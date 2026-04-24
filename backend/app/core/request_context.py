"""Request-scoped context values (contextvars).

요청 ID 같은 요청별 정보를 미들웨어 → 로거 → 응답 헤더에 걸쳐 전파한다.
"""

from __future__ import annotations

from contextvars import ContextVar

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    return _request_id_var.get()


__all__ = ["get_request_id", "set_request_id"]
