"""Idempotent consumer 헬퍼 (Phase 2.2.2).

Redis Streams 는 at-least-once 라 같은 event_id 가 두 번 이상 배달될 수 있다.
다운스트림(DB write, 외부 API 호출)이 부수효과를 가지면 재처리는 데이터 정합성을
깬다. `run.processed_event` 에 (event_id, consumer_name) 마킹으로 멱등 보장.

흐름:
  1. handler 실행 직전, `INSERT ... ON CONFLICT DO NOTHING` 시도.
  2. 0행 영향 → 이미 처리됨 → handler skip, 호출자가 ACK 만 수행.
  3. 1행 영향 → 신규 → handler 실행 → commit. handler 실패 시 ROLLBACK 으로 마킹도
     함께 사라져 다음 read 에서 재시도 가능.

같은 트랜잭션에서 마킹 + 처리 — handler 가 외부 API 같은 비DB 부수효과를 일으키면
'마킹 후 commit 직전 crash' 에서 외부 효과만 발생하고 마킹 미완으로 재처리 가능.
이 경우 handler 자체가 idempotent 여야 함 (Phase 2 외부 API 호출은 Idempotency-Key
헤더로 처리).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.run import ProcessedEvent

T = TypeVar("T")


@dataclass(slots=True, frozen=True)
class ConsumeResult(Generic[T]):
    """결과 — `processed=True` 면 신규 처리, `False` 면 멱등 skip.

    `value` 는 handler 의 반환값 (skip 시 None).
    """

    processed: bool
    value: T | None


def consume_idempotent(
    session: Session,
    *,
    event_id: str,
    consumer_name: str,
    handler: Callable[[Session], T],
) -> ConsumeResult[T]:
    """`run.processed_event` 마킹과 handler 실행을 한 트랜잭션으로 묶음.

    호출자(consumer loop)는 commit/rollback 책임을 이 함수에 위임한다 — 함수 내부에서
    commit 까지 끝낸다. 외부 트랜잭션과 합치려면 `session.begin_nested()` 사용 후
    호출자가 외부 commit 하면 된다.
    """
    if not event_id or not consumer_name:
        raise ValueError("event_id and consumer_name are required")

    stmt = (
        pg_insert(ProcessedEvent)
        .values(event_id=event_id, consumer_name=consumer_name)
        .on_conflict_do_nothing(index_elements=["event_id", "consumer_name"])
    )
    result = session.execute(stmt)
    rowcount: int = getattr(result, "rowcount", 0) or 0
    inserted = rowcount > 0

    if not inserted:
        # 이미 처리됨 — 트랜잭션 닫고 handler skip.
        session.rollback()
        return ConsumeResult(processed=False, value=None)

    try:
        value = handler(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return ConsumeResult(processed=True, value=value)


def reset_processed_marker(session: Session, *, event_id: str, consumer_name: str) -> int:
    """수동 replay 도구용 — 운영자가 특정 (event_id, consumer) 마킹을 지움.

    이후 같은 event_id 가 다시 들어오면 재처리. 호출자가 commit 책임.
    """
    result = session.execute(
        delete(ProcessedEvent)
        .where(ProcessedEvent.event_id == event_id)
        .where(ProcessedEvent.consumer_name == consumer_name)
    )
    rowcount: int = getattr(result, "rowcount", 0) or 0
    return rowcount


__all__ = [
    "ConsumeResult",
    "consume_idempotent",
    "reset_processed_marker",
]
