"""Server-Sent Events 헬퍼 (Phase 3.2.3).

`StreamingResponse` 위에서 `text/event-stream` 포맷의 메시지를 송출. 운영 시 NKS 의
nginx ingress 가 `proxy_buffering off` + `keepalive_timeout > heartbeat` 가 필요.

heartbeat 가 없으면 idle 연결을 nginx/load balancer 가 90s ~ 5min 사이에 끊는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Content-Type": "text/event-stream; charset=utf-8",
    "X-Accel-Buffering": "no",  # nginx 가 buffer 하지 않도록 — SSE 표준 힌트.
    "Connection": "keep-alive",
}

DEFAULT_HEARTBEAT_INTERVAL_SEC: float = 30.0


def format_event(*, event: str | None = None, data: Any, event_id: str | None = None) -> str:
    """SSE 표준 포맷으로 직렬화.

    `data` 가 dict / list 면 JSON 으로 변환. None 이면 빈 문자열.
    """
    payload: str
    if data is None:
        payload = ""
    elif isinstance(data, str):
        payload = data
    elif isinstance(data, Mapping | list | tuple):
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    else:
        payload = json.dumps(data, ensure_ascii=False, default=str)

    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    # `data:` 는 1줄 1메시지 권장 — 줄바꿈 포함 시 각 줄에 `data:` 접두.
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def heartbeat_event() -> str:
    """30s 간격 keep-alive — `event: ping` + 빈 data."""
    return format_event(event="ping", data={})


async def merged_with_heartbeat(
    source: AsyncIterator[str],
    *,
    interval_sec: float = DEFAULT_HEARTBEAT_INTERVAL_SEC,
) -> AsyncIterator[str]:
    """원본 SSE 메시지 stream + 일정 주기 heartbeat 합치기.

    `source` 가 종료되면 generator 도 종료. 클라이언트 disconnect 는 caller 의
    StreamingResponse 가 처리.
    """
    queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()

    async def _pump_source() -> None:
        try:
            async for msg in source:
                await queue.put(("msg", msg))
        finally:
            await queue.put(("eof", None))

    async def _pump_heartbeat() -> None:
        while True:
            await asyncio.sleep(interval_sec)
            await queue.put(("hb", None))

    pump = asyncio.create_task(_pump_source())
    beat = asyncio.create_task(_pump_heartbeat())
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "eof":
                return
            if kind == "hb":
                yield heartbeat_event()
            else:
                assert payload is not None
                yield payload
    finally:
        beat.cancel()
        pump.cancel()
        # 두 task 가 정리되도록 await — 예외는 무시.
        for t in (beat, pump):
            with contextlib.suppress(Exception):
                await t


__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_SEC",
    "SSE_HEADERS",
    "format_event",
    "heartbeat_event",
    "merged_with_heartbeat",
]
