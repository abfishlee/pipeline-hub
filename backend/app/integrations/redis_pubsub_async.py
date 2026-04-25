"""Redis Pub/Sub 비동기 클라이언트 (Phase 3.2.3 — SSE 전용).

기존 `app/core/events.py::RedisPubSub` 은 sync publish 에 최적화. SSE 라우터는
async 컨텍스트에서 채널 listen 이 필요해 `redis.asyncio` 기반 별도 모듈 도입.

API:
    async with AsyncRedisPubSub.from_settings() as ps:
        async for message in ps.subscribe("pipeline:42"):
            print(message)

`message` 는 string (publisher 가 JSON 직렬화한 값). 클라이언트 disconnect 시 컨
텍스트 매니저 종료가 채널 unsubscribe + 연결 해제를 담당.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from types import TracebackType

import redis.asyncio as redis_async

from app.config import Settings, get_settings


class AsyncRedisPubSub:
    """`redis.asyncio.Redis` 위에 얹은 얇은 wrapper.

    redis-py 의 PubSub 는 같은 connection 에서 여러 채널을 listen 할 수 있지만,
    SSE 1 endpoint 는 1 채널만 다루므로 본 wrapper 는 단순화: subscribe → listen
    → close.
    """

    def __init__(self, client: redis_async.Redis) -> None:
        self._client = client
        self._pubsub = client.pubsub()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> AsyncRedisPubSub:
        s = settings or get_settings()
        client = redis_async.from_url(s.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        return cls(client)

    async def __aenter__(self) -> AsyncRedisPubSub:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        """채널 구독 후 메시지 string 을 yield. caller 가 break 하면 unsubscribe."""
        await self._pubsub.subscribe(channel)
        try:
            async for message in self._pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    # subscribe / unsubscribe / pong 같은 control 메시지 무시.
                    continue
                data = message.get("data")
                if data is None:
                    continue
                if isinstance(data, bytes | bytearray):
                    yield data.decode("utf-8", errors="replace")
                else:
                    yield str(data)
        finally:
            with contextlib.suppress(Exception):
                await self._pubsub.unsubscribe(channel)

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):
            await self._pubsub.aclose()  # type: ignore[no-untyped-call]
        with contextlib.suppress(Exception):
            await self._client.aclose()


__all__ = ["AsyncRedisPubSub"]
