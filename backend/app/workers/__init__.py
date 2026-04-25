"""Dramatiq Worker 패키지 (Phase 2.2.1).

설계 원칙:
  - **브로커는 단 1개** — Redis (`APP_REDIS_URL`). dramatiq 큐와 Redis Streams 가
    같은 인스턴스를 공유하지만, 큐 prefix(`dp:`) 와 stream prefix(`dp:events:`) 로
    namespace 분리.
  - **Actor 는 얇게** — `app/domain/*` 함수만 호출. 트랜잭션/외부 IO 는 도메인이 책임.
  - **재시도 정책**: max_retries=3, exponential backoff (1s → 2s → 4s).
  - **DLQ**: max_retries 초과 시 `DeadLetterMiddleware` 가 `run.dead_letter` 에
    INSERT. 이후 운영자가 수동 replay (Phase 2.2.x 운영 도구).
  - **앱 코드에서 actor 임포트 자체로 등록되도록** 하위 모듈을 `__init__` 에서 import.

실행:
    cd backend && uv run dramatiq app.workers --processes 1 --threads 4
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from typing import Any

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import Middleware
from sqlalchemy import insert

from app.config import get_settings
from app.db.sync_session import get_sync_sessionmaker
from app.models.run import DeadLetter

# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------
# 테스트는 `APP_DRAMATIQ_STUB=1` 로 StubBroker 강제 (Redis 미가동 환경).
_USE_STUB = os.environ.get("APP_DRAMATIQ_STUB") == "1"


def _build_broker() -> dramatiq.Broker:
    s = get_settings()
    if _USE_STUB:
        broker: dramatiq.Broker = StubBroker()
    else:
        broker = RedisBroker(url=s.redis_url, namespace=s.dramatiq_queue_prefix)
    broker.add_middleware(DeadLetterMiddleware())
    return broker


# ---------------------------------------------------------------------------
# DLQ Middleware
# ---------------------------------------------------------------------------
class DeadLetterMiddleware(Middleware):
    """max_retries 초과 후 영구 실패한 메시지를 `run.dead_letter` 에 기록.

    dramatiq 의 `Retries` 미들웨어가 max_retries 를 다 쓰면 `after_process_message`
    에서 exception=last_exc 와 함께 호출되고, 메시지가 큐에서 제거된다.
    그 직전에 우리가 가로채어 DLQ INSERT.
    """

    def after_process_message(
        self,
        broker: dramatiq.Broker,
        message: dramatiq.Message,
        *,
        result: Any = None,
        exception: BaseException | None = None,
    ) -> None:
        if exception is None:
            return
        retries = int(message.options.get("retries", 0))
        max_retries = int(message.options.get("max_retries", 3))
        if retries < max_retries:
            return  # 아직 재시도 여력 — DLQ 미적재.

        try:
            sm = get_sync_sessionmaker()
            with sm() as session:
                session.execute(
                    insert(DeadLetter).values(
                        origin=message.actor_name,
                        payload_json={
                            "args": list(message.args),
                            "kwargs": dict(message.kwargs),
                            "message_id": message.message_id,
                            "queue_name": message.queue_name,
                        },
                        error_message=f"{type(exception).__name__}: {exception}",
                        stack_trace="".join(
                            traceback.format_exception(type(exception), exception, None)
                        )[:8000],
                    )
                )
                session.commit()
        except Exception:
            # 관제 인프라(DLQ) 단절이 워커 가용성을 깨선 안 됨 — 로깅으로 충분.
            # 동기 logger 대신 stderr (worker stdout 은 Loki 가 수집 — Phase 2 후반).
            import sys

            traceback.print_exc(file=sys.stderr)


# ---------------------------------------------------------------------------
# 공통 actor 데코레이터
# ---------------------------------------------------------------------------
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIME_LIMIT_MS = 60_000  # 60s
DEFAULT_MIN_BACKOFF_MS = 1_000  # 1s
DEFAULT_MAX_BACKOFF_MS = 30_000  # 30s


def pipeline_actor(
    *,
    queue_name: str = "default",
    max_retries: int = DEFAULT_MAX_RETRIES,
    time_limit: int = DEFAULT_TIME_LIMIT_MS,
    min_backoff: int = DEFAULT_MIN_BACKOFF_MS,
    max_backoff: int = DEFAULT_MAX_BACKOFF_MS,
) -> Callable[[Callable[..., Any]], dramatiq.Actor]:
    """프로젝트 표준 actor 데코레이터. dramatiq.actor 의 옵션을 일괄 적용."""

    def _wrap(fn: Callable[..., Any]) -> dramatiq.Actor:
        return dramatiq.actor(
            fn,
            queue_name=queue_name,
            max_retries=max_retries,
            time_limit=time_limit,
            min_backoff=min_backoff,
            max_backoff=max_backoff,
        )

    return _wrap


# ---------------------------------------------------------------------------
# Broker 설정 (모듈 import 시 1회)
# ---------------------------------------------------------------------------
_broker: dramatiq.Broker | None = None


def get_broker() -> dramatiq.Broker:
    global _broker
    if _broker is None:
        _broker = _build_broker()
        dramatiq.set_broker(_broker)
    return _broker


# 워커 프로세스 임포트 시점에 broker 등록 + 모든 actor 모듈 로드.
get_broker()

# 모든 actor 를 broker 에 등록 — 하위 모듈 임포트 자체가 등록 effect.
from app.workers import (  # noqa: E402
    crawler_worker,
    db_incremental_worker,
    ocr_worker,
    outbox_publisher,
    pipeline_node_worker,
    price_fact_worker,
    transform_worker,
)

__all__ = [
    "DeadLetterMiddleware",
    "crawler_worker",
    "db_incremental_worker",
    "get_broker",
    "ocr_worker",
    "outbox_publisher",
    "pipeline_actor",
    "pipeline_node_worker",
    "price_fact_worker",
    "transform_worker",
]
