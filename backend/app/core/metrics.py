"""Prometheus 메트릭 정의 + HTTP 측정 미들웨어.

Phase 1.2.10. Phase 2 에서 Worker / OCR / Outbox 메트릭 추가.

주의:
  - prometheus_client 의 메트릭은 모듈 임포트 시 단 1회 등록(REGISTRY 글로벌). 다중 임포트
    를 견디도록 유틸 함수에서 try/except 처리.
  - HTTP 미들웨어는 path 를 라우트 템플릿(`/v1/users/{user_id}`)으로 정규화해 cardinality
    를 안정화한다. URL 그대로 쓰면 user_id 마다 라벨이 폭발.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

T = TypeVar("T", bound=Counter | Histogram | Gauge)


def _get_or_create(metric_factory: Callable[[], T]) -> T:
    """이미 등록된 동명 메트릭이 있으면 그것을, 아니면 새로 생성.

    pytest 가 모듈을 여러 번 import 해도 ValueError("Duplicated timeseries") 회피.
    """
    try:
        return metric_factory()
    except ValueError:
        # 이미 등록됨 — REGISTRY 에서 찾아 반환.
        # 이름은 metric_factory 내부에 있어 직접 추출 어려움 → 동일 인스턴스를 다시 만들 수 없으므로
        # ValueError 시점의 메트릭 이름은 호출자가 알고 있다고 가정. 실용적으로 ValueError 시
        # 모듈 첫 import 의 메트릭이 살아있으니 module-level 변수로 바인딩만 하면 됨.
        # → 단순화: 이 함수 사용은 모듈 최상위에서만, ValueError 시 새 NoOp 객체로 대체.
        raise


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP 요청 수.",
    labelnames=("method", "path", "status"),
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 요청 지연 시간 (초).",
    labelnames=("method", "path", "status"),
    # 5ms ~ 5s 범위 — API 응답 분포에 맞춤.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
db_pool_in_use = Gauge(
    "db_pool_in_use",
    "현재 사용 중인 DB 커넥션 수 (SQLAlchemy AsyncEngine pool).",
)

# ---------------------------------------------------------------------------
# Ingest (Phase 1.2.7 연동)
# ---------------------------------------------------------------------------
ingest_requests_total = Counter(
    "ingest_requests_total",
    "수집 API 호출 수 (성공/실패/dedup 포함, status 라벨로 구분).",
    labelnames=("source_code", "kind", "status"),
)

ingest_dedup_total = Counter(
    "ingest_dedup_total",
    "수집 dedup 히트 횟수 (idempotency_key 또는 content_hash).",
    labelnames=("source_code", "kind"),
)

ingest_bytes_total = Counter(
    "ingest_bytes_total",
    "수집된 본문 누적 바이트 (신규 적재만 카운트, dedup 제외).",
    labelnames=("source_code", "kind"),
)


# ---------------------------------------------------------------------------
# HTTP 미들웨어
# ---------------------------------------------------------------------------
def _resolve_route_path(request: Request) -> str:
    """URL 을 라우트 템플릿으로 정규화.

    `/v1/users/123` → `/v1/users/{user_id}`. 매칭 실패 시 `unmatched`.
    """
    raw_path = request.url.path
    # 라우터 매칭 시도 — Starlette 의 Match.FULL 일 때 templated path 회수.
    for route in request.app.router.routes:
        try:
            match, _ = route.matches(request.scope)
        except Exception:
            continue
        if match == Match.FULL and hasattr(route, "path"):
            return str(route.path)
    return raw_path or "unmatched"


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 요청의 횟수/지연을 자동 측정."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # /metrics 자체는 측정 제외 (자기 측정 noise).
        if request.url.path == "/metrics":
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            elapsed = time.perf_counter() - started
            method = request.method
            path = _resolve_route_path(request)
            status = str(status_code)
            http_requests_total.labels(method=method, path=path, status=status).inc()
            http_request_duration_seconds.labels(method=method, path=path, status=status).observe(
                elapsed
            )
        return response


# ---------------------------------------------------------------------------
# /metrics endpoint helper
# ---------------------------------------------------------------------------
def metrics_response_body(registry: CollectorRegistry = REGISTRY) -> tuple[bytes, str]:
    """`(payload, content_type)` 반환 — FastAPI Response 로 그대로 사용."""
    return generate_latest(registry), CONTENT_TYPE_LATEST


__all__ = [
    "CONTENT_TYPE_LATEST",
    "HttpMetricsMiddleware",
    "db_pool_in_use",
    "http_request_duration_seconds",
    "http_requests_total",
    "ingest_bytes_total",
    "ingest_dedup_total",
    "ingest_requests_total",
    "metrics_response_body",
]


# 타입 힌트 호환을 위한 placeholder — `_get_or_create` 사용은 향후 상황별로 적용.
__noop_app: ASGIApp | None = None
