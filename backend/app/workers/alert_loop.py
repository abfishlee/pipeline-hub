"""Phase 8.5 — Alert evaluation lifespan loop (5분 cron)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.alerting import evaluate_and_fire_rules
from app.db.sync_session import get_sync_sessionmaker

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 300.0  # 5분


async def alert_evaluation_loop(stop_event: asyncio.Event) -> None:
    """5분마다 alert rules 평가 + 발사."""
    logger.info("alert_evaluation_loop.started")

    # 첫 evaluation 은 lifespan 시작 30초 후로 지연 (worker 워밍업 시간 확보).
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=30.0)

    while not stop_event.is_set():
        try:
            fired = await asyncio.to_thread(_evaluate_once)
            if fired:
                logger.info(
                    "alert_evaluation_loop.fired",
                    extra={"count": len(fired)},
                )
        except Exception:
            logger.warning("alert_evaluation_loop.iteration_failed", exc_info=True)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SEC)

    logger.info("alert_evaluation_loop.stopped")


def _evaluate_once() -> list:
    sm = get_sync_sessionmaker()
    with sm() as session:
        try:
            results = evaluate_and_fire_rules(session)
            session.commit()
            return results
        except Exception:
            session.rollback()
            raise


__all__ = ["alert_evaluation_loop"]
