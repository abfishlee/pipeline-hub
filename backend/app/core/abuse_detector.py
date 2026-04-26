"""Abuse detection (Phase 4.2.6) — Redis 기반 sliding window 카운터로 정책 위반 감지.

정책:
  - IP_MULTI_KEY  — 동일 IP 가 분당 N(=5) 개 이상 *서로 다른* api_key 사용.
  - KEY_HIGH_4XX  — 동일 api_key 가 분당 M(=200) 개 이상 4xx 응답 받음.

위반 시 audit.security_event INSERT + outbox NOTIFY (notify_worker → Slack). 동일
정책의 중복 알람을 막기 위해 Redis 에 *분당 알람 표시* (`fired:<kind>:<entity>:<minute>`)
를 1번만 적재.

Redis 미가동 시 fail-open — 절대 응답 latency 영향 X. Sentry 가 별도로 Redis 가용성
모니터링.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

IP_MULTI_KEY_THRESHOLD = 5      # 분당 IP 가 사용한 distinct key 수
KEY_HIGH_4XX_THRESHOLD = 200    # 분당 키 별 4xx 응답 수

_redis_client: aioredis.Redis | None = None
_KEY_PREFIX = "dp:abuse"


def _get_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url, decode_responses=True
        )
    return _redis_client


def _bucket_minute(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%d%H%M")


async def _already_fired(kind: str, entity: str) -> bool:
    """분당 1번만 알람 발사 — Redis SETNX 패턴."""
    key = f"{_KEY_PREFIX}:fired:{kind}:{entity}:{_bucket_minute()}"
    try:
        # SET NX EX 60 — 첫 호출 만 True.
        client = _get_client()
        result = await client.set(key, "1", nx=True, ex=60)
        return not bool(result)  # True 가 set 성공 (= 처음) → False 가 already_fired.
    except Exception:
        return True  # Redis 실패 시 알람 skip — fail-safe.


async def track_ip_key_use(*, ip: str | None, api_key_id: int) -> int | None:
    """IP 의 분당 distinct key 수 누적 → 임계 초과면 distinct count 반환, 아니면 None."""
    if ip is None:
        return None
    set_key = f"{_KEY_PREFIX}:ipkeys:{ip}:{_bucket_minute()}"
    try:
        client = _get_client()
        await client.sadd(set_key, str(api_key_id))  # type: ignore[misc]
        await client.expire(set_key, 60)
        count_raw: Any = await client.scard(set_key)  # type: ignore[misc]
        count = int(count_raw)
    except Exception:
        return None
    if count > IP_MULTI_KEY_THRESHOLD:
        return count
    return None


async def track_4xx(*, api_key_id: int, status_code: int) -> int | None:
    """api_key 의 분당 4xx 누적 → 임계 초과면 count 반환."""
    if status_code < 400 or status_code >= 500:
        return None
    counter_key = f"{_KEY_PREFIX}:4xx:{api_key_id}:{_bucket_minute()}"
    try:
        client = _get_client()
        used_raw: Any = await client.incr(counter_key)
        used = int(used_raw)
        if used == 1:
            await client.expire(counter_key, 60)
    except Exception:
        return None
    if used > KEY_HIGH_4XX_THRESHOLD:
        return used
    return None


async def record_event(
    *,
    kind: str,
    severity: str,
    ip: str | None,
    api_key_id: int | None,
    user_agent: str | None,
    details: dict[str, Any],
) -> None:
    """audit.security_event INSERT + outbox NOTIFY 발행 (sync session)."""
    import asyncio

    from sqlalchemy import text

    from app.db.sync_session import get_sync_sessionmaker

    safe_ip = _coerce_inet(ip)

    def _do() -> None:
        sm = get_sync_sessionmaker()
        with sm() as session:
            session.execute(
                text(
                    "INSERT INTO audit.security_event "
                    "(kind, severity, api_key_id, ip_addr, user_agent, details_json) "
                    "VALUES (:k, :sv, :akid, CAST(:ip AS INET), :ua, "
                    "        CAST(:dj AS JSONB))"
                ),
                {
                    "k": kind,
                    "sv": severity,
                    "akid": api_key_id,
                    "ip": safe_ip,
                    "ua": (user_agent or "")[:500] or None,
                    "dj": json.dumps(details, default=str),
                },
            )
            # outbox NOTIFY — notify_worker 가 Slack 발송.
            session.execute(
                text(
                    "INSERT INTO run.event_outbox "
                    "(aggregate_type, aggregate_id, event_type, payload_json) "
                    "VALUES ('security_event', 'abuse', 'notify.requested', "
                    "        CAST(:p AS JSONB))"
                ),
                {
                    "p": json.dumps(
                        {
                            "channel": "slack",
                            "target": "",
                            "level": severity,
                            "subject": f"보안 이벤트 — {kind}",
                            "body": (
                                f"kind={kind} severity={severity} ip={safe_ip} "
                                f"api_key_id={api_key_id} details={details}"
                            ),
                            "kind": kind,
                            "severity": severity,
                            "api_key_id": api_key_id,
                            "ip_addr": safe_ip,
                            "details": details,
                        },
                        default=str,
                    ),
                },
            )
            session.commit()

    try:
        await asyncio.to_thread(_do)
    except Exception:
        logger.exception("security_event.insert_failed")
    else:
        from app.core import metrics

        metrics.security_events_total.labels(kind=kind, severity=severity).inc()


def _coerce_inet(value: str | None) -> str | None:
    if not value:
        return None
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


async def evaluate_request(
    *,
    api_key_id: int,
    status_code: int,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """1 요청 종료 시 호출. 두 정책 모두 평가 + 위반 시 알람.

    중복 알람 방지: 동일 (kind, entity) 이 분당 1번만.
    """
    # 1) IP_MULTI_KEY — api_key_id 는 NULL (정책이 IP 단위라 단일 key 소속 무관).
    multi = await track_ip_key_use(ip=ip, api_key_id=api_key_id)
    if multi is not None and not await _already_fired("IP_MULTI_KEY", ip or "unknown"):
        await record_event(
            kind="IP_MULTI_KEY",
            severity="WARN",
            ip=ip,
            api_key_id=None,
            user_agent=user_agent,
            details={
                "distinct_keys_per_minute": multi,
                "threshold": IP_MULTI_KEY_THRESHOLD,
                "last_api_key_id": api_key_id,
            },
        )

    # 2) KEY_HIGH_4XX
    high4xx = await track_4xx(api_key_id=api_key_id, status_code=status_code)
    if high4xx is not None and not await _already_fired("KEY_HIGH_4XX", str(api_key_id)):
        await record_event(
            kind="KEY_HIGH_4XX",
            severity="WARN",
            ip=ip,
            api_key_id=api_key_id,
            user_agent=user_agent,
            details={"4xx_per_minute": high4xx, "threshold": KEY_HIGH_4XX_THRESHOLD},
        )


async def reset_for_test() -> None:
    """테스트 헬퍼 — 모든 dp:abuse:* 키 삭제."""
    import contextlib

    with contextlib.suppress(Exception):
        client = _get_client()
        async for k in client.scan_iter(match=f"{_KEY_PREFIX}:*"):
            await client.delete(k)


__all__ = [
    "IP_MULTI_KEY_THRESHOLD",
    "KEY_HIGH_4XX_THRESHOLD",
    "evaluate_request",
    "record_event",
    "reset_for_test",
    "track_4xx",
    "track_ip_key_use",
]
