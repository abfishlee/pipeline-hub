"""Redis Streams 발행/소비 클라이언트 (Phase 2.2.1 발행 / 2.2.2 소비).

원칙:
  - **하나의 Redis 인스턴스**가 dramatiq 브로커와 이벤트 스트림을 같이 사용한다.
    URL 은 Settings.redis_url 단일 출처. 토픽/큐 prefix 로 namespace 분리.
  - **API 경로는 async, worker 도메인 함수는 sync** 둘 다 호출한다.
    redis-py 5.x 의 동기 클라이언트는 짧은 RTT 짧은 작업이라 `asyncio.to_thread`
    로 감싸도 비용 미미. (dramatiq 도 동일한 sync 클라이언트를 씀.)
  - **At-least-once.** XADD 후 DB 마킹이 실패하면 재시도 시 중복 XADD 가 발생할
    수 있다. 이는 outbox 패턴 + idempotent consumer 로 다운스트림에서 흡수.
  - 토픽 키는 `<settings.redis_streams_prefix>:<aggregate_type>` (예: `dp:events:raw_object`).
  - Consumer Group 이름은 `<worker_type>-<env>` (예: `outbox-local`, `ocr-prod`) —
    같은 stream 을 다중 worker_type 이 fan-out 으로 소비 가능.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Mapping
from typing import Any

import redis
from redis.exceptions import ResponseError

from app.config import Settings, get_settings


# ---------------------------------------------------------------------------
# 발행 (Publisher)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 소비 (Consumer Group)
# ---------------------------------------------------------------------------
def consumer_group_name(worker_type: str, env: str) -> str:
    """소비자 그룹 이름 규칙: `<worker_type>-<env>`.

    예: ("outbox", "local") → "outbox-local". 스트림 1개를 여러 worker_type 이
    fan-out 으로 받게 하려면 worker_type 별로 그룹을 만들면 된다.
    """
    if not worker_type or not env:
        raise ValueError("worker_type and env are required")
    return f"{worker_type}-{env}"


# 스트림 메시지 = (entry_id, fields_dict). redis-py 의 decode_responses=True 가정.
StreamMessage = tuple[str, dict[str, str]]


class RedisStreamConsumer:
    """Redis Streams Consumer Group 래퍼.

    한 인스턴스 = 한 그룹 + 한 스트림 + 한 consumer_id 조합. 동일 worker_type 의
    여러 인스턴스(스레드/프로세스)는 같은 group 을 공유, 다른 consumer_id 로 동작
    하면 redis 가 메시지를 자동 분산한다.
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        stream_key: str,
        group: str,
        consumer_id: str,
    ) -> None:
        self._client = client
        self._stream_key = stream_key
        self._group = group
        self._consumer_id = consumer_id

    @classmethod
    def from_settings(
        cls,
        *,
        aggregate_type: str,
        worker_type: str,
        consumer_id: str,
        settings: Settings | None = None,
    ) -> RedisStreamConsumer:
        s = settings or get_settings()
        client = redis.Redis.from_url(s.redis_url, decode_responses=True)
        stream_key = f"{s.redis_streams_prefix}:{aggregate_type}"
        group = consumer_group_name(worker_type, s.env)
        return cls(client, stream_key=stream_key, group=group, consumer_id=consumer_id)

    @property
    def stream_key(self) -> str:
        return self._stream_key

    @property
    def group(self) -> str:
        return self._group

    @property
    def consumer_id(self) -> str:
        return self._consumer_id

    def ensure_group(self, *, start_id: str = "0") -> None:
        """그룹이 없으면 MKSTREAM 으로 생성. 이미 있으면 BUSYGROUP 무시.

        start_id "0" = 처음부터, "$" = 그룹 생성 이후 들어오는 메시지부터.
        Outbox 같이 history 도 흘려야 하면 "0" (기본).
        """
        try:
            self._client.xgroup_create(self._stream_key, self._group, id=start_id, mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                return
            raise

    def read(
        self,
        *,
        count: int = 16,
        block_ms: int | None = 1000,
        from_pending: bool = False,
    ) -> list[StreamMessage]:
        """XREADGROUP 으로 한 묶음 받음.

        from_pending=True → ID "0" (이 consumer 에 이미 배달되었으나 ACK 안 한
        메시지를 다시 받음 — crash 후 재시작 복구). False → ">" (새 메시지).
        """
        last_id = "0" if from_pending else ">"
        raw = self._client.xreadgroup(
            self._group,
            self._consumer_id,
            {self._stream_key: last_id},
            count=count,
            block=block_ms,
        )
        if not raw:
            return []
        # raw = [(stream_key, [(entry_id, fields), ...])]
        result: list[StreamMessage] = []
        for _, entries in raw:  # type: ignore[union-attr]
            for entry_id, fields in entries:
                result.append((str(entry_id), {str(k): str(v) for k, v in fields.items()}))
        return result

    def ack(self, entry_id: str) -> int:
        """XACK — 처리 완료 표시. 반환 = ack 된 메시지 수 (0 = 이미 ack 됨)."""
        # redis-py 동기 클라이언트라 실제 반환은 int. 타입 힌트는 ResponseT 라 cast.
        result = self._client.xack(self._stream_key, self._group, entry_id)
        return int(result)  # type: ignore[arg-type]

    def pending_count(self) -> int:
        """이 그룹의 PEL(pending entries list) 크기."""
        info = self._client.xpending(self._stream_key, self._group)
        # info 는 dict-like — `pending` 키에 총 개수.
        if isinstance(info, dict):
            return int(info.get("pending", 0))
        # 리스트 응답(redis-py 5+) 인 경우 [count, min_id, max_id, [[consumer, n], ...]]
        if isinstance(info, list) and info:
            return int(info[0])
        return 0

    def claim_stale(
        self,
        *,
        min_idle_ms: int,
        count: int = 16,
    ) -> list[StreamMessage]:
        """XAUTOCLAIM 으로 다른 consumer 가 idle 시간 초과 동안 ack 못한 메시지 인계.

        `min_idle_ms` 동안 PEL 에 머문 메시지를 본 consumer_id 에 옮김. crash 한 워커
        의 메시지를 살아 있는 워커가 이어 처리하는 시나리오.
        """
        # redis-py 의 xautoclaim 시그니처: name, groupname, consumername, min_idle_time, start_id="0-0"
        raw = self._client.xautoclaim(
            self._stream_key,
            self._group,
            self._consumer_id,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        # 응답: [next_cursor, [(entry_id, fields), ...], [deleted_ids]] (redis-py 5+).
        # 또는 (next_cursor, claimed_messages, deleted_ids) tuple.
        claimed: list[StreamMessage] = []
        if not raw:
            return claimed
        if isinstance(raw, tuple | list):
            # claimed messages 는 두 번째 요소.
            messages = raw[1] if len(raw) >= 2 else []
            for entry_id, fields in messages:
                claimed.append((str(entry_id), {str(k): str(v) for k, v in fields.items()}))
        return claimed

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._client.close()


# ---------------------------------------------------------------------------
# Pub/Sub (Phase 3.2.1 — pipeline 노드 상태 실시간 SSE)
# ---------------------------------------------------------------------------
class RedisPubSub:
    """Redis PUBLISH 래퍼 — Streams 와 별개 채널 (히스토리 없는 broadcast).

    Phase 3.2.1 노드 상태 전이를 SSE 로 즉시 프론트에 흘리기 위한 채널. 히스토리는
    `run.node_run` 에 영속화되므로 PUB/SUB 메시지 유실은 실행 정합성에 영향 없음.
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RedisPubSub:
        s = settings or get_settings()
        return cls(redis.Redis.from_url(s.redis_url, decode_responses=True))

    def publish(self, channel: str, payload: Mapping[str, Any]) -> int:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        result = self._client.publish(channel, body)
        return int(result) if isinstance(result, int | str) else 0

    async def apublish(self, channel: str, payload: Mapping[str, Any]) -> int:
        return await asyncio.to_thread(self.publish, channel, payload)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._client.close()


__all__ = [
    "RedisPubSub",
    "RedisStreamConsumer",
    "RedisStreamPublisher",
    "StreamMessage",
    "consumer_group_name",
]
