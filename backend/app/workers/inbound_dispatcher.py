"""Inbound envelope → workflow trigger background dispatcher (Phase 8.1).

`POST /v1/inbound/{channel_code}` 가 envelope 을 RECEIVED 로 저장하면, 본 dispatcher
가 5초마다 polling 하여 channel.workflow_id 가 binding 된 envelope 을 PROCESSING
으로 전환하고 workflow run 을 trigger.

main.py 의 lifespan 에서 task 시작 + SIGTERM 시 stop_event 로 graceful shutdown.

향후 보강:
  - Dramatiq actor 로 분산 처리 (Wave 6 정식)
  - rate limit per channel_code
  - DLQ 자동 라우팅
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime

from app.db.sync_session import get_sync_sessionmaker
from app.domain.inbound_dispatch import dispatch_received_envelopes

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5.0
BATCH_LIMIT = 20

# Phase 8.5 — Operations Dashboard 가 dispatcher 헬스를 조회하기 위한 best-effort
# 메모리 heartbeat. process restart 시 reset 되지만 같은 process 안에서는 유효.
_LAST_DISPATCH_AT: datetime | None = None
_LAST_DISPATCHED_COUNT: int = 0


async def inbound_dispatcher_loop(stop_event: asyncio.Event) -> None:
    """Background loop — 5초마다 RECEIVED envelope 일괄 dispatch."""
    logger.info("inbound_dispatcher_loop.started")

    while not stop_event.is_set():
        global _LAST_DISPATCH_AT, _LAST_DISPATCHED_COUNT
        try:
            results = await asyncio.to_thread(_run_dispatch_batch)
            _LAST_DISPATCH_AT = datetime.utcnow()
            _LAST_DISPATCHED_COUNT = (
                sum(1 for r in results if r.status == "dispatched") if results else 0
            )
            if results:
                logger.info(
                    "inbound_dispatcher.batch",
                    extra={
                        "dispatched": sum(1 for r in results if r.status == "dispatched"),
                        "manual": sum(1 for r in results if r.status == "manual"),
                        "failed": sum(1 for r in results if r.status == "failed"),
                    },
                )
        except Exception:
            logger.warning("inbound_dispatcher.iteration_failed", exc_info=True)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SEC)

    logger.info("inbound_dispatcher_loop.stopped")


def _run_dispatch_batch() -> list:
    """단일 batch 처리 — sync session 안에서."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        try:
            results = dispatch_received_envelopes(session, limit=BATCH_LIMIT)
            session.commit()
            return results
        except Exception:
            session.rollback()
            raise


__all__ = ["inbound_dispatcher_loop"]
