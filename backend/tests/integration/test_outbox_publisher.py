"""실 PG + 실 Redis 통합 테스트 — outbox publisher 도메인.

`docker compose` 가 기동되어 있어야 함. 미가동 시 skip.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import redis as redis_lib
from sqlalchemy import delete, select

from app.config import get_settings
from app.core.events import RedisStreamPublisher
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.outbox import publish_pending_events
from app.models.run import EventOutbox


@pytest.fixture(scope="module")
def _redis_or_skip() -> Iterator[redis_lib.Redis]:
    """Redis ping. 실패 시 module 전체 skip."""
    settings = get_settings()
    client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:
        pytest.skip(f"redis unreachable: {exc}")
    yield client
    client.close()


@pytest.fixture
def isolated_stream(_redis_or_skip: redis_lib.Redis) -> Iterator[tuple[str, str]]:
    """테스트 격리용 stream key. 시작/종료 시 DEL.

    `RedisStreamPublisher` 의 prefix override 를 위해 (prefix, aggregate_type) 반환.
    """
    prefix = "it_outbox_test"
    aggregate_type = "raw_object"
    key = f"{prefix}:{aggregate_type}"
    _redis_or_skip.delete(key)
    yield prefix, aggregate_type
    _redis_or_skip.delete(key)


@pytest.fixture
def cleanup_event_outbox() -> Iterator[list[int]]:
    """삽입한 event_id 를 sweep."""
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(EventOutbox).where(EventOutbox.event_id.in_(ids)))
        session.commit()
    dispose_sync_engine()


def _seed_pending(session: object, ids_out: list[int], n: int) -> list[int]:
    """seed N 개의 PENDING 이벤트. 반환 = event_id 리스트."""
    inserted: list[int] = []
    assert hasattr(session, "execute")
    for i in range(n):
        row = EventOutbox(
            aggregate_type="raw_object",
            aggregate_id=f"{1000 + i}:2026-04-25",
            event_type="raw_object.created",
            payload_json={"raw_object_id": 1000 + i, "size": 42 + i},
        )
        session.add(row)  # type: ignore[attr-defined]
    session.commit()  # type: ignore[attr-defined]

    rows = (
        session.execute(  # type: ignore[attr-defined]
            select(EventOutbox)
            .where(EventOutbox.aggregate_id.in_([f"{1000 + i}:2026-04-25" for i in range(n)]))
            .order_by(EventOutbox.event_id)
        )
        .scalars()
        .all()
    )
    for r in rows:
        inserted.append(r.event_id)
        ids_out.append(r.event_id)
    return inserted


def test_publish_pending_drains_to_redis_and_marks_published(
    isolated_stream: tuple[str, str],
    _redis_or_skip: redis_lib.Redis,
    cleanup_event_outbox: list[int],
) -> None:
    prefix, aggregate_type = isolated_stream
    sm = get_sync_sessionmaker()
    with sm() as session:
        seeded_ids = _seed_pending(session, cleanup_event_outbox, n=3)

        publisher = RedisStreamPublisher(_redis_or_skip, prefix=prefix)
        stats = publish_pending_events(session, publisher, batch_size=100, max_attempts=5)

        assert stats.selected == 3
        assert stats.published == 3
        assert stats.failed == 0

        marked = session.execute(
            select(EventOutbox.status, EventOutbox.published_at)
            .where(EventOutbox.event_id.in_(seeded_ids))
            .order_by(EventOutbox.event_id)
        ).all()
        assert all(row.status == "PUBLISHED" for row in marked)
        assert all(row.published_at is not None for row in marked)

    stream_key = f"{prefix}:{aggregate_type}"
    assert _redis_or_skip.xlen(stream_key) == 3
    entries = _redis_or_skip.xrange(stream_key)
    decoded = [e[1] for e in entries]
    assert all("event_id" in fields for fields in decoded)
    assert all(fields["aggregate_type"] == "raw_object" for fields in decoded)


def test_publish_failure_increments_attempt_and_promotes_to_failed(
    cleanup_event_outbox: list[int],
) -> None:
    """publisher.xadd 가 raise 하도록 stub — attempt_no 증가, max 도달 시 FAILED."""
    sm = get_sync_sessionmaker()

    class _BoomPublisher:
        def xadd(self, *_a: object, **_kw: object) -> str:
            raise RuntimeError("redis-blackhole")

    with sm() as session:
        seeded = _seed_pending(session, cleanup_event_outbox, n=1)
        eid = seeded[0]

        # max_attempts=2 → 첫 실패는 PENDING(attempt=1), 두 번째 실패는 FAILED(attempt=2).
        for expected_status, expected_attempt in [("PENDING", 1), ("FAILED", 2)]:
            stats = publish_pending_events(
                session,
                _BoomPublisher(),
                batch_size=10,
                max_attempts=2,  # type: ignore[arg-type]
            )
            assert stats.selected == 1
            assert stats.published == 0
            assert stats.failed == 1
            row = session.execute(
                select(EventOutbox).where(EventOutbox.event_id == eid)
            ).scalar_one()
            assert row.status == expected_status, f"after attempt {expected_attempt}"
            assert row.attempt_no == expected_attempt
            assert row.last_error is not None and "redis-blackhole" in row.last_error
