"""SSE 라우터 — Pipeline run 노드 상태 실시간 stream (Phase 3.2.3).

`GET /v1/pipelines/runs/{run_id}/events` —
  - 인증된 사용자(OPERATOR+) 가 connect.
  - pipeline_run 존재 검증.
  - Redis Pub/Sub `pipeline:{run_id}` 구독 → SSE 로 forward.
  - 30s heartbeat.
  - 클라이언트 disconnect 시 cleanup (StreamingResponse 가 generator close).

워크플로 정의 변경 / 다른 run 조회는 `GET /v1/pipelines/runs/{run_id}` (REST,
Phase 3.2.1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from app.core.sse import (
    DEFAULT_HEARTBEAT_INTERVAL_SEC,
    SSE_HEADERS,
    format_event,
    merged_with_heartbeat,
)
from app.deps import SessionDep, require_roles
from app.domain.pipeline_runtime import PUBSUB_CHANNEL_PREFIX
from app.integrations.redis_pubsub_async import AsyncRedisPubSub
from app.repositories import pipelines as pipelines_repo

router = APIRouter(
    prefix="/v1/pipelines",
    tags=["pipelines-sse"],
    dependencies=[Depends(require_roles("ADMIN", "APPROVER", "OPERATOR"))],
)


async def _stream_pipeline_events(
    request: Request,
    *,
    pipeline_run_id: int,
) -> AsyncIterator[str]:
    """Redis Pub/Sub → SSE generator. heartbeat 와 합친 형태로 yield."""
    channel = f"{PUBSUB_CHANNEL_PREFIX}:{pipeline_run_id}"
    pubsub = AsyncRedisPubSub.from_settings()

    async def _source() -> AsyncIterator[str]:
        try:
            async with pubsub:
                async for raw in pubsub.subscribe(channel):
                    # 클라이언트 disconnect 시 즉시 종료.
                    if await request.is_disconnected():
                        return
                    yield format_event(event="node.state.changed", data=raw)
        except Exception as exc:
            yield format_event(event="error", data={"error": str(exc)})

    # opening event — 구독 직후 한 번. 클라이언트가 연결 확립을 즉시 인지.
    yield format_event(
        event="open",
        data={"pipeline_run_id": pipeline_run_id, "channel": channel},
    )
    async for chunk in merged_with_heartbeat(
        _source(),
        interval_sec=DEFAULT_HEARTBEAT_INTERVAL_SEC,
    ):
        yield chunk


@router.get("/runs/{pipeline_run_id}/events")
async def pipeline_run_events(
    request: Request,
    session: SessionDep,
    pipeline_run_id: int,
) -> StreamingResponse:
    detail = await pipelines_repo.get_pipeline_run_with_nodes(session, pipeline_run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"pipeline_run {pipeline_run_id} not found")

    return StreamingResponse(
        _stream_pipeline_events(request, pipeline_run_id=pipeline_run_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


__all__ = ["router"]
