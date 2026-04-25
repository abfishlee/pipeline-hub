"""Outbox publisher actor (Phase 2.2.1, 2.2.9 backlog 갱신 추가).

`publish_outbox_batch.send()` 로 enqueue 하면 한 배치를 발행한 뒤, 같은 호출에서
백로그 메트릭(outbox_pending / dramatiq_queue_lag / dead_letter_pending) 도 갱신.

Actor 는 얇은 래퍼 — 실제 로직은 `app.domain.outbox.publish_pending_events`.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.config import get_settings
from app.core import metrics
from app.core.event_topics import EventTopic
from app.core.events import RedisStreamPublisher
from app.db.sync_session import get_sync_sessionmaker
from app.domain.outbox import publish_pending_events
from app.models.run import DeadLetter, EventOutbox
from app.workers import pipeline_actor

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _refresh_backlog_metrics(session: Session, publisher: RedisStreamPublisher) -> None:
    """outbox PENDING / dead_letter PENDING / Redis Streams XLEN 일괄 갱신."""
    pending = (
        session.execute(
            select(func.count(EventOutbox.event_id)).where(EventOutbox.status == "PENDING")
        ).scalar_one()
        or 0
    )
    metrics.outbox_pending_total.set(int(pending))

    dl_pending = (
        session.execute(
            select(func.count(DeadLetter.dl_id)).where(DeadLetter.replayed_at.is_(None))
        ).scalar_one()
        or 0
    )
    metrics.dead_letter_pending_total.set(int(dl_pending))

    # 알려진 토픽 XLEN — group lag 정밀 추적은 향후 sub-phase.
    for topic in EventTopic:
        length: int = 0
        try:
            raw = publisher._client.xlen(publisher.stream_key(topic.value))
            # redis-py 동기 클라이언트 — 실제 반환은 int. cast 로 mypy 만족.
            length = int(raw) if isinstance(raw, int | str) else 0
        except Exception:
            length = 0
        metrics.dramatiq_queue_lag_seconds.labels(topic=topic.value).set(length)


@pipeline_actor(queue_name="outbox", max_retries=3, time_limit=30_000)
def publish_outbox_batch() -> dict[str, int]:
    """현재 PENDING 한 배치를 발행 + 백로그 메트릭 갱신. 결과 통계를 dict 로 반환."""
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
            with contextlib.suppress(Exception):
                _refresh_backlog_metrics(session, publisher)
        return {
            "selected": stats.selected,
            "published": stats.published,
            "failed": stats.failed,
        }
    finally:
        publisher.close()


__all__ = ["publish_outbox_batch"]
