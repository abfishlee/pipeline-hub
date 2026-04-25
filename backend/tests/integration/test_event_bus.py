"""실 PG + 실 Redis 통합 테스트 — Streams 그룹 + idempotent consumer + XCLAIM.

`docker compose` 가 기동되어 있어야 함. 미가동 시 skip.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
import redis as redis_lib
from sqlalchemy import delete, select

from app.config import get_settings
from app.core.event_topics import (
    EventTopic,
    RawObjectCreatedPayload,
    parse_message,
)
from app.core.events import (
    RedisStreamConsumer,
    RedisStreamPublisher,
    consumer_group_name,
)
from app.db.sync_session import get_sync_sessionmaker
from app.domain.idempotent_consume import (
    ConsumeResult,
    consume_idempotent,
    reset_processed_marker,
)
from app.models.run import ProcessedEvent


@pytest.fixture(scope="module")
def _redis_or_skip() -> Iterator[redis_lib.Redis]:
    settings = get_settings()
    client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:
        pytest.skip(f"redis unreachable: {exc}")
    yield client
    client.close()


@pytest.fixture
def isolated_topic(_redis_or_skip: redis_lib.Redis) -> Iterator[tuple[str, str]]:
    """테스트별 격리 prefix + topic. 시작/종료 시 stream 통째로 DEL."""
    prefix = f"it_evbus_{int(time.time() * 1000) % 1_000_000}"
    topic = EventTopic.RAW_OBJECT.value
    key = f"{prefix}:{topic}"
    _redis_or_skip.delete(key)
    yield prefix, topic
    _redis_or_skip.delete(key)


@pytest.fixture
def cleanup_processed_events() -> Iterator[list[tuple[str, str]]]:
    """삽입한 (event_id, consumer_name) sweep."""
    keys: list[tuple[str, str]] = []
    yield keys
    if not keys:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for eid, cn in keys:
            session.execute(
                delete(ProcessedEvent)
                .where(ProcessedEvent.event_id == eid)
                .where(ProcessedEvent.consumer_name == cn)
            )
        session.commit()


def _publish_one(publisher: RedisStreamPublisher, *, event_id: str, raw_id: int) -> None:
    publisher.xadd(
        EventTopic.RAW_OBJECT.value,
        {
            "event_id": event_id,
            "aggregate_type": "raw_object",
            "aggregate_id": f"{raw_id}:2026-04-25",
            "event_type": "raw_object.created",
            "occurred_at": "2026-04-25T01:23:45+00:00",
            "payload": {
                "raw_object_id": raw_id,
                "partition_date": "2026-04-25",
                "source_id": 1,
                "content_hash": "deadbeef",
                "object_uri": None,
                "bytes_size": 42,
            },
        },
    )


# ---------------------------------------------------------------------------
# 1. ensure_group + read + idempotent_consume + ack
# ---------------------------------------------------------------------------
def test_idempotent_consume_skips_on_redelivery(
    _redis_or_skip: redis_lib.Redis,
    isolated_topic: tuple[str, str],
    cleanup_processed_events: list[tuple[str, str]],
) -> None:
    prefix, topic = isolated_topic
    publisher = RedisStreamPublisher(_redis_or_skip, prefix=prefix)
    consumer = RedisStreamConsumer(
        _redis_or_skip,
        stream_key=publisher.stream_key(topic),
        group=consumer_group_name("ocr", "test"),
        consumer_id="worker-A",
    )
    consumer.ensure_group(start_id="0")

    event_id = "ev-it-001"
    cleanup_processed_events.append((event_id, "ocr-test"))
    _publish_one(publisher, event_id=event_id, raw_id=4242)

    msgs = consumer.read(count=10, block_ms=500)
    assert len(msgs) == 1
    entry_id, fields = msgs[0]
    env = parse_message(fields)
    assert env.event_type == "raw_object.created"
    assert env.event_id == event_id
    payload = RawObjectCreatedPayload.model_validate(env.payload)
    assert payload.raw_object_id == 4242

    sm = get_sync_sessionmaker()
    seen: list[str] = []

    def _handler(_session: object) -> str:
        seen.append(env.event_id)
        return "ok"

    with sm() as session:
        first: ConsumeResult[str] = consume_idempotent(
            session,
            event_id=env.event_id,
            consumer_name="ocr-test",
            handler=_handler,  # type: ignore[arg-type]
        )
    assert first.processed is True
    assert first.value == "ok"
    assert seen == [event_id]
    consumer.ack(entry_id)

    # 같은 event_id 재배달 시뮬레이션 — handler 호출 안 됨.
    seen.clear()
    with sm() as session:
        second = consume_idempotent(
            session,
            event_id=env.event_id,
            consumer_name="ocr-test",
            handler=_handler,  # type: ignore[arg-type]
        )
    assert second.processed is False
    assert second.value is None
    assert seen == []  # handler 미호출 검증.

    # DB 상태 — 정확히 1행.
    with sm() as session:
        rows = (
            session.execute(
                select(ProcessedEvent)
                .where(ProcessedEvent.event_id == event_id)
                .where(ProcessedEvent.consumer_name == "ocr-test")
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


def test_two_consumers_same_event_distinct_markers(
    _redis_or_skip: redis_lib.Redis,
    isolated_topic: tuple[str, str],
    cleanup_processed_events: list[tuple[str, str]],
) -> None:
    """같은 event_id 를 다른 consumer_name 가 처리하면 별개 행 — 합성 PK 회귀."""
    prefix, topic = isolated_topic
    publisher = RedisStreamPublisher(_redis_or_skip, prefix=prefix)
    event_id = "ev-fanout-001"
    cleanup_processed_events.append((event_id, "ocr-test"))
    cleanup_processed_events.append((event_id, "transform-test"))
    _publish_one(publisher, event_id=event_id, raw_id=99)

    sm = get_sync_sessionmaker()
    counts = {"ocr": 0, "transform": 0}

    def make_handler(name: str):
        def _h(_s: object) -> None:
            counts[name] += 1

        return _h

    with sm() as session:
        r_ocr = consume_idempotent(
            session,
            event_id=event_id,
            consumer_name="ocr-test",
            handler=make_handler("ocr"),  # type: ignore[arg-type]
        )
    with sm() as session:
        r_xform = consume_idempotent(
            session,
            event_id=event_id,
            consumer_name="transform-test",
            handler=make_handler("transform"),  # type: ignore[arg-type]
        )

    assert r_ocr.processed is True and r_xform.processed is True
    assert counts == {"ocr": 1, "transform": 1}


# ---------------------------------------------------------------------------
# 2. XCLAIM — 죽은 consumer 메시지 인계
# ---------------------------------------------------------------------------
def test_claim_stale_transfers_pending_to_alive_consumer(
    _redis_or_skip: redis_lib.Redis,
    isolated_topic: tuple[str, str],
) -> None:
    prefix, topic = isolated_topic
    publisher = RedisStreamPublisher(_redis_or_skip, prefix=prefix)
    stream_key = publisher.stream_key(topic)
    group = consumer_group_name("ocr", "test")

    # consumer A 가 read 만 하고 ack 안 함 (죽은 시뮬레이션).
    a = RedisStreamConsumer(_redis_or_skip, stream_key=stream_key, group=group, consumer_id="A")
    a.ensure_group(start_id="0")

    _publish_one(publisher, event_id="ev-claim-1", raw_id=1)
    _publish_one(publisher, event_id="ev-claim-2", raw_id=2)

    msgs_a = a.read(count=10, block_ms=500)
    assert len(msgs_a) == 2  # A 가 둘 다 가져갔지만 ack 안 함.
    assert a.pending_count() == 2

    # min_idle 이 충분히 짧아야 즉시 인계 — 50ms 대기 후 30ms idle 임계로 claim.
    time.sleep(0.06)

    b = RedisStreamConsumer(_redis_or_skip, stream_key=stream_key, group=group, consumer_id="B")
    claimed = b.claim_stale(min_idle_ms=30, count=10)
    assert len(claimed) == 2
    claimed_event_ids = {parse_message(fields).event_id for _, fields in claimed}
    assert claimed_event_ids == {"ev-claim-1", "ev-claim-2"}

    # B 가 ack 하면 그룹 PEL 0.
    for entry_id, _ in claimed:
        b.ack(entry_id)
    assert b.pending_count() == 0


# ---------------------------------------------------------------------------
# 3. reset_processed_marker — 운영자 수동 replay
# ---------------------------------------------------------------------------
def test_reset_processed_marker_allows_reprocessing(
    cleanup_processed_events: list[tuple[str, str]],
) -> None:
    sm = get_sync_sessionmaker()
    event_id = "ev-replay-001"
    cleanup_processed_events.append((event_id, "ocr-test"))

    calls = {"n": 0}

    def _h(_s: object) -> None:
        calls["n"] += 1

    with sm() as session:
        first = consume_idempotent(
            session,
            event_id=event_id,
            consumer_name="ocr-test",
            handler=_h,  # type: ignore[arg-type]
        )
    assert first.processed is True
    assert calls["n"] == 1

    with sm() as session:
        deleted = reset_processed_marker(session, event_id=event_id, consumer_name="ocr-test")
        session.commit()
    assert deleted == 1

    with sm() as session:
        replayed = consume_idempotent(
            session,
            event_id=event_id,
            consumer_name="ocr-test",
            handler=_h,  # type: ignore[arg-type]
        )
    assert replayed.processed is True
    assert calls["n"] == 2  # 실제 재실행됨.
