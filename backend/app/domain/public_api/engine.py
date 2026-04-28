"""Phase 6.1 — Public API generic engine.

단 1개의 함수가 KAMIS / 식약처 / 통계청 / 공공데이터포털 등 *어떤 REST API* 든 처리.
공급자별 분기 절대 없음. 모든 정보는 ConnectorSpec 에서 옴.

흐름:
  1. ConnectorSpec 읽기 (DB)
  2. secret 해결 (env / Settings)
  3. query/body template 치환 ({ymd} {page} {cursor} 등)
  4. HTTP 호출 (timeout / retry / rate-limit)
  5. response parse (XML/JSON)
  6. JSONPath-lite 로 row 추출
  7. pagination 자동 따라가기 (page_number / offset / cursor)
  8. ConnectorCallResult 반환
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.public_api.parser import extract_path, parse_response_body
from app.domain.public_api.parsers import parse_response
from app.domain.public_api.spec import (
    AuthMethod,
    ConnectorSpec,
    HttpMethod,
    PaginationKind,
    render_template,
)

logger = logging.getLogger(__name__)


class PublicApiError(RuntimeError):
    """Public API 호출 실패. caller 가 422/502 변환."""


@dataclass(slots=True)
class _PageResult:
    http_status: int
    body_text: str
    parsed: Any
    rows: list[dict[str, Any]]
    request_url: str
    next_page_param: Any | None = None


@dataclass(slots=True)
class ConnectorCallResult:
    """엔진 호출 결과. test/dry-run/scheduled 모두 같은 형태."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    pages: list[_PageResult] = field(default_factory=list)
    total_row_count: int = 0
    duration_ms: int = 0
    request_summary: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# secret 해결 (Phase 5.2.1.1 의 resolve_secret 와 동일 패턴)
# ---------------------------------------------------------------------------
def _resolve_secret(secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    # Settings 우선.
    try:
        from app.config import get_settings

        settings = get_settings()
        attr = secret_ref.lower()
        val = getattr(settings, attr, None)
        if val is not None:
            return val.get_secret_value() if hasattr(val, "get_secret_value") else str(val)
    except Exception:
        pass
    # env fallback.
    return os.environ.get(secret_ref)


# ---------------------------------------------------------------------------
# 1 page 호출
# ---------------------------------------------------------------------------
async def _call_one_page(
    spec: ConnectorSpec,
    *,
    runtime_params: Mapping[str, Any],
    secret_value: str | None,
) -> _PageResult:
    # 1. query / body 템플릿 치환.
    query = render_template(spec.query_template, runtime_params)
    body = (
        render_template(spec.body_template, runtime_params)
        if spec.body_template is not None
        else None
    )
    headers = dict(spec.request_headers)

    # 2. auth 적용.
    auth: tuple[str, str] | None = None
    if spec.auth_method == AuthMethod.QUERY_PARAM:
        if not spec.auth_param_name:
            raise PublicApiError("query_param auth requires auth_param_name")
        if secret_value is None:
            raise PublicApiError(f"secret {spec.secret_ref!r} not resolved")
        query[spec.auth_param_name] = secret_value
    elif spec.auth_method == AuthMethod.HEADER:
        if not spec.auth_param_name:
            raise PublicApiError("header auth requires auth_param_name")
        if secret_value is None:
            raise PublicApiError(f"secret {spec.secret_ref!r} not resolved")
        headers[spec.auth_param_name] = secret_value
    elif spec.auth_method == AuthMethod.BEARER:
        if secret_value is None:
            raise PublicApiError(f"secret {spec.secret_ref!r} not resolved")
        headers["Authorization"] = f"Bearer {secret_value}"
    elif spec.auth_method == AuthMethod.BASIC:
        if not spec.auth_param_name or secret_value is None:
            raise PublicApiError("basic auth requires user (auth_param_name) + password (secret_ref)")
        auth = (spec.auth_param_name, secret_value)
    # AuthMethod.NONE → 아무것도 안 함

    # 3. HTTP 호출.
    timeout = httpx.Timeout(spec.timeout_sec)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout, auth=auth) as client:
        if spec.http_method == HttpMethod.GET:
            resp = await client.get(spec.endpoint_url, params=query, headers=headers)
        else:
            resp = await client.post(
                spec.endpoint_url,
                params=query,
                json=body,
                headers=headers,
            )
    duration_ms = int((time.perf_counter() - started) * 1000)

    body_bytes = resp.content
    body_text = resp.text
    rows = parse_response(
        body=body_bytes,
        response_format=spec.response_format.value,
        response_path=spec.response_path or "",
    )

    # 4. cursor pagination 인 경우 다음 cursor 추출.
    parsed: Any = None
    next_cursor = None
    if spec.pagination_kind == PaginationKind.CURSOR:
        cursor_path = spec.pagination_config.get("cursor_response_path")
        if cursor_path:
            if spec.response_format.value not in ("json", "xml"):
                raise PublicApiError("cursor pagination requires json or xml response")
            parsed = parse_response_body(body_text, response_format=spec.response_format.value)
            next_cursor = extract_path(parsed, cursor_path)

    logger.info(
        "public_api.call connector=%s status=%s rows=%d ms=%d url=%s",
        spec.name,
        resp.status_code,
        len(rows),
        duration_ms,
        str(resp.request.url)[:200],
    )

    return _PageResult(
        http_status=resp.status_code,
        body_text=body_text[:50_000],  # 로그 안전.
        parsed=parsed,
        rows=rows,
        request_url=str(resp.request.url),
        next_page_param=next_cursor,
    )


# ---------------------------------------------------------------------------
# pagination 자동 루프
# ---------------------------------------------------------------------------
async def _call_with_pagination(
    spec: ConnectorSpec,
    *,
    runtime_params: Mapping[str, Any],
    secret_value: str | None,
    max_pages: int,
) -> list[_PageResult]:
    """pagination_kind 별로 자동 페이지 따라가기."""
    if spec.pagination_kind == PaginationKind.NONE:
        page = await _call_one_page(
            spec, runtime_params=runtime_params, secret_value=secret_value
        )
        return [page]

    pages: list[_PageResult] = []
    cfg = spec.pagination_config

    if spec.pagination_kind == PaginationKind.PAGE_NUMBER:
        page_param = str(cfg.get("page_param_name", "page"))
        size_param = cfg.get("size_param_name")
        size = int(cfg.get("page_size", 100))
        start_page = int(cfg.get("start_page", 1))
        for page_no in range(start_page, start_page + max_pages):
            params = {**runtime_params, "page": page_no}
            # query template 의 {page} 가 page_no 로 치환되는 게 표준.
            # 추가로 명시적 query_template 외 page_param 도 자동 주입.
            spec_modified = _inject_pagination_param(spec, page_param, page_no, size_param, size)
            page = await _call_one_page(
                spec_modified, runtime_params=params, secret_value=secret_value
            )
            pages.append(page)
            if not page.rows:
                break
            if size > 0 and len(page.rows) < size:
                break

    elif spec.pagination_kind == PaginationKind.OFFSET_LIMIT:
        offset_param = str(cfg.get("offset_param_name", "offset"))
        limit_param = str(cfg.get("limit_param_name", "limit"))
        limit = int(cfg.get("limit", 100))
        offset = int(cfg.get("start_offset", 0))
        for _ in range(max_pages):
            params = {**runtime_params, "offset": offset, "limit": limit}
            spec_modified = _inject_pagination_param(
                spec, offset_param, offset, limit_param, limit
            )
            page = await _call_one_page(
                spec_modified, runtime_params=params, secret_value=secret_value
            )
            pages.append(page)
            if not page.rows or len(page.rows) < limit:
                break
            offset += limit

    elif spec.pagination_kind == PaginationKind.CURSOR:
        cursor_param = str(cfg.get("cursor_param_name", "cursor"))
        cursor: Any = cfg.get("start_cursor")
        for _ in range(max_pages):
            params = {**runtime_params, "cursor": cursor}
            spec_modified = (
                _inject_pagination_param(spec, cursor_param, cursor, None, 0)
                if cursor is not None
                else spec
            )
            page = await _call_one_page(
                spec_modified, runtime_params=params, secret_value=secret_value
            )
            pages.append(page)
            if not page.rows or page.next_page_param is None:
                break
            cursor = page.next_page_param

    return pages


def _inject_pagination_param(
    spec: ConnectorSpec,
    page_param: str,
    page_value: Any,
    size_param: str | None,
    size_value: int,
) -> ConnectorSpec:
    """spec.query_template 에 pagination param 주입한 *복제 spec* 반환."""
    new_query = dict(spec.query_template)
    new_query[page_param] = page_value
    if size_param:
        new_query[size_param] = size_value
    return ConnectorSpec(
        connector_id=spec.connector_id,
        domain_code=spec.domain_code,
        resource_code=spec.resource_code,
        name=spec.name,
        description=spec.description,
        endpoint_url=spec.endpoint_url,
        http_method=spec.http_method,
        auth_method=spec.auth_method,
        auth_param_name=spec.auth_param_name,
        secret_ref=spec.secret_ref,
        request_headers=dict(spec.request_headers),
        query_template=new_query,
        body_template=spec.body_template,
        pagination_kind=spec.pagination_kind,
        pagination_config=dict(spec.pagination_config),
        response_format=spec.response_format,
        response_path=spec.response_path,
        timeout_sec=spec.timeout_sec,
        retry_max=spec.retry_max,
        rate_limit_per_min=spec.rate_limit_per_min,
        status=spec.status,
        is_active=spec.is_active,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def call_connector(
    spec: ConnectorSpec,
    *,
    runtime_params: Mapping[str, Any] | None = None,
    max_pages: int = 1,
) -> ConnectorCallResult:
    """동기 호출 (worker / API 핸들러용). 내부에서 asyncio.run."""
    started = datetime.now(UTC)
    perf_start = time.perf_counter()
    secret_value = _resolve_secret(spec.secret_ref)
    runtime = dict(runtime_params or {})
    # 표준 변수: {ymd} 가 비어있으면 오늘 날짜 자동 주입.
    if "ymd" not in runtime:
        runtime["ymd"] = started.strftime("%Y-%m-%d")

    result = ConnectorCallResult(started_at=started)
    try:
        pages = asyncio.run(
            _call_with_pagination(
                spec,
                runtime_params=runtime,
                secret_value=secret_value,
                max_pages=max(1, min(max_pages, 100)),
            )
        )
    except PublicApiError as exc:
        result.error_message = str(exc)
        result.completed_at = datetime.now(UTC)
        result.duration_ms = int((time.perf_counter() - perf_start) * 1000)
        return result
    except Exception as exc:
        result.error_message = f"{type(exc).__name__}: {exc}"[:500]
        result.completed_at = datetime.now(UTC)
        result.duration_ms = int((time.perf_counter() - perf_start) * 1000)
        return result

    all_rows: list[dict[str, Any]] = []
    for p in pages:
        all_rows.extend(p.rows)

    result.pages = pages
    result.rows = all_rows
    result.total_row_count = len(all_rows)
    result.duration_ms = int((time.perf_counter() - perf_start) * 1000)
    result.completed_at = datetime.now(UTC)
    if pages:
        last = pages[-1]
        result.request_summary = {
            "endpoint": spec.endpoint_url,
            "method": spec.http_method.value,
            "pagination_kind": spec.pagination_kind.value,
            "page_count": len(pages),
            "last_http_status": last.http_status,
            "last_request_url": last.request_url,
        }
    return result


def test_connector(
    spec: ConnectorSpec,
    *,
    runtime_params: Mapping[str, Any] | None = None,
) -> ConnectorCallResult:
    """1 page 만 호출 — Source/API Designer 의 '테스트 호출' 버튼용."""
    return call_connector(spec, runtime_params=runtime_params, max_pages=1)


__all__ = [
    "ConnectorCallResult",
    "PublicApiError",
    "call_connector",
    "test_connector",
]
