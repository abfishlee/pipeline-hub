"""DLQ 미들웨어 — max_retries 초과 후 `run.dead_letter` INSERT 검증.

브로커는 StubBroker 강제(`APP_DRAMATIQ_STUB=1`) — Redis 미가동에서도 미들웨어 자체
로직 검증. 실 PG 는 필요 (`run.dead_letter` INSERT 확인).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select

from app.db.sync_session import get_sync_sessionmaker
from app.models.run import DeadLetter


@pytest.fixture(scope="module", autouse=True)
def _force_stub_broker() -> Iterator[None]:
    prev = os.environ.get("APP_DRAMATIQ_STUB")
    os.environ["APP_DRAMATIQ_STUB"] = "1"
    yield
    if prev is None:
        os.environ.pop("APP_DRAMATIQ_STUB", None)
    else:
        os.environ["APP_DRAMATIQ_STUB"] = prev


@pytest.fixture
def cleanup_dlq() -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(DeadLetter).where(DeadLetter.dl_id.in_(ids)))
        session.commit()


def test_dlq_records_permanently_failed_message(cleanup_dlq: list[int]) -> None:
    """retries == max_retries 일 때 DeadLetterMiddleware 가 dead_letter INSERT."""
    from app.workers import DeadLetterMiddleware

    middleware = DeadLetterMiddleware()

    fake_message = MagicMock()
    fake_message.actor_name = "test_actor_boom"
    fake_message.message_id = "msg-it-001"
    fake_message.queue_name = "test"
    fake_message.args = ("hello", 42)
    fake_message.kwargs = {"flag": True}
    fake_message.options = {"retries": 3, "max_retries": 3}

    middleware.after_process_message(
        broker=MagicMock(),
        message=fake_message,
        result=None,
        exception=RuntimeError("intentional failure"),
    )

    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = (
            session.execute(
                select(DeadLetter)
                .where(DeadLetter.origin == "test_actor_boom")
                .order_by(DeadLetter.dl_id.desc())
                .limit(1)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        dl = rows[0]
        cleanup_dlq.append(dl.dl_id)
        assert dl.error_message is not None
        assert "intentional failure" in dl.error_message
        assert dl.payload_json["args"] == ["hello", 42]
        assert dl.payload_json["kwargs"] == {"flag": True}
        assert dl.payload_json["message_id"] == "msg-it-001"


def test_dlq_skipped_when_retries_remaining() -> None:
    """retries < max_retries — DLQ INSERT 가 발생하면 안 됨."""
    from app.workers import DeadLetterMiddleware

    middleware = DeadLetterMiddleware()

    sm = get_sync_sessionmaker()
    with sm() as session:
        before = session.execute(
            select(DeadLetter).where(DeadLetter.origin == "still_retrying")
        ).all()

    fake = MagicMock()
    fake.actor_name = "still_retrying"
    fake.message_id = "msg-002"
    fake.queue_name = "test"
    fake.args = ()
    fake.kwargs = {}
    fake.options = {"retries": 1, "max_retries": 3}

    middleware.after_process_message(
        broker=MagicMock(), message=fake, exception=RuntimeError("transient")
    )

    with sm() as session:
        after = session.execute(
            select(DeadLetter).where(DeadLetter.origin == "still_retrying")
        ).all()
    assert len(after) == len(before)


def test_dlq_skipped_on_success() -> None:
    """exception=None → 정상 종료 — DLQ 무시."""
    from app.workers import DeadLetterMiddleware

    middleware = DeadLetterMiddleware()
    fake = MagicMock()
    fake.actor_name = "success_actor"
    middleware.after_process_message(broker=MagicMock(), message=fake, exception=None)
    # 예외 없이 통과하면 OK.
