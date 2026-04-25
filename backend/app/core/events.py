"""Redis Streams 발행 클라이언트 (Phase 2.2.1).

원칙:
  - **하나의 Redis 인스턴스**가 dramatiq 브로커와 이벤트 스트림을 같이 사용한다.
    URL 은 Settings.redis_url 단일 출처. 토픽/큐 prefix 로 namespace 분리.
  - **API 경로는 async, worker 도메인 함수는 sync** 둘 다 호출한다.
    redis-py 5.x 의 동기 클라이언트는 짧은 RTT 짧은 작업이라 `asyncio.to_thread`
    로 감싸도 비용 미미. (dramatiq 도 동일한 sync 클라이언트를 씀.)
  - **At-least-once.** XADD 후 DB 마킹이 실패하면 재시도 시 중복 XADD 가 발생할
    수 있다. 이는 outbox 패턴 + idempotent consumer 로 다운스트림에서 흡수.
  - 토픽 키는 `<settings.redis_streams_prefix>:<aggregate_type>` (예: `dp:events:raw_object`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Mapping
from typing import Any

import redis

from app.config import Settings, get_settings


class RedisStreamPublisher:
    """Redis Streams XADD 래퍼 — sync/async 양쪽 호출 가능."""

    def __init__(self, client: redis.Redis, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RedisStreamPublisher:
        s = settings or get_settings()
        return cls(
            redis.Redis.from_url(s.redis_url, decode_responses=True),
            s.redis_streams_prefix,
        )

    def stream_key(self, aggregate_type: str) -> str:
        return f"{self._prefix}:{aggregate_type}"

    def xadd(self, aggregate_type: str, fields: Mapping[str, Any]) -> str:
        """동기 XADD. fields 의 dict/list 값은 JSON 직렬화."""
        # redis-py 의 xadd 는 invariant dict 를 기대 — Any 로 두고 런타임 타입은 우리가 보장.
        flat: dict[Any, Any] = {}
        for k, v in fields.items():
            flat[k] = (
                v
                if isinstance(v, str)
                else json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)
            )
        return str(self._client.xadd(self.stream_key(aggregate_type), flat))

    async def axadd(self, aggregate_type: str, fields: Mapping[str, Any]) -> str:
        """async wrapper — sync 클라이언트를 thread pool 로 감쌈."""
        return await asyncio.to_thread(self.xadd, aggregate_type, fields)

    def close(self) -> None:
        # 이미 닫힌 경우 등 — 운영 코드에서는 무시.
        with contextlib.suppress(Exception):
            self._client.close()


__all__ = ["RedisStreamPublisher"]
