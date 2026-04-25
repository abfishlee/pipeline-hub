"""Transform 도메인 (Phase 2.2.5).

raw_object → stg.standard_record + stg.price_observation 적재 + std_code 매핑 시도.

지원 입력 모양:
  - `payload_json` 이 dict 이고 `items` 가 라인 배열인 경우 (수집 API JSON / 영수증 OCR
    파서 결과 모두 이 형태로 정규화). 각 line 은 최소 `name` + `price` 필요.
  - 다른 모양 (e.g. CSV, raw bytes 만 있는 IMAGE) → 도메인이 빈 배치 처리, outbox 만
    `staging.ready` 0건으로 발행 (다운스트림이 무시).

매핑 정책:
  - 라인별 `resolve_std_code(label_ko=line["name"])`
  - trigram_hit / embedding_hit → `price_observation.std_code` 채움 + `std_confidence`
  - crowd → `run.crowd_task("std_low_confidence")` placeholder + outbox(crowd.task.created)

호출자가 commit 책임 (`consume_idempotent` 가 자체 트랜잭션).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as DateType
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import metrics
from app.domain.standardization import (
    DEFAULT_EMBEDDING_THRESHOLD,
    DEFAULT_TRIGRAM_THRESHOLD,
    resolve_std_code,
)
from app.integrations.hyperclova import EmbeddingClient
from app.models.raw import RawObject
from app.models.run import CrowdTask, EventOutbox
from app.models.stg import PriceObservation, StandardRecord


@dataclass(slots=True, frozen=True)
class TransformOutcome:
    raw_object_id: int
    partition_date: DateType
    record_count: int
    matched_count: int
    crowd_task_count: int
    standard_record_ids: tuple[int, ...]
    price_observation_ids: tuple[int, ...]


def _extract_lines(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """payload_json → 가격 라인 배열. items 외 다른 명칭(`lines`, `data`)도 허용."""
    if not payload:
        return []
    for key in ("items", "lines", "data"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [c for c in candidate if isinstance(c, dict)]
    return []


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def process_record(
    session: Session,
    *,
    raw_object_id: int,
    partition_date: DateType,
    embedding_client: EmbeddingClient | None,
    trigram_threshold: float = DEFAULT_TRIGRAM_THRESHOLD,
    embedding_threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
) -> TransformOutcome:
    raw = session.execute(
        select(RawObject)
        .where(RawObject.raw_object_id == raw_object_id)
        .where(RawObject.partition_date == partition_date)
    ).scalar_one_or_none()
    if raw is None:
        raise ValueError(f"raw_object not found: id={raw_object_id} date={partition_date}")

    lines = _extract_lines(raw.payload_json)

    standard_rows: list[StandardRecord] = []
    obs_rows: list[PriceObservation] = []
    matched = 0
    crowd_tasks: list[CrowdTask] = []
    now = datetime.now(UTC)

    for line in lines:
        name_raw = str(line.get("name") or "").strip()
        if not name_raw:
            continue
        price = _to_decimal(line.get("price"))
        if price is None:
            continue

        # 1) standardization 매칭
        resolution = resolve_std_code(
            session,
            name_raw,
            embedding_client=embedding_client,
            trigram_threshold=trigram_threshold,
            embedding_threshold=embedding_threshold,
        )

        # 2) standard_record (entity_type=PRICE)
        sr = StandardRecord(
            source_id=raw.source_id,
            raw_object_id=raw.raw_object_id,
            raw_partition=raw.partition_date,
            entity_type="PRICE",
            business_key=line.get("sku") or None,
            record_json={
                "name": name_raw,
                "price": str(price),
                "raw": line,
                "matched_std_code": resolution.std_code,
                "matched_strategy": resolution.strategy,
            },
            observed_at=now,
        )
        session.add(sr)
        standard_rows.append(sr)

        # 3) price_observation
        obs = PriceObservation(
            source_id=raw.source_id,
            raw_object_id=raw.raw_object_id,
            raw_partition=raw.partition_date,
            retailer_code=str(line.get("retailer_code") or "") or None,
            seller_name=str(line.get("seller_name") or "") or None,
            store_name=str(line.get("store_name") or "") or None,
            product_name_raw=name_raw,
            std_code=resolution.std_code,
            std_confidence=(round(resolution.confidence * 100, 2) if resolution.std_code else None),
            sale_unit=str(line.get("unit") or "") or None,
            price_krw=price,
            currency=str(line.get("currency") or "KRW"),
            observed_at=now,
            standardized_at=now if resolution.std_code else None,
        )
        session.add(obs)
        obs_rows.append(obs)

        if resolution.std_code is not None:
            matched += 1
        else:
            ct = CrowdTask(
                raw_object_id=raw.raw_object_id,
                partition_date=raw.partition_date,
                ocr_result_id=None,
                reason="std_low_confidence",
                status="PENDING",
                payload_json={
                    "label_ko": name_raw,
                    "trigram_threshold": trigram_threshold,
                    "embedding_threshold": embedding_threshold,
                },
            )
            session.add(ct)
            crowd_tasks.append(ct)
            metrics.crowd_task_created_total.labels(reason="std_low_confidence").inc()

    session.flush()  # PK 채움.

    standard_ids = tuple(r.record_id for r in standard_rows)
    obs_ids = tuple(r.obs_id for r in obs_rows)

    # 4) crowd_task → outbox
    for ct in crowd_tasks:
        session.add(
            EventOutbox(
                aggregate_type="crowd_task",
                aggregate_id=str(ct.crowd_task_id),
                event_type="crowd.task.created",
                payload_json={
                    "crowd_task_id": ct.crowd_task_id,
                    "raw_object_id": raw.raw_object_id,
                    "partition_date": raw.partition_date.isoformat(),
                    "ocr_result_id": None,
                    "reason": "std_low_confidence",
                    "status": "PENDING",
                },
            )
        )

    # 5) staging.ready outbox — 0건이어도 발행 (다운스트림이 raw 처리 완료 인식).
    session.add(
        EventOutbox(
            aggregate_type="staging",
            aggregate_id=f"{raw.raw_object_id}:{raw.partition_date.isoformat()}",
            event_type="staging.ready",
            payload_json={
                "raw_object_id": raw.raw_object_id,
                "partition_date": raw.partition_date.isoformat(),
                "record_count": len(standard_rows),
                "price_observation_count": len(obs_rows),
                "standard_record_ids": list(standard_ids),
                "price_observation_ids": list(obs_ids),
                "matched_count": matched,
                "crowd_task_count": len(crowd_tasks),
            },
        )
    )

    raw.status = "PROCESSED"

    return TransformOutcome(
        raw_object_id=raw.raw_object_id,
        partition_date=raw.partition_date,
        record_count=len(standard_rows),
        matched_count=matched,
        crowd_task_count=len(crowd_tasks),
        standard_record_ids=standard_ids,
        price_observation_ids=obs_ids,
    )


__all__ = ["TransformOutcome", "process_record"]
