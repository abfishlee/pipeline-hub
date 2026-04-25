"""Transform worker actor (Phase 2.2.5).

`dp:events:raw_object` 의 `event_type=ingest.api.received|ingest.file.received`
이벤트가 enqueue 되면 transform 도메인 호출. `ocr.completed` 도 같은 워커에서
처리 (영수증 OCR 결과가 곧바로 standard_record/price_observation 으로 이어지도록).

actor 는 얇음 — domain 함수 호출만. consume_idempotent 로 멱등.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import date as DateType
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.db.sync_session import get_sync_sessionmaker
from app.domain.idempotent_consume import consume_idempotent
from app.domain.transform import TransformOutcome, process_record
from app.integrations.hyperclova import (
    EmbeddingClient,
    HyperClovaEmbeddingClient,
)
from app.workers import pipeline_actor


def _build_embedding_client() -> EmbeddingClient | None:
    s = get_settings()
    api_key = s.hyperclova_api_key.get_secret_value()
    if not api_key:
        return None
    return HyperClovaEmbeddingClient(
        api_url=s.hyperclova_api_url,
        embedding_app=s.hyperclova_embedding_app,
        api_key=api_key,
        dimension=s.embedding_dim,
    )


@pipeline_actor(queue_name="transform", max_retries=3, time_limit=120_000)
def process_transform_event(
    event_id: str,
    raw_object_id: int,
    partition_date_iso: str,
) -> dict[str, Any]:
    """outbox event 1건을 transform 파이프라인에 흘림."""
    sm = get_sync_sessionmaker()
    settings = get_settings()
    pdate = _parse_date(partition_date_iso)
    embedding_client = _build_embedding_client()

    try:
        with sm() as session:
            result = consume_idempotent(
                session,
                event_id=event_id,
                consumer_name="transform-worker",
                handler=lambda s: process_record(
                    s,
                    raw_object_id=raw_object_id,
                    partition_date=pdate,
                    embedding_client=embedding_client,
                    trigram_threshold=settings.std_trigram_threshold,
                    embedding_threshold=settings.std_embedding_threshold,
                ),
            )
        if not result.processed:
            return {"status": "skipped_idempotent", "event_id": event_id}
        outcome: TransformOutcome | None = result.value
        assert outcome is not None
        return {
            "status": "processed",
            "event_id": event_id,
            "raw_object_id": outcome.raw_object_id,
            "record_count": outcome.record_count,
            "matched_count": outcome.matched_count,
            "crowd_task_count": outcome.crowd_task_count,
        }
    finally:
        if embedding_client is not None:
            with suppress(Exception):
                close = getattr(embedding_client, "aclose", None)
                if close is not None:
                    import asyncio

                    asyncio.run(close())


def _parse_date(iso: str) -> DateType:
    return datetime.strptime(iso, "%Y-%m-%d").date()


__all__ = ["process_transform_event"]
