"""Structured logging (structlog → stdout).

로컬(`APP_LOG_JSON=false`)은 사람 읽기 쉬운 ConsoleRenderer,
운영은 JSON. 컨테이너 런타임(K8s/Docker)이 stdout을 수집한다.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.config import Settings


def _add_request_id(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Copy contextvar `request_id` 를 이벤트 딕셔너리로 전파."""
    from app.core.request_context import get_request_id

    rid = get_request_id()
    if rid:
        event_dict.setdefault("request_id", rid)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. 앱 시작 시 1회 호출."""
    # stdlib root logger → structlog 포맷터 사용
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor
    if settings.log_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # 3rd-party 로거 수준 조정 (너무 시끄러운 것들)
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """애플리케이션 전역 logger getter."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = ["configure_logging", "get_logger"]
