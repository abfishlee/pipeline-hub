"""Outbox publisher 도메인 (Phase 2.2.1).

흐름:
  1. `run.event_outbox` 의 PENDING N건을 `SELECT ... FOR UPDATE SKIP LOCKED` 로 잠금
     (다중 worker 안전).
  2. 각 행을 Redis Streams 에 XADD (`<prefix>:<aggregate_type>`).
  3. 같은 트랜잭션에서 `status='PUBLISHED'`, `published_at=now()` 마킹.
  4. XADD 실패 시 `attempt_no += 1`, `last_error` 갱신. attempt_no >= max_attempts
     이면 `status='FAILED'` (이후 운영자가 수동 replay).

At-least-once 보증:
  - XADD 후 commit 전 worker crash → row 가 다시 PENDING 으로 보임 → 재시도 시 같은
    이벤트가 stream 에 또 들어감 → idempotent consumer 가 흡수.
  - commit 후 worker crash → 안전 (이미 PUBLISHED).

Worker 가 sync 라 sync session 사용. 같은 ORM 모델 공유.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.events import RedisStreamPublisher
from app.models.run import EventOutbox


@dataclass(slots=True, frozen=True)
class PublishStats:
    selected: int
    published: int
    failed: int


def publish_pending_events(
    session: Session,
    publisher: RedisStreamPublisher,
    *,
    batch_size: int,
    max_attempts: int,
) -> PublishStats:
    """PENDING 이벤트 한 배치를 발행. 호출자가 트랜잭션 커밋."""
    locked_rows = (
        session.execute(
            select(EventOutbox)
            .where(EventOutbox.status == "PENDING")
            .order_by(EventOutbox.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )

    selected = len(locked_rows)
    published = 0
    failed = 0
    now = datetime.now(UTC)

    for row in locked_rows:
        try:
            publisher.xadd(
                row.aggregate_type,
                {
                    "event_id": str(row.event_id),
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "event_type": row.event_type,
                    "occurred_at": row.created_at.isoformat() if row.created_at else "",
                    "payload": row.payload_json,
                },
            )
        except Exception as exc:
            new_attempt = row.attempt_no + 1
            new_status = "FAILED" if new_attempt >= max_attempts else "PENDING"
            session.execute(
                update(EventOutbox)
                .where(EventOutbox.event_id == row.event_id)
                .values(
                    status=new_status,
                    attempt_no=new_attempt,
                    last_error=f"{type(exc).__name__}: {exc}"[:2000],
                )
            )
            failed += 1
            continue

        session.execute(
            update(EventOutbox)
            .where(EventOutbox.event_id == row.event_id)
            .values(status="PUBLISHED", published_at=now, last_error=None)
        )
        published += 1

    session.commit()
    return PublishStats(selected=selected, published=published, failed=failed)


__all__ = ["PublishStats", "publish_pending_events"]
