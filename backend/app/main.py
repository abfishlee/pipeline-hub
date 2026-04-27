"""FastAPI application entrypoint.

NKS Ready 8계명 중 이 파일에서 충족되는 것:
  ② env 기반 설정 (app.config)
  ③ /healthz /readyz 엔드포인트
  ④ SIGTERM graceful shutdown (lifespan + uvicorn --timeout-graceful-shutdown)
  ⑤ stdout JSON 로그 (configure_logging)
  ⑥ request_id 전파 (RequestIdMiddleware)
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# Windows + psycopg async = SelectorEventLoop 강제 (Phase 6 Wave 6 로컬 dev fix).
# ProactorEventLoop 는 psycopg async 와 비호환. NCP/NKS Linux 에는 영향 없음.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app import __version__
from app.api.v1 import admin_partitions as admin_partitions_router
from app.api.v1 import api_keys as api_keys_router
from app.api.v1 import auth as auth_router
from app.api.v1 import crowd as crowd_router
from app.api.v1 import dead_letters as dl_router
from app.api.v1 import inbound as inbound_router
from app.api.v1 import ingest as ingest_router
from app.api.v1 import internal as internal_router
from app.api.v1 import jobs as jobs_router
from app.api.v1 import master_merge as master_merge_router
from app.api.v1 import pipelines as pipelines_router
from app.api.v1 import public as public_router
from app.api.v1 import raw as raw_router
from app.api.v1 import security_events as security_events_router
from app.api.v1 import sources as sources_router
from app.api.v1 import sql_studio as sql_studio_router
from app.api.v1 import sse as sse_router
from app.api.v1 import users as users_router
from app.api.v2 import backfill as v2_backfill_router
from app.api.v2 import checklist as v2_checklist_router
from app.api.v2 import connectors as v2_connectors_router
from app.api.v2 import contracts as v2_contracts_router
from app.api.v2 import cutover as v2_cutover_router
from app.api.v2 import domains as v2_domains_router
from app.api.v2 import dq_rules as v2_dq_rules_router
from app.api.v2 import dryrun as v2_dryrun_router
from app.api.v2 import inbound_channels as v2_inbound_channels_router
from app.api.v2 import load_policies as v2_load_policies_router
from app.api.v2 import mappings as v2_mappings_router
from app.api.v2 import mart_drafts as v2_mart_drafts_router
from app.api.v2 import namespaces as v2_namespaces_router
from app.api.v2 import operations as v2_operations_router
from app.api.v2 import perf as v2_perf_router
from app.api.v2 import permissions as v2_permissions_router
from app.api.v2 import providers as v2_providers_router
from app.api.v2 import public_router as v2_public_router
from app.api.v2 import resources as v2_resources_router
from app.api.v2 import service_mart as v2_service_mart_router
from app.api.v2 import sql_assets as v2_sql_assets_router
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


class PublicApiUsageMiddleware(BaseHTTPMiddleware):
    """Phase 4.2.5 — /public/v1/* 호출 1건당 audit.public_api_usage 1 row.

    require_endpoint dependency 가 request.state 에 api_key_id/endpoint/scope 를
    심어 두면 본 미들웨어가 응답 종료 시 비동기로 INSERT (fire-and-forget).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith("/public/"):
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        api_key_id = getattr(request.state, "public_api_key_id", None)
        endpoint = getattr(request.state, "public_api_endpoint", None)
        scope = getattr(request.state, "public_api_scope", None)
        if api_key_id is not None and endpoint is not None:
            import contextlib

            from app.api.v1.public import record_usage_async
            from app.core.abuse_detector import evaluate_request

            ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            with contextlib.suppress(Exception):
                await record_usage_async(
                    api_key_id=int(api_key_id),
                    endpoint=str(endpoint),
                    scope=scope,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    ip_addr=ip,
                )
            # Phase 4.2.6 — abuse 평가 (Redis 미가동 시 fail-open).
            with contextlib.suppress(Exception):
                await evaluate_request(
                    api_key_id=int(api_key_id),
                    status_code=response.status_code,
                    ip=ip,
                    user_agent=user_agent,
                )
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

    # Phase 8.1 — Inbound dispatcher background task 시작.
    inbound_stop = asyncio.Event()
    inbound_task: asyncio.Task[None] | None = None
    # Phase 8.5 — Alert evaluation 5분 cron task.
    alert_stop = asyncio.Event()
    alert_task: asyncio.Task[None] | None = None
    if settings.env != "test":
        from app.workers.alert_loop import alert_evaluation_loop
        from app.workers.inbound_dispatcher import inbound_dispatcher_loop

        inbound_task = asyncio.create_task(
            inbound_dispatcher_loop(inbound_stop)
        )
        log.info("inbound_dispatcher.scheduled")
        alert_task = asyncio.create_task(alert_evaluation_loop(alert_stop))
        log.info("alert_evaluation.scheduled")

    log.info("startup.complete")
    try:
        yield
    finally:
        # SIGTERM 시 이 finally 블록이 실행된다.
        log.info("shutdown.begin")
        if inbound_task is not None:
            inbound_stop.set()
            try:
                await asyncio.wait_for(inbound_task, timeout=10.0)
            except (TimeoutError, asyncio.CancelledError):
                inbound_task.cancel()
        if alert_task is not None:
            alert_stop.set()
            try:
                await asyncio.wait_for(alert_task, timeout=10.0)
            except (TimeoutError, asyncio.CancelledError):
                alert_task.cancel()
        await db_session.dispose_engine()
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
    # 처리 순서: RequestId → CORS → AccessLog → PublicApiUsage → HttpMetrics → 라우터.
    app.add_middleware(HttpMetricsMiddleware)
    app.add_middleware(PublicApiUsageMiddleware)
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
        headers: dict[str, str] = {}
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is not None:
            headers["Retry-After"] = str(int(retry_after))
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
            headers=headers,
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
    # Phase 7 Wave 1A — 외부 push receiver (HMAC + idempotency).
    app.include_router(inbound_router.router)
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
    # Phase 4.2.5 — api_key admin CRUD (ADMIN 만).
    app.include_router(api_keys_router.router)
    # Phase 4.2.6 — security events 조회 (ADMIN 만).
    app.include_router(security_events_router.router)
    # Phase 4.2.7 — partition archive 관리 (ADMIN 만).
    app.include_router(admin_partitions_router.router)
    # Phase 4.2.8 — multi-source 머지 (ADMIN/APPROVER).
    app.include_router(master_merge_router.router)
    # Phase 5.2.1 — v2 generic registry (ADMIN/DOMAIN_ADMIN).
    app.include_router(v2_domains_router.router)
    app.include_router(v2_contracts_router.router)
    app.include_router(v2_mappings_router.router)
    app.include_router(v2_providers_router.router)
    # Phase 5.2.4 STEP 7 — ETL UX MVP backend.
    app.include_router(v2_permissions_router.router)
    app.include_router(v2_dryrun_router.router)
    app.include_router(v2_dq_rules_router.router)
    app.include_router(v2_checklist_router.router)
    # Phase 5.2.5 STEP 8 — v1 → v2 plugin shadow + cutover.
    app.include_router(v2_cutover_router.router)
    # Phase 5.2.8 STEP 11 — perf SLO + Performance Coach + backfill.
    app.include_router(v2_perf_router.router)
    app.include_router(v2_backfill_router.router)
    # Phase 6 Wave 1 — Public API Connector (Source/API workbench backend).
    app.include_router(v2_connectors_router.router)
    # Phase 6 Wave 2B — SQL Asset CRUD (Transform Designer SQL 탭).
    app.include_router(v2_sql_assets_router.router)
    # Phase 6 Wave 3 — Mart Workbench (mart_drafts + load_policies + resources).
    app.include_router(v2_mart_drafts_router.router)
    app.include_router(v2_load_policies_router.router)
    app.include_router(v2_resources_router.router)
    # Phase 6 Wave 6 — Quality Workbench (Standardization 탭).
    app.include_router(v2_namespaces_router.router)
    # Phase 7 Wave 1A — Inbound channel CRUD (외부 push 채널 등록).
    app.include_router(v2_inbound_channels_router.router)
    # Phase 7 Wave 5 — Operations Dashboard.
    app.include_router(v2_operations_router.router)
    # Phase 8 — Service Mart Viewer.
    app.include_router(v2_service_mart_router.router)

    # Phase 4.2.5 — Public API sub-app: /public/docs / /public/v1/*
    public_app = FastAPI(
        title="Pipeline Hub Public API",
        version=__version__,
        description="외부 API key 인증 기반 mart 공개 조회 API.",
        openapi_url="/openapi.json" if not settings.is_production else None,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    @public_app.exception_handler(DomainError)
    async def _public_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return await _domain_error(request, exc)

    public_app.include_router(public_router.router)
    # Phase 5.2.7 STEP 10 — multi-domain /public/v2/{domain}/*
    public_app.include_router(v2_public_router.router)
    app.mount("/public", public_app)

    return app


app = create_app()


__all__ = ["app", "create_app"]
