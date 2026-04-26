"""CDC consumer worker (Phase 4.2.3) — wal2json slot stream → raw.db_cdc_event.

각 enabled 한 `ctl.cdc_subscription` 마다 daemon-style actor 가 1배치를 폴링하고
종료. cron 또는 self-rescheduling 으로 반복 호출. PoC 단계라 단일 actor + time_limit
60s 로 시작 — 운영 시 source 별 dedicated queue + concurrency 분리 검토.

호출 패턴:
  - `dispatch_cdc_batch.send(source_id=N)` — 1회 1배치 처리.
  - airflow `cdc_lag_monitor_dag` 가 매 5분 enabled 한 모든 source 에 대해 enqueue.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.sync_session import get_sync_sessionmaker
from app.integrations.cdc.wal2json_consumer import (
    parse_wal2json_batch,
    persist_cdc_changes,
    stream_slot,
    update_lag_metric,
)
from app.models.ctl import CdcSubscription
from app.workers import pipeline_actor

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
DEFAULT_BATCH_TIME_LIMIT_MS = 60_000


@pipeline_actor(
    queue_name="cdc_consumer",
    max_retries=3,
    time_limit=DEFAULT_BATCH_TIME_LIMIT_MS,
)
def dispatch_cdc_batch(source_id: int, batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    """source_id 의 slot 에서 batch_size 개 메시지를 읽고 적재.

    환경에서 wal2json 가 미가동이거나 slot 이 없으면 lag 갱신만 하고 종료.
    """
    sm = get_sync_sessionmaker()
    settings = get_settings()
    inserted = 0
    polled = 0
    with sm() as session:
        sub = session.execute(
            select(CdcSubscription).where(CdcSubscription.source_id == source_id)
        ).scalar_one_or_none()
        if sub is None or not sub.enabled:
            return {"source_id": source_id, "skipped": True, "reason": "no_subscription"}
        slot_name = sub.slot_name
        publication_name = sub.publication_name

        try:
            stream = stream_slot(
                dsn=_sync_dsn(settings.database_url),
                slot_name=slot_name,
                publication_name=publication_name,
            )
            messages: list[tuple[str, str]] = []
            for i, (lsn, payload) in enumerate(stream):
                messages.append((lsn, payload))
                if i + 1 >= batch_size:
                    break
            polled = len(messages)
            changes = parse_wal2json_batch(messages)
            inserted = persist_cdc_changes(
                session, source_id=source_id, changes=changes
            )
        except Exception as exc:
            logger.warning(
                "cdc_consumer.stream_failed source_id=%s slot=%s err=%s",
                source_id,
                slot_name,
                exc,
            )

        # lag 갱신은 항상 시도 — slot 미가동이어도 None 만 기록되고 끝.
        lag = update_lag_metric(session, source_id=source_id)
        session.commit()

    return {
        "source_id": source_id,
        "polled": polled,
        "inserted": inserted,
        "lag_bytes": lag,
    }


def _sync_dsn(database_url: str) -> str:
    """SQLAlchemy URL → libpq DSN (replication 모드 호환)."""
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url[len("postgresql+asyncpg://") :]
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url[len("postgresql+psycopg://") :]
    return database_url


__all__ = ["dispatch_cdc_batch"]
