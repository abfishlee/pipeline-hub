"""OCR worker actor (Phase 2.2.4).

`process_ocr_event(event_id, raw_object_id, partition_date_iso)` actor 가 enqueue
되면 도메인 함수 `process_receipt` 를 idempotent 하게 호출.

트리거:
  - 1차: outbox publisher 가 stream 으로 이송 → 별도 consumer loop (Phase 2.2.7) 가
    `dp:events:raw_object` 의 `event_type=ingest.receipt.received` 만 필터해
    `process_ocr_event.send(...)`.
  - 2차(임시 / 운영자 재처리): 운영 도구가 직접 send.

Actor 는 얇음 — 도메인 + idempotent_consume 만 호출. 트랜잭션 commit 은 도메인이
자체 처리(consume_idempotent 가 끝낸 뒤 호출자 별도 commit 불필요).
"""

from __future__ import annotations

from contextlib import suppress
from datetime import date as DateType
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.core.events import RedisStreamPublisher
from app.db.sync_session import get_sync_sessionmaker
from app.domain.idempotent_consume import consume_idempotent
from app.domain.ocr import OcrOutcome, process_receipt
from app.integrations.clova import ClovaOcrProvider
from app.integrations.object_storage import get_object_storage
from app.integrations.ocr.types import OcrProvider
from app.integrations.upstage import UpstageOcrProvider
from app.workers import pipeline_actor


def _build_providers() -> list[OcrProvider]:
    """Settings 기반 provider 체인. 비활성(미설정) provider 는 자동 제외.

    의도적으로 호출 시점마다 새로 만든다 — Settings 변경 즉시 반영 + 단순함.
    httpx.AsyncClient 는 `aclose` 가 있지만 Phase 2.2.4 단순화로 매 호출 lifecycle
    종료 (process 1회 호출 = client 1개). 트래픽 늘면 풀링 도입.
    """
    s = get_settings()
    providers: list[OcrProvider] = []
    if s.clova_ocr_url and s.clova_ocr_secret.get_secret_value():
        providers.append(
            ClovaOcrProvider(
                api_url=s.clova_ocr_url,
                secret=s.clova_ocr_secret.get_secret_value(),
            )
        )
    upstage_key = s.upstage_api_key.get_secret_value()
    if upstage_key:
        providers.append(UpstageOcrProvider(api_url=s.upstage_ocr_url, api_key=upstage_key))
    return providers


@pipeline_actor(queue_name="ocr", max_retries=3, time_limit=120_000)
def process_ocr_event(
    event_id: str,
    raw_object_id: int,
    partition_date_iso: str,
) -> dict[str, Any]:
    """outbox event 1건을 OCR 파이프라인에 흘림. 결과 통계를 dict 로 반환.

    Args:
      event_id: outbox `event_id` (idempotency key).
      raw_object_id: 원본 raw_object PK.
      partition_date_iso: `YYYY-MM-DD`.
    """
    sm = get_sync_sessionmaker()
    publisher = RedisStreamPublisher.from_settings()
    providers = _build_providers()
    pdate = _parse_date(partition_date_iso)

    try:
        with sm() as session:
            result = consume_idempotent(
                session,
                event_id=event_id,
                consumer_name="ocr-worker",
                handler=lambda s: process_receipt(
                    s,
                    publisher,
                    get_object_storage(),
                    providers,
                    raw_object_id=raw_object_id,
                    partition_date=pdate,
                ),
            )
        if not result.processed:
            return {"status": "skipped_idempotent", "event_id": event_id}
        outcome: OcrOutcome | None = result.value
        assert outcome is not None
        return {
            "status": "processed",
            "event_id": event_id,
            "raw_object_id": outcome.raw_object_id,
            "page_count": outcome.page_count,
            "avg_confidence": outcome.avg_confidence,
            "provider": outcome.provider,
            "crowd_task_id": outcome.crowd_task_id,
        }
    finally:
        publisher.close()
        for p in providers:
            with suppress(Exception):
                # ClovaOcrProvider / UpstageOcrProvider 둘 다 aclose 비동기.
                # worker 는 sync 라 close 가능하면 닫고 아니면 무시.
                close = getattr(p, "aclose", None)
                if close is None:
                    continue
                # asyncio.run 으로 즉시 종료.
                import asyncio

                asyncio.run(close())


def _parse_date(iso: str) -> DateType:
    return datetime.strptime(iso, "%Y-%m-%d").date()


__all__ = ["process_ocr_event"]
