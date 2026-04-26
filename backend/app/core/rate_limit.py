"""Redis 기반 분당 fixed-window rate limit (Phase 4.2.5).

설계:
  - key 별로 `<prefix>:rl:<api_key_id>:<minute_bucket>` INCR.
  - 첫 INCR 시 EXPIRE 60s — 자연 만료.
  - 결과가 limit 초과면 429.
  - slowapi/aioredis 같은 추가 의존성 없이 기존 redis-py 만 사용.

리미트가 0 또는 음수면 *제한 없음* (테스트/내부 호출용).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

_KEY_PREFIX = "dp:public_api:rl"


@dataclass(slots=True, frozen=True)
class RateLimitResult:
    allowed: bool
    used: int
    limit: int
    reset_seconds: int  # 다음 bucket 까지 남은 초.


def _bucket_minute(now: datetime | None = None) -> str:
    n = now or datetime.now(UTC)
    return n.strftime("%Y%m%d%H%M")


_redis_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url, decode_responses=True
        )
    return _redis_client


async def check_rate_limit(*, api_key_id: int, limit: int) -> RateLimitResult:
    """현재 분의 호출 카운트를 +1 하고 limit 비교.

    `limit <= 0` 이면 제한 없음 (used=0, allowed=True 반환).
    Redis 미가동 시 fail-open (allowed=True) — 테스트/오프라인 운영 대응.
    """
    if limit <= 0:
        return RateLimitResult(allowed=True, used=0, limit=limit, reset_seconds=0)
    bucket = _bucket_minute()
    key = f"{_KEY_PREFIX}:{api_key_id}:{bucket}"
    try:
        client = _get_client()
        used = int(await client.incr(key))
        if used == 1:
            await client.expire(key, 60)
        ttl_raw: Any = await client.ttl(key)
        ttl = int(ttl_raw) if ttl_raw is not None else 60
    except Exception:
        return RateLimitResult(allowed=True, used=0, limit=limit, reset_seconds=60)
    return RateLimitResult(
        allowed=used <= limit,
        used=used,
        limit=limit,
        reset_seconds=max(ttl, 0),
    )


async def reset_rate_limit_for_test(api_key_id: int) -> None:
    """테스트 헬퍼 — 현재 분의 카운터 삭제."""
    import contextlib

    bucket = _bucket_minute()
    with contextlib.suppress(Exception):
        await _get_client().delete(f"{_KEY_PREFIX}:{api_key_id}:{bucket}")


__all__ = [
    "RateLimitResult",
    "check_rate_limit",
    "reset_rate_limit_for_test",
]
