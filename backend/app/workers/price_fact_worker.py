"""price_fact 워커 actor (Phase 2.2.6).

`staging.ready` 이벤트 1건을 받으면 `propagate_price_fact` 도메인 호출.
trigger:
  - 1차: outbox publisher 가 `dp:events:staging` 으로 이송 → consumer loop (Phase
    2.2.7) 가 본 actor 로 forward.
  - 2차(임시 / 운영자 재처리): 직접 send.

Actor 는 얇음 — domain + idempotent_consume 만 호출.
"""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.db.sync_session import get_sync_sessionmaker
from app.domain.idempotent_consume import consume_idempotent
from app.domain.price_fact import PriceFactOutcome, propagate_price_fact
from app.workers import pipeline_actor


@pipeline_actor(queue_name="price_fact", max_retries=3, time_limit=120_000)
def process_price_fact_event(
    event_id: str,
    raw_object_id: int,
    partition_date_iso: str,
    sample_rate: float | None = None,
) -> dict[str, Any]:
    """staging.ready event 1건 처리. 결과 통계 dict."""
    settings = get_settings()
    sm = get_sync_sessionmaker()
    pdate = _parse_date(partition_date_iso)
    rate = sample_rate if sample_rate is not None else settings.price_fact_sample_rate

    with sm() as session:
        result = consume_idempotent(
            session,
            event_id=event_id,
            consumer_name="price-fact-worker",
            handler=lambda s: propagate_price_fact(
                s,
                raw_object_id=raw_object_id,
                partition_date=pdate,
                sample_rate=rate,
            ),
        )
    if not result.processed:
        return {"status": "skipped_idempotent", "event_id": event_id}
    outcome: PriceFactOutcome | None = result.value
    assert outcome is not None
    return {
        "status": "processed",
        "event_id": event_id,
        "raw_object_id": outcome.raw_object_id,
        "inserted": outcome.inserted_count,
        "sampled": outcome.sampled_count,
        "held": outcome.held_count,
        "skipped": outcome.skipped_count,
    }


def _parse_date(iso: str) -> DateType:
    return datetime.strptime(iso, "%Y-%m-%d").date()


__all__ = ["process_price_fact_event"]
