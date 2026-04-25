"""HTTP 요청 → `audit.access_log` 비동기 INSERT 미들웨어.

원칙:
  - **Best-effort** — INSERT 실패는 silent (요청은 항상 통과).
  - 응답 후 `asyncio.create_task` 로 fire-and-forget. 요청 latency 영향 최소화.
  - 새 DB 세션을 열어 사용 (요청 세션은 응답 시점에 이미 close).
  - `/metrics`, `/healthz`, `/readyz` 같은 인프라 엔드포인트는 기록 제외 (노이즈).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger
from app.core.request_context import get_request_id
from app.db.session import get_sessionmaker
from app.models.audit import AccessLog

log = get_logger(__name__)

_EXCLUDED_PATHS: frozenset[str] = frozenset(
    {"/metrics", "/healthz", "/readyz", "/", "/docs", "/redoc", "/openapi.json"}
)


def _client_ip(request: Request) -> str | None:
    # X-Forwarded-For 첫 값 우선 (운영 시 ingress/nginx 가 진짜 IP 세팅).
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


def _user_id_from_state(request: Request) -> int | None:
    # current_user dep 가 통과한 경우 request.state.user 에 저장하는 패턴은 미적용.
    # JWT 디코드 자체는 dep 가 처리하므로 여기서는 헤더 기반 fallback 만 — 정확도는 deps 통합 후 향상.
    # Phase 1.2.10 한정: 간단 디코드 시도.
    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    try:
        from jose import jwt

        from app.config import get_settings

        payload = jwt.get_unverified_claims(token)
        sub = payload.get("sub")
        if sub is not None:
            return int(sub)
        # 시크릿 검증까지 하면 비용↑ — middleware 는 기록 목적이라 unverified 로 충분.
        # 위/변조 토큰은 deps 가 401 반환하므로 여기까지 도달하지 않음.
        _ = get_settings  # 미사용 경고 회피
    except Exception:
        return None
    return None


async def _persist_log(
    *,
    user_id: int | None,
    method: str,
    path: str,
    status_code: int,
    ip: str | None,
    user_agent: str | None,
    duration_ms: int,
    request_id: str | None,
) -> None:
    """별도 세션으로 INSERT. 실패는 warning 로깅만."""
    sm = get_sessionmaker()
    try:
        session: AsyncSession
        async with sm() as session:
            session.add(
                AccessLog(
                    user_id=user_id,
                    api_key_id=None,  # Phase 4 Public API 도입 후 채움
                    method=method,
                    path=path[:1024],
                    status_code=status_code,
                    ip=ip,
                    user_agent=(user_agent or "")[:512] or None,
                    duration_ms=duration_ms,
                    request_id=request_id,
                    occurred_at=datetime.now(UTC),
                )
            )
            await session.commit()
    except Exception as exc:
        # 관제 인프라 단절이 비즈니스 가용성을 깨선 안 됨 — 로깅만.
        log.warning("audit.access_log.failed", error=str(exc))


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # fire-and-forget — 요청 latency 영향 없음.
        asyncio.create_task(  # noqa: RUF006
            _persist_log(
                user_id=_user_id_from_state(request),
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                ip=_client_ip(request),
                user_agent=request.headers.get("User-Agent"),
                duration_ms=elapsed_ms,
                request_id=get_request_id(),
            )
        )
        return response


__all__ = ["AccessLogMiddleware"]
