"""Phase 4.2.6 — abuse_detector 통합 테스트.

검증:
  1. IP_MULTI_KEY — 동일 IP 가 분당 5+ distinct key 사용 → security_event 1건.
  2. KEY_HIGH_4XX — 동일 key 가 분당 200+ 4xx 받음 → security_event 1건.
  3. 정상 트래픽은 적재 안 함 (false positive 방지).
  4. 분당 알람 1번만 발사 (Redis SETNX 패턴).

실 PG/Redis 의존. Redis 미가동 시 fail-open 으로 함수가 None 반환 → 일부 케이스 skip.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, select, text

from app.core import abuse_detector
from app.core.security import hash_password
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.audit import SecurityEvent
from app.models.ctl import ApiKey
from app.models.run import EventOutbox

REDIS_SKIP = "redis unavailable — abuse_detector fail-open path"


@pytest.fixture
def seed_api_key() -> Iterator[int]:
    """1개 api_key seed → cleanup. KEY_HIGH_4XX 등 FK 검증용."""
    sm = get_sync_sessionmaker()
    suffix = secrets.token_hex(4).lower()
    api_key_id: int
    with sm() as session:
        api_key_id = session.execute(
            text(
                "INSERT INTO ctl.api_key "
                "(key_prefix, key_hash, client_name, scope, retailer_allowlist) "
                "VALUES (:p, :h, 'IT abuse-detector', '{products.read}', '{}'::bigint[]) "
                "RETURNING api_key_id"
            ),
            {"p": f"itab{suffix}", "h": hash_password(secrets.token_urlsafe(8))},
        ).scalar_one()
        session.commit()
    yield int(api_key_id)
    with sm() as session:
        session.execute(
            text("DELETE FROM audit.security_event WHERE api_key_id = :id"),
            {"id": api_key_id},
        )
        session.execute(
            text("DELETE FROM ctl.api_key WHERE api_key_id = :id"),
            {"id": api_key_id},
        )
        session.commit()


@pytest.fixture
def cleanup_security_events() -> Iterator[None]:
    yield
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(SecurityEvent))
        session.execute(
            delete(EventOutbox).where(EventOutbox.aggregate_type == "security_event")
        )
        session.commit()
    dispose_sync_engine()


async def _ping_or_skip() -> None:
    """현재 event loop 에서 새 client 생성 + ping. 실패 시 pytest.skip 신호."""
    abuse_detector._redis_client = None
    client = abuse_detector._get_client()
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        raise pytest.skip.Exception(f"{REDIS_SKIP}: {exc}", allow_module_level=False)


# ---------------------------------------------------------------------------
# 1. IP_MULTI_KEY
# ---------------------------------------------------------------------------
def test_ip_multi_key_fires_security_event(
    cleanup_security_events: None,
) -> None:
    ip = "10.99.99.1"

    async def _drive() -> None:
        await _ping_or_skip()
        await abuse_detector.reset_for_test()
        for k in range(1001, 1007):
            await abuse_detector.evaluate_request(
                api_key_id=k,
                status_code=200,
                ip=ip,
                user_agent="test/1.0",
            )

    asyncio.run(_drive())

    sm = get_sync_sessionmaker()
    with sm() as session:
        events = session.execute(
            select(SecurityEvent).where(SecurityEvent.kind == "IP_MULTI_KEY")
        ).scalars().all()
        assert len(events) >= 1
        assert str(events[-1].ip_addr) == ip
        assert events[-1].details_json.get("threshold") == 5

        notif = session.execute(
            select(EventOutbox)
            .where(EventOutbox.aggregate_type == "security_event")
            .where(EventOutbox.event_type == "notify.requested")
        ).scalars().all()
        assert len(notif) >= 1


# ---------------------------------------------------------------------------
# 2. KEY_HIGH_4XX
# ---------------------------------------------------------------------------
def test_key_high_4xx_fires_security_event(
    cleanup_security_events: None,
    seed_api_key: int,
) -> None:
    async def _drive() -> None:
        await _ping_or_skip()
        await abuse_detector.reset_for_test()
        # KEY_HIGH_4XX_THRESHOLD = 200 — 201번째에 임계 초과.
        for _ in range(201):
            await abuse_detector.evaluate_request(
                api_key_id=seed_api_key,
                status_code=403,
                ip="10.99.99.2",
                user_agent="test/1.0",
            )

    asyncio.run(_drive())

    sm = get_sync_sessionmaker()
    with sm() as session:
        events = session.execute(
            select(SecurityEvent).where(SecurityEvent.kind == "KEY_HIGH_4XX")
        ).scalars().all()
        assert len(events) >= 1
        assert events[-1].api_key_id == seed_api_key


# ---------------------------------------------------------------------------
# 3. 정상 트래픽은 적재 안 함 — false positive 방지
# ---------------------------------------------------------------------------
def test_normal_traffic_does_not_fire(cleanup_security_events: None) -> None:
    async def _drive() -> None:
        await _ping_or_skip()
        await abuse_detector.reset_for_test()
        for _ in range(20):
            await abuse_detector.evaluate_request(
                api_key_id=42,
                status_code=200,
                ip="10.99.99.3",
                user_agent="test/1.0",
            )

    asyncio.run(_drive())

    sm = get_sync_sessionmaker()
    with sm() as session:
        events = session.execute(
            select(SecurityEvent).where(SecurityEvent.ip_addr == "10.99.99.3")
        ).scalars().all()
        assert events == []


# ---------------------------------------------------------------------------
# 4. 분당 1번만 발사 — 중복 알람 방지
# ---------------------------------------------------------------------------
def test_duplicate_alert_suppressed_within_minute(
    cleanup_security_events: None,
) -> None:
    ip = "10.99.99.4"

    async def _drive() -> None:
        await _ping_or_skip()
        await abuse_detector.reset_for_test()
        # 1차: 6 distinct keys → 1건 발사.
        for k in range(2001, 2007):
            await abuse_detector.evaluate_request(
                api_key_id=k, status_code=200, ip=ip, user_agent="t"
            )
        # 2차: 같은 IP 에 또 6 distinct keys → 같은 분이라 추가 발사 없어야.
        for k in range(2007, 2013):
            await abuse_detector.evaluate_request(
                api_key_id=k, status_code=200, ip=ip, user_agent="t"
            )

    asyncio.run(_drive())

    sm = get_sync_sessionmaker()
    with sm() as session:
        events = session.execute(
            select(SecurityEvent)
            .where(SecurityEvent.kind == "IP_MULTI_KEY")
            .where(SecurityEvent.ip_addr == ip)
        ).scalars().all()
        # 분당 1건만 — 중복 알람 발사되지 않음.
        assert len(events) == 1
