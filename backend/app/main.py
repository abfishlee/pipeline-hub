"""FastAPI application entrypoint.

NKS Ready 8계명 중 이 파일에서 충족되는 것:
  ② env 기반 설정 (app.config)
  ③ /healthz /readyz 엔드포인트
  ④ SIGTERM graceful shutdown (lifespan + uvicorn --timeout-graceful-shutdown)
  ⑤ stdout JSON 로그 (configure_logging)
  ⑥ request_id 전파 (RequestIdMiddleware)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app import __version__
from app.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging, get_logger
from app.core.request_context import set_request_id

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    """요청마다 request_id 를 발급/전파.

    incoming `X-Request-ID` 가 있으면 그대로 쓰고, 없으면 uuid4 생성.
    모든 응답 헤더에도 돌려줘 분산 추적(Phase 2 OTel)의 기반을 만든다.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        set_request_id(rid)
        request.state.request_id = rid

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response


# ---------------------------------------------------------------------------
# Lifespan (graceful startup/shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings)
    log.info("startup.begin", env=settings.env, version=__version__)
    # TODO(Phase 1.2.3+): DB connection pool + Redis ping readiness 체크 추가.
    log.info("startup.complete")
    try:
        yield
    finally:
        # SIGTERM 시 이 finally 블록이 실행된다.
        log.info("shutdown.begin")
        # TODO(Phase 2): outbox publisher 정리, background task drain, DB pool close
        log.info("shutdown.complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Unified Data Pipeline Platform",
        version=__version__,
        description="농축산물 가격 수집·표준화·서비스 플랫폼 API (Phase 1 skeleton)",
        lifespan=lifespan,
        debug=settings.debug,
        # OpenAPI 는 운영에서만 제한
        openapi_url="/openapi.json" if not settings.is_production else None,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )
    app.state.settings = settings

    # --- Middleware (순서 중요: 바깥 → 안쪽) ---
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    # --- Exception handlers ---
    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": rid,
                    "details": exc.details,
                }
            },
        )

    # --- Health routes ---
    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness probe — 프로세스가 살아있기만 하면 200."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, object]:
        """Readiness probe — 외부 의존성 ping 결과.

        Phase 1.2.3 에서 DB/Redis 연결 확인 추가 예정.
        지금은 구조만 유지.
        """
        checks = {
            "app": "ok",
            # "db": "ok",   # Phase 1.2.3
            # "redis": "ok",# Phase 2
        }
        all_ok = all(v == "ok" for v in checks.values())
        return {
            "status": "ready" if all_ok else "unready",
            "version": __version__,
            "env": settings.env,
            "checks": checks,
        }

    @app.get("/", tags=["meta"], include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "datapipeline-backend",
            "version": __version__,
            "docs": "/docs",
        }

    return app


app = create_app()


__all__ = ["app", "create_app"]
