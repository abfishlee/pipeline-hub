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
from app.api.v1 import auth as auth_router
from app.api.v1 import crowd as crowd_router
from app.api.v1 import dead_letters as dl_router
from app.api.v1 import ingest as ingest_router
from app.api.v1 import internal as internal_router
from app.api.v1 import jobs as jobs_router
from app.api.v1 import pipelines as pipelines_router
from app.api.v1 import public as public_router
from app.api.v1 import raw as raw_router
from app.api.v1 import sources as sources_router
from app.api.v1 import sql_studio as sql_studio_router
from app.api.v1 import sse as sse_router
from app.api.v1 import users as users_router
from app.config import Settings, get_settings
from app.core.access_log import AccessLogMiddleware
from app.core.errors import DomainError
from app.core.logging import configure_logging, get_logger
from app.core.metrics import HttpMetricsMiddleware, metrics_response_body
from app.core.request_context import set_request_id
from app.core.sentry import configure_sentry
from app.db import session as db_session
from app.integrations import object_storage as object_storage_module

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
    sentry_enabled = configure_sentry(settings)
    log.info(
        "startup.begin",
        env=settings.env,
        version=__version__,
        sentry=sentry_enabled,
    )

    # DB 연결 사전 검증. 실패해도 startup 자체는 통과시키고 /readyz 가 unready 보고.
    # (12-Factor: 외부 의존성 일시 단절이 컨테이너 재시작 사유가 되지 않도록)
    if await db_session.ping():
        log.info("db.connected")
    else:
        log.warning("db.unreachable", url_host=settings.database_url.split("@")[-1])

    # Object Storage ping — 동일 정책 (실패해도 startup 통과).
    try:
        storage = object_storage_module.get_object_storage()
        if await storage.ping():
            log.info("object_storage.connected", bucket=storage.bucket)
        else:
            log.warning("object_storage.unreachable", endpoint=settings.os_endpoint)
    except Exception as exc:
        log.warning("object_storage.init_failed", error=str(exc))

    log.info("startup.complete")
    try:
        yield
    finally:
        # SIGTERM 시 이 finally 블록이 실행된다.
        log.info("shutdown.begin")
        await db_session.dispose_engine()
        # TODO(Phase 2): outbox publisher 정리, background task drain, Redis pool close
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

    # --- Middleware (순서 중요: 바깥 → 안쪽 적용) ---
    # add_middleware 는 stack 처럼 동작 — 마지막에 add 한 게 가장 바깥 (요청 처리 시 먼저).
    # 처리 순서: RequestId → CORS → AccessLog → HttpMetrics → 라우터.
    app.add_middleware(HttpMetricsMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIdMiddleware)

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
    async def readyz() -> JSONResponse:
        """Readiness probe — 외부 의존성 ping.

        DB / Object Storage ping 실패 시 503 + 해당 check=fail. healthz 는 영향 없음.
        """
        db_ok = await db_session.ping()
        try:
            os_ok = await object_storage_module.get_object_storage().ping()
        except Exception:
            os_ok = False
        checks: dict[str, str] = {
            "app": "ok",
            "db": "ok" if db_ok else "fail",
            "object_storage": "ok" if os_ok else "fail",
            # "redis": "ok",  # Phase 2
        }
        all_ok = all(v == "ok" for v in checks.values())
        body: dict[str, object] = {
            "status": "ready" if all_ok else "unready",
            "version": __version__,
            "env": settings.env,
            "checks": checks,
        }
        return JSONResponse(content=body, status_code=200 if all_ok else 503)

    @app.get("/", tags=["meta"], include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "datapipeline-backend",
            "version": __version__,
            "docs": "/docs",
        }

    @app.get("/metrics", tags=["health"], include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus exposition. 인증 없음 — 내부 scrape 전용 (NetworkPolicy 로 격리)."""
        body, content_type = metrics_response_body()
        return Response(content=body, media_type=content_type)

    # --- v1 라우터 ---
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(sources_router.router)
    app.include_router(ingest_router.router)
    app.include_router(jobs_router.router)
    app.include_router(raw_router.router)
    # Phase 4.2.1 — legacy /v1/crowd-tasks + 정식 /v1/crowd/tasks 두 router.
    app.include_router(crowd_router.legacy_router)
    app.include_router(crowd_router.router)
    app.include_router(dl_router.router)
    # Phase 4.0.4 — internal_router 가 pipelines_router 보다 먼저 등록되어야 함:
    # POST /v1/pipelines/internal/runs 가 pipelines 의 POST /{workflow_id}/runs 보다
    # 먼저 매칭돼야 JWT dep 가 안 발화한다 (workflow_id="internal" 로 잘못 해석되는 것 방지).
    app.include_router(internal_router.router)
    app.include_router(pipelines_router.router)
    app.include_router(sse_router.router)
    app.include_router(sql_studio_router.router)
    # Phase 4.2.4 — Public API stub (api_key 인증 + RLS).
    app.include_router(public_router.router)

    return app


app = create_app()


__all__ = ["app", "create_app"]
