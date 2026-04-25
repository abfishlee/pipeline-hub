"""OCR 도메인 (Phase 2.2.4).

워커가 호출:
  1. `raw.raw_object` 에서 영수증 메타 로드 (sync session).
  2. Object Storage 에서 image bytes 다운로드 (async, asyncio.run 으로 호출).
  3. OCR provider 순차 시도 (CLOVA → Upstage 폴백).
  4. `raw.ocr_result` 페이지별 INSERT.
  5. avg_confidence ≥ threshold 면 `ocr.completed` outbox.
     미달이면 `run.crowd_task` placeholder INSERT + `crowd.task.created` outbox.
  6. 호출자가 commit 책임.

idempotency 는 호출 측 `consume_idempotent` 가 보장 ((event_id, consumer_name) 마킹).
이 함수 자체는 멱등하지 않으므로 같은 (raw_object_id) 로 두 번 호출하면 ocr_result
가 중복 적재된다. 운영 도구로 raw_object 재처리 시 사전 cleanup 필요.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as DateType

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import metrics
from app.core.events import RedisStreamPublisher
from app.integrations.object_storage import ObjectStorage
from app.integrations.ocr.types import OcrError, OcrProvider, OcrResponse
from app.models.raw import OcrResult, RawObject
from app.models.run import CrowdTask, EventOutbox

# < 0.85 → crowd_task placeholder (`docs/phases/PHASE_2_RUNTIME.md` 2.2.4 정책).
DEFAULT_CONFIDENCE_THRESHOLD = 0.85


@dataclass(slots=True, frozen=True)
class OcrOutcome:
    raw_object_id: int
    partition_date: DateType
    ocr_result_ids: tuple[int, ...]
    page_count: int
    avg_confidence: float
    provider: str
    duration_ms: int
    crowd_task_id: int | None  # 미달 시 발급된 placeholder.


def _parse_object_uri(uri: str) -> tuple[str, str]:
    """`s3://bucket/key` or `nos://bucket/key` → (bucket, key). 같은 bucket 여러 key."""
    for scheme in ("s3://", "nos://"):
        if uri.startswith(scheme):
            rest = uri[len(scheme) :]
            bucket, sep, key = rest.partition("/")
            if not sep or not key:
                raise ValueError(f"invalid object_uri (no key): {uri!r}")
            return bucket, key
    raise ValueError(f"unsupported object_uri scheme: {uri!r}")


async def _fetch_and_recognize(
    storage: ObjectStorage,
    providers: Sequence[OcrProvider],
    *,
    object_key: str,
    content_type: str,
) -> tuple[bytes, OcrResponse]:
    """다운로드 후 provider 순차 시도. 모두 실패 시 마지막 OcrError 전파."""
    image_bytes = await storage.get_bytes(object_key)
    if not providers:
        raise OcrError("no OCR providers configured")

    last_exc: OcrError | None = None
    for provider in providers:
        started = time.perf_counter()
        try:
            response = await provider.recognize(image_bytes=image_bytes, content_type=content_type)
        except OcrError as exc:
            last_exc = exc
            metrics.ocr_requests_total.labels(provider=provider.name, status="failure").inc()
            metrics.ocr_duration_seconds.labels(provider=provider.name).observe(
                time.perf_counter() - started
            )
            continue
        else:
            metrics.ocr_requests_total.labels(provider=provider.name, status="success").inc()
            metrics.ocr_duration_seconds.labels(provider=provider.name).observe(
                response.duration_ms / 1000.0
            )
            return image_bytes, response

    assert last_exc is not None
    raise last_exc


def process_receipt(
    session: Session,
    publisher: RedisStreamPublisher,
    storage: ObjectStorage,
    providers: Sequence[OcrProvider],
    *,
    raw_object_id: int,
    partition_date: DateType,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    content_type: str = "image/jpeg",
) -> OcrOutcome:
    """영수증 1건 OCR 처리. publisher 는 outbox 와 별도로 즉시 stream 발행에도 활용 가능
    하지만 본 함수는 outbox 만 적재 (Phase 2.2.1 publisher 가 stream 으로 이송)."""

    raw = session.execute(
        select(RawObject)
        .where(RawObject.raw_object_id == raw_object_id)
        .where(RawObject.partition_date == partition_date)
    ).scalar_one_or_none()
    if raw is None:
        raise OcrError(f"raw_object not found: id={raw_object_id} date={partition_date}")
    if not raw.object_uri:
        raise OcrError(f"raw_object {raw_object_id} has no object_uri (not a file/receipt)")

    _, object_key = _parse_object_uri(raw.object_uri)

    # async IO: storage 다운로드 + OCR 호출
    image_bytes, response = asyncio.run(
        _fetch_and_recognize(storage, providers, object_key=object_key, content_type=content_type)
    )
    del image_bytes  # 메모리 해제 — 페이지 결과만 들고 간다.

    # 페이지별 ocr_result INSERT (sync ORM)
    page_avg_confs: list[float] = []
    new_rows: list[OcrResult] = []
    for page in response.pages:
        # confidence 컬럼은 NUMERIC(5,2) 라 0~100 스케일로 저장.
        score_pct = round(page.confidence * 100, 2)
        row = OcrResult(
            raw_object_id=raw_object_id,
            partition_date=partition_date,
            page_no=page.page_no,
            text_content=page.text,
            confidence_score=score_pct,
            layout_json=page.layout,
            engine_name=response.provider,
            engine_version=response.engine_version,
            duration_ms=response.duration_ms,
        )
        session.add(row)
        new_rows.append(row)
        page_avg_confs.append(page.confidence)
    session.flush()  # ocr_result_id 채움.
    inserted_ids: list[int] = [r.ocr_result_id for r in new_rows]

    avg_confidence = sum(page_avg_confs) / len(page_avg_confs) if page_avg_confs else 0.0
    metrics.ocr_confidence.labels(provider=response.provider).observe(avg_confidence)

    # 미달 → crowd_task placeholder.
    crowd_task_id: int | None = None
    if avg_confidence < confidence_threshold:
        crowd = CrowdTask(
            raw_object_id=raw_object_id,
            partition_date=partition_date,
            ocr_result_id=inserted_ids[0] if inserted_ids else None,
            reason="ocr_low_confidence",
            status="PENDING",
            payload_json={
                "avg_confidence": round(avg_confidence, 4),
                "threshold": confidence_threshold,
                "provider": response.provider,
                "page_count": len(response.pages),
            },
        )
        session.add(crowd)
        session.flush()
        crowd_task_id = crowd.crowd_task_id
        metrics.crowd_task_created_total.labels(reason="ocr_low_confidence").inc()

        session.add(
            EventOutbox(
                aggregate_type="crowd_task",
                aggregate_id=str(crowd_task_id),
                event_type="crowd.task.created",
                payload_json={
                    "crowd_task_id": crowd_task_id,
                    "raw_object_id": raw_object_id,
                    "partition_date": partition_date.isoformat(),
                    "ocr_result_id": inserted_ids[0] if inserted_ids else None,
                    "reason": "ocr_low_confidence",
                    "status": "PENDING",
                },
            )
        )

    # ocr.completed outbox — confidence 무관하게 항상 발행 (다운스트림 표준화는 미달이면
    # crowd 결과를 기다리도록 자체 분기).
    session.add(
        EventOutbox(
            aggregate_type="ocr_result",
            aggregate_id=f"{raw_object_id}:{partition_date.isoformat()}",
            event_type="ocr.completed",
            payload_json={
                "raw_object_id": raw_object_id,
                "partition_date": partition_date.isoformat(),
                "ocr_result_ids": inserted_ids,
                "page_count": len(response.pages),
                "avg_confidence": round(avg_confidence, 4),
                "provider": response.provider,
                "engine_version": response.engine_version,
                "duration_ms": response.duration_ms,
                "crowd_task_id": crowd_task_id,
            },
        )
    )

    # raw_object 상태 갱신 — PROCESSED.
    raw.status = "PROCESSED"

    # publisher 는 미사용 (commit 후 outbox publisher 가 따로 stream 으로 이송).
    # 시그니처에 남긴 이유: 향후 즉시 발행 모드 확장 여지.
    _ = publisher

    return OcrOutcome(
        raw_object_id=raw_object_id,
        partition_date=partition_date,
        ocr_result_ids=tuple(inserted_ids),
        page_count=len(response.pages),
        avg_confidence=round(avg_confidence, 6),
        provider=response.provider,
        duration_ms=response.duration_ms,
        crowd_task_id=crowd_task_id,
    )


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "OcrOutcome",
    "process_receipt",
]
