"""자체 구현 Circuit Breaker (Phase 5.2.1.1, Q4 답변).

상태:
  CLOSED  → 정상. 모든 요청 통과.
  OPEN    → 차단. 모든 요청 즉시 실패 → fallback provider 자동 시도.
  HALF_OPEN → 1건 probe. 성공 → CLOSED, 실패 → OPEN 복귀.

기본 정책 (Q5 답변):
  max_retries        = 2
  retry_backoff_ms   = exponential 1000 → 3000
  open_after         = 연속 5xx/timeout 5건
  open_seconds       = 60
  half_open_probe    = 1건
  retry_after_max_s  = 300

저장:
  - Redis: 빠른 *현재 상태* (`dp:provider:cb:{provider_code}:{source_id}` →
    `state|failure_count|opened_at|...`).
  - DB: 이력 (provider_health 테이블) — 운영 화면 + 감사.

Redis 미가동 시 *fail-open* — circuit breaker 가 *허용* 쪽으로 동작 (= v1 path 와
동일하게 fallback). Redis 가용성 SLA 가 본 보호 메커니즘의 전제.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(slots=True, frozen=True)
class FailoverPolicy:
    """provider 호출의 retry / circuit / retry-after 정책 (Q5 답변)."""

    max_retries: int = 2
    retry_backoff_ms_first: int = 1000
    retry_backoff_ms_factor: float = 3.0
    open_after_failures: int = 5
    open_seconds: int = 60
    half_open_probe: int = 1
    retry_after_max_seconds: int = 300


DEFAULT_POLICY = FailoverPolicy()


@dataclass(slots=True)
class CircuitSnapshot:
    state: CircuitState
    failure_count: int
    opened_at_epoch: float | None
    last_error: str | None


_redis_client: aioredis.Redis | None = None
_KEY_PREFIX = "dp:provider:cb"


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url, decode_responses=True
        )
    return _redis_client


def _key(provider_code: str, source_id: int | None) -> str:
    sid = str(source_id) if source_id is not None else "global"
    return f"{_KEY_PREFIX}:{provider_code}:{sid}"


@dataclass(slots=True)
class CircuitBreaker:
    """1 (provider, source) 쌍의 circuit breaker."""

    provider_code: str
    source_id: int | None = None
    policy: FailoverPolicy = field(default_factory=lambda: DEFAULT_POLICY)

    # ------------------------------------------------------------------
    # state IO
    # ------------------------------------------------------------------
    async def get_state(self) -> CircuitSnapshot:
        try:
            client = _get_redis()
            raw = await client.get(_key(self.provider_code, self.source_id))
        except Exception:
            return CircuitSnapshot(CircuitState.CLOSED, 0, None, None)
        if raw is None:
            return CircuitSnapshot(CircuitState.CLOSED, 0, None, None)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return CircuitSnapshot(CircuitState.CLOSED, 0, None, None)
        return CircuitSnapshot(
            state=CircuitState(data.get("state", "CLOSED")),
            failure_count=int(data.get("failure_count", 0)),
            opened_at_epoch=data.get("opened_at"),
            last_error=data.get("last_error"),
        )

    async def _save(self, snap: CircuitSnapshot, *, ttl_sec: int | None = None) -> None:
        try:
            client = _get_redis()
            value = json.dumps(
                {
                    "state": snap.state.value,
                    "failure_count": snap.failure_count,
                    "opened_at": snap.opened_at_epoch,
                    "last_error": snap.last_error,
                }
            )
            if ttl_sec is not None and ttl_sec > 0:
                await client.setex(_key(self.provider_code, self.source_id), ttl_sec, value)
            else:
                await client.set(_key(self.provider_code, self.source_id), value)
        except Exception:
            return

    async def reset(self) -> None:
        with contextlib.suppress(Exception):
            client = _get_redis()
            await client.delete(_key(self.provider_code, self.source_id))

    # ------------------------------------------------------------------
    # decision API
    # ------------------------------------------------------------------
    async def can_execute(self) -> tuple[bool, CircuitSnapshot]:
        """현재 상태에 따라 호출 가능 여부 + snapshot 반환.

        OPEN 이면 retry-after 만료 확인 → HALF_OPEN 으로 전이 후 1건 probe 허용.
        """
        snap = await self.get_state()
        if snap.state == CircuitState.CLOSED:
            return True, snap
        if snap.state == CircuitState.HALF_OPEN:
            # HALF_OPEN 은 *1건만* 허용 — Redis SET NX 가 직렬화 책임. 단순화: 첫 호출만 허용.
            return True, snap
        # OPEN — retry-after 만료 시 HALF_OPEN.
        if snap.opened_at_epoch is None:
            return False, snap
        elapsed = time.time() - snap.opened_at_epoch
        if elapsed >= self.policy.open_seconds:
            new_snap = CircuitSnapshot(
                state=CircuitState.HALF_OPEN,
                failure_count=snap.failure_count,
                opened_at_epoch=snap.opened_at_epoch,
                last_error=snap.last_error,
            )
            await self._save(new_snap, ttl_sec=self.policy.open_seconds * 2)
            return True, new_snap
        return False, snap

    async def record_success(self) -> CircuitSnapshot:
        snap = CircuitSnapshot(CircuitState.CLOSED, 0, None, None)
        await self._save(snap)
        return snap

    async def record_failure(self, *, error: str) -> CircuitSnapshot:
        cur = await self.get_state()
        new_count = cur.failure_count + 1
        if new_count >= self.policy.open_after_failures:
            new_snap = CircuitSnapshot(
                state=CircuitState.OPEN,
                failure_count=new_count,
                opened_at_epoch=time.time(),
                last_error=error[:1000],
            )
            await self._save(new_snap, ttl_sec=self.policy.open_seconds * 2)
            return new_snap
        new_snap = CircuitSnapshot(
            state=CircuitState.CLOSED,
            failure_count=new_count,
            opened_at_epoch=cur.opened_at_epoch,
            last_error=error[:1000],
        )
        await self._save(new_snap)
        return new_snap

    # ------------------------------------------------------------------
    # retry helpers
    # ------------------------------------------------------------------
    def compute_backoff_ms(self, attempt: int) -> int:
        if attempt <= 1:
            return self.policy.retry_backoff_ms_first
        # exponential.
        return int(
            self.policy.retry_backoff_ms_first
            * (self.policy.retry_backoff_ms_factor ** (attempt - 1))
        )

    def cap_retry_after(self, retry_after_seconds: int) -> int:
        return max(0, min(retry_after_seconds, self.policy.retry_after_max_seconds))


def is_retryable_status(status_code: int) -> bool:
    """Q5 답변 분류:
      4xx (400/401/403/404) — retry 안 함 (설정/요청 문제)
      408/429 — retry-after 존중 + retry 가능
      5xx / timeout / network — retry 가능
    """
    if status_code in (408, 429):
        return True
    return 500 <= status_code < 600


def is_failure_status(status_code: int) -> bool:
    """circuit breaker 의 *실패* 카운트 기준:
      5xx + 408 + 429 만 OPEN 으로 진행 (4xx 다른 코드는 *호출자* 문제이므로 제외).
    """
    if status_code in (408, 429):
        return True
    return 500 <= status_code < 600


__all__ = [
    "DEFAULT_POLICY",
    "CircuitBreaker",
    "CircuitSnapshot",
    "CircuitState",
    "FailoverPolicy",
    "is_failure_status",
    "is_retryable_status",
]
