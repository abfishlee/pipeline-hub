"""Outbox publisher actor (Phase 2.2.1).

`publish_outbox_batch.send()` 로 enqueue 하면 한 배치를 발행한다.
정식 폴링 데몬(주기적 자가 트리거)은 Phase 2.2.6 추가 예정.

Actor 는 얇은 래퍼 — 실제 로직은 `app.domain.outbox.publish_pending_events`.
"""

from __future__ import annotations

from app.config import get_settings
from app.core.events import RedisStreamPublisher
from app.db.sync_session import get_sync_sessionmaker
from app.domain.outbox import publish_pending_events
from app.workers import pipeline_actor


@pipeline_actor(queue_name="outbox", max_retries=3, time_limit=30_000)
def publish_outbox_batch() -> dict[str, int]:
    """현재 PENDING 한 배치를 발행. 결과 통계를 dict 로 반환."""
    settings = get_settings()
    sm = get_sync_sessionmaker()
    publisher = RedisStreamPublisher.from_settings(settings)
    try:
        with sm() as session:
            stats = publish_pending_events(
                session,
                publisher,
                batch_size=settings.outbox_batch_size,
                max_attempts=settings.outbox_max_attempts,
            )
        return {
            "selected": stats.selected,
            "published": stats.published,
            "failed": stats.failed,
        }
    finally:
        publisher.close()


__all__ = ["publish_outbox_batch"]
