"""HTTP — `/v2/connectors/public-api` (Phase 6 Wave 1).

Source/API Designer (workbench 1) 의 backend.
사용자가 KAMIS / 식약처 / 통계청 등 어떤 API 도 코딩 0줄로 등록.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.public_api import (
    AuthMethod,
    ConnectorSpec,
    HttpMethod,
    PaginationKind,
    ResponseFormat,
    load_spec_from_db,
    save_spec_to_db,
    test_connector,
)
from app.models.domain import DomainDefinition

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v2/connectors/public-api",
    tags=["v2-connectors"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "OPERATOR", "APPROVER"))
    ],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PaginationConfig(BaseModel):
    page_param_name: str | None = None
    size_param_name: str | None = None
    page_size: int = 100
    start_page: int = 1
    offset_param_name: str | None = None
    limit_param_name: str | None = None
    limit: int = 100
    start_offset: int = 0
    cursor_param_name: str | None = None
    cursor_response_path: str | None = None
    start_cursor: Any | None = None


class ConnectorIn(BaseModel):
    domain_code: str
    resource_code: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None

    endpoint_url: str = Field(min_length=1)
    http_method: HttpMethod = HttpMethod.GET

    auth_method: AuthMethod = AuthMethod.NONE
    auth_param_name: str | None = None
    secret_ref: str | None = None

    request_headers: dict[str, str] = Field(default_factory=dict)
    query_template: dict[str, Any] = Field(default_factory=dict)
    body_template: dict[str, Any] | None = None

    pagination_kind: PaginationKind = PaginationKind.NONE
    pagination_config: dict[str, Any] = Field(default_factory=dict)

    response_format: ResponseFormat = ResponseFormat.JSON
    response_path: str | None = None

    timeout_sec: int = Field(default=15, ge=1, le=300)
    retry_max: int = Field(default=2, ge=0, le=10)
    rate_limit_per_min: int = Field(default=60, ge=1, le=10_000)



class ConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connector_id: int
    domain_code: str
    resource_code: str
    name: str
    description: str | None
    endpoint_url: str
    http_method: str
    auth_method: str
    auth_param_name: str | None
    secret_ref: str | None
    request_headers: dict[str, Any]
    query_template: dict[str, Any]
    body_template: dict[str, Any] | None
    pagination_kind: str
    pagination_config: dict[str, Any]
    response_format: str
    response_path: str | None
    timeout_sec: int
    retry_max: int
    rate_limit_per_min: int
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TestCallRequest(BaseModel):
    runtime_params: dict[str, Any] = Field(default_factory=dict)
    max_pages: int = Field(default=1, ge=1, le=10)


class TestCallResponse(BaseModel):
    success: bool
    http_status: int | None
    row_count: int
    duration_ms: int
    request_summary: dict[str, Any]
    sample_rows: list[dict[str, Any]]
    error_message: str | None = None


class StatusTransitionRequest(BaseModel):
    target_status: str = Field(pattern=r"^(REVIEW|APPROVED|PUBLISHED|DRAFT)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        try:
            res = fn(session)
            session.commit()
            return res
        except Exception:
            session.rollback()
            raise


def _spec_from_in(body: ConnectorIn, *, connector_id: int | None) -> ConnectorSpec:
    return ConnectorSpec(
        connector_id=connector_id,
        domain_code=body.domain_code,
        resource_code=body.resource_code,
        name=body.name,
        description=body.description,
        endpoint_url=body.endpoint_url,
        http_method=body.http_method,
        auth_method=body.auth_method,
        auth_param_name=body.auth_param_name,
        secret_ref=body.secret_ref,
        request_headers=dict(body.request_headers),
        query_template=dict(body.query_template),
        body_template=dict(body.body_template) if body.body_template else None,
        pagination_kind=body.pagination_kind,
        pagination_config=dict(body.pagination_config),
        response_format=body.response_format,
        response_path=body.response_path,
        timeout_sec=body.timeout_sec,
        retry_max=body.retry_max,
        rate_limit_per_min=body.rate_limit_per_min,
        status="DRAFT",
        is_active=True,
    )


def _row_to_out(row: Any) -> ConnectorOut:
    return ConnectorOut(
        connector_id=int(row.connector_id),
        domain_code=str(row.domain_code),
        resource_code=str(row.resource_code),
        name=str(row.name),
        description=str(row.description) if row.description else None,
        endpoint_url=str(row.endpoint_url),
        http_method=str(row.http_method),
        auth_method=str(row.auth_method),
        auth_param_name=str(row.auth_param_name) if row.auth_param_name else None,
        secret_ref=str(row.secret_ref) if row.secret_ref else None,
        request_headers=dict(row.request_headers or {}),
        query_template=dict(row.query_template or {}),
        body_template=dict(row.body_template) if row.body_template else None,
        pagination_kind=str(row.pagination_kind),
        pagination_config=dict(row.pagination_config or {}),
        response_format=str(row.response_format),
        response_path=str(row.response_path) if row.response_path else None,
        timeout_sec=int(row.timeout_sec),
        retry_max=int(row.retry_max),
        rate_limit_per_min=int(row.rate_limit_per_min),
        status=str(row.status),
        is_active=bool(row.is_active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _infer_schema_json(sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Test Call sample 을 Field Mapping contract 의 최소 schema 로 저장."""
    properties: dict[str, dict[str, str]] = {}
    for row in sample_rows[:20]:
        for key, value in row.items():
            if key in properties:
                continue
            if isinstance(value, bool):
                typ = "boolean"
            elif isinstance(value, int):
                typ = "integer"
            elif isinstance(value, float):
                typ = "number"
            elif isinstance(value, dict):
                typ = "object"
            elif isinstance(value, list):
                typ = "array"
            else:
                typ = "string"
            properties[str(key)] = {"type": typ}
    return {"type": "object", "properties": properties, "sample_rows": sample_rows[:10]}


def _source_code_for(spec: ConnectorSpec) -> str:
    import re

    raw = f"API_{spec.domain_code}_{spec.resource_code}".upper()
    code = re.sub(r"[^A-Z0-9_]+", "_", raw).strip("_")
    return code[:64] or "API_SOURCE"


def _ensure_contract_from_test_sample(
    s: Session,
    *,
    spec: ConnectorSpec,
    sample_rows: list[dict[str, Any]],
    user_id: int | None,
) -> None:
    """Source/API test 성공 시 Mapping 에서 바로 쓸 source_contract 를 보장.

    wipe 직후 도메인/contract 가 비어 있어도 Source/API → Test Call → Field Mapping
    흐름이 끊기지 않게 하는 실증용 연결 지점이다.
    """
    domain = s.get(DomainDefinition, spec.domain_code)
    if domain is None:
        # Source/API 화면의 빠른 도메인 생성이 정상 경로지만, API 직접 호출도 보호.
        s.add(
            DomainDefinition(
                domain_code=spec.domain_code,
                name=spec.domain_code,
                description="Created from Source/API connector",
                schema_yaml={},
                status="PUBLISHED",
            )
        )
        s.flush()

    source_code = _source_code_for(spec)
    source_id = s.execute(
        text(
            """
            INSERT INTO ctl.data_source
              (source_code, source_name, source_type, is_active, config_json)
            VALUES
              (:code, :name, 'API', TRUE, CAST(:cfg AS JSONB))
            ON CONFLICT (source_code) DO UPDATE SET
              source_name = EXCLUDED.source_name,
              is_active = TRUE,
              config_json = EXCLUDED.config_json,
              updated_at = now()
            RETURNING source_id
            """
        ),
        {
            "code": source_code,
            "name": spec.name,
            "cfg": json.dumps(
                {"connector_id": spec.connector_id, "endpoint_url": spec.endpoint_url},
                ensure_ascii=False,
            ),
        },
    ).scalar_one()
    schema_json = _infer_schema_json(sample_rows)
    s.execute(
        text(
            """
            INSERT INTO domain.source_contract
              (source_id, domain_code, resource_code, schema_version, schema_json,
               compatibility_mode, resource_selector_json, status, description)
            VALUES
              (:sid, :domain, :resource, 1, CAST(:schema AS JSONB),
               'backward', '{}'::jsonb, 'PUBLISHED', :desc)
            ON CONFLICT (source_id, domain_code, resource_code, schema_version)
            DO UPDATE SET
              schema_json = EXCLUDED.schema_json,
              status = 'PUBLISHED',
              description = EXCLUDED.description,
              updated_at = now()
            """
        ),
        {
            "sid": int(source_id),
            "domain": spec.domain_code,
            "resource": spec.resource_code,
            "schema": json.dumps(schema_json, ensure_ascii=False, default=str),
            "desc": f"Auto-generated from Source/API test by user {user_id}",
        },
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.post("", response_model=ConnectorOut, status_code=201)
async def create(body: ConnectorIn, user: CurrentUserDep) -> ConnectorOut:
    def _do(s: Session) -> ConnectorOut:
        spec = _spec_from_in(body, connector_id=None)
        cid = save_spec_to_db(s, spec, created_by=user.user_id)
        s.flush()
        row = s.execute(
            text("SELECT * FROM domain.public_api_connector WHERE connector_id = :id"),
            {"id": cid},
        ).first()
        assert row is not None
        return _row_to_out(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(
    domain_code: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ConnectorOut]:
    def _do(s: Session) -> list[ConnectorOut]:
        sql = "SELECT * FROM domain.public_api_connector "
        params: dict[str, Any] = {"lim": limit}
        clauses: list[str] = []
        if domain_code:
            clauses.append("domain_code = :dom")
            params["dom"] = domain_code
        if status:
            clauses.append("status = :st")
            params["st"] = status
        if clauses:
            sql += "WHERE " + " AND ".join(clauses) + " "
        sql += "ORDER BY connector_id DESC LIMIT :lim"
        rows = s.execute(text(sql), params).all()
        return [_row_to_out(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{connector_id}", response_model=ConnectorOut)
async def get_one(connector_id: int) -> ConnectorOut:
    def _do(s: Session) -> ConnectorOut:
        row = s.execute(
            text("SELECT * FROM domain.public_api_connector WHERE connector_id = :id"),
            {"id": connector_id},
        ).first()
        if row is None:
            raise HTTPException(404, detail=f"connector {connector_id} not found")
        return _row_to_out(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{connector_id}", response_model=ConnectorOut)
async def update(
    connector_id: int, body: ConnectorIn, user: CurrentUserDep
) -> ConnectorOut:
    def _do(s: Session) -> ConnectorOut:
        # DRAFT 만 직접 수정 가능 (사용자 결정 § 13.4).
        existing = load_spec_from_db(s, connector_id=connector_id)
        if existing is None:
            raise HTTPException(404, detail=f"connector {connector_id} not found")
        if existing.status not in ("DRAFT",):
            raise HTTPException(
                409,
                detail=(
                    f"connector status={existing.status} — DRAFT 로 되돌린 뒤 수정하세요."
                ),
            )
        spec = _spec_from_in(body, connector_id=connector_id)
        # status 는 별도 transition 으로만.
        spec.status = existing.status
        save_spec_to_db(s, spec, created_by=user.user_id)
        s.flush()
        row = s.execute(
            text("SELECT * FROM domain.public_api_connector WHERE connector_id = :id"),
            {"id": connector_id},
        ).first()
        assert row is not None
        return _row_to_out(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/{connector_id}/transition", response_model=ConnectorOut)
async def transition(
    connector_id: int, body: StatusTransitionRequest, user: CurrentUserDep
) -> ConnectorOut:
    """상태 전이 — DRAFT→REVIEW→APPROVED→PUBLISHED.

    APPROVED/PUBLISHED 는 ADMIN 만. 권한 체크는 require_roles 가드.
    """

    def _do(s: Session) -> ConnectorOut:
        existing = load_spec_from_db(s, connector_id=connector_id)
        if existing is None:
            raise HTTPException(404, detail=f"connector {connector_id} not found")
        # 단순 전이 매트릭스.
        valid: dict[str, set[str]] = {
            "DRAFT": {"REVIEW"},
            "REVIEW": {"APPROVED", "DRAFT"},
            "APPROVED": {"PUBLISHED", "DRAFT"},
            "PUBLISHED": {"DRAFT"},
        }
        if body.target_status not in valid.get(existing.status, set()):
            raise HTTPException(
                422,
                detail=(
                    f"transition {existing.status}→{body.target_status} not allowed; "
                    f"valid: {sorted(valid.get(existing.status, set()))}"
                ),
            )
        s.execute(
            text(
                "UPDATE domain.public_api_connector "
                "SET status = :st, updated_at = now(), "
                "    approved_by = CASE WHEN :st IN ('APPROVED','PUBLISHED') "
                "                       THEN :uid ELSE approved_by END "
                "WHERE connector_id = :id"
            ),
            {"st": body.target_status, "uid": user.user_id, "id": connector_id},
        )
        s.flush()
        row = s.execute(
            text("SELECT * FROM domain.public_api_connector WHERE connector_id = :id"),
            {"id": connector_id},
        ).first()
        assert row is not None
        return _row_to_out(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{connector_id}", status_code=204)
async def delete(connector_id: int) -> Response:
    def _do(s: Session) -> None:
        existing = load_spec_from_db(s, connector_id=connector_id)
        if existing is None:
            raise HTTPException(404, detail=f"connector {connector_id} not found")
        if existing.status == "PUBLISHED":
            raise HTTPException(
                409,
                detail="PUBLISHED connector 는 삭제 불가 — DRAFT 로 transition 후 삭제",
            )
        s.execute(
            text("DELETE FROM domain.public_api_connector WHERE connector_id = :id"),
            {"id": connector_id},
        )

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Test call — "테스트 호출" 버튼
# ---------------------------------------------------------------------------
@router.post("/{connector_id}/test", response_model=TestCallResponse)
async def test_call(
    connector_id: int, body: TestCallRequest, user: CurrentUserDep
) -> TestCallResponse:
    """1회 호출 → 응답 미리보기. 외부 사이드 이펙트 있음 (실 API 호출)."""

    def _do(s: Session) -> tuple[ConnectorSpec, int | None]:
        spec = load_spec_from_db(s, connector_id=connector_id)
        if spec is None:
            raise HTTPException(404, detail=f"connector {connector_id} not found")
        return spec, user.user_id

    spec, uid = await asyncio.to_thread(_run_in_sync, _do)

    # 실 호출 — sync engine. 별도 thread 로 안전 실행.
    def _call() -> Any:
        return test_connector(spec, runtime_params=body.runtime_params)

    result = await asyncio.to_thread(_call)
    sample_rows = list(result.rows[:10])

    # public_api_run 에 기록.
    def _log(s: Session) -> None:
        s.execute(
            text(
                "INSERT INTO domain.public_api_run "
                "(connector_id, run_kind, runtime_params, request_summary, "
                " http_status, row_count, duration_ms, error_message, sample_rows, "
                " triggered_by, started_at, completed_at) "
                "VALUES (:cid, 'test', CAST(:rp AS JSONB), CAST(:rs AS JSONB), "
                "        :hs, :rc, :dur, :err, CAST(:samp AS JSONB), "
                "        :uid, :sa, :ca)"
            ),
            {
                "cid": connector_id,
                "rp": json.dumps(body.runtime_params, default=str),
                "rs": json.dumps(result.request_summary, default=str),
                "hs": result.request_summary.get("last_http_status"),
                "rc": result.total_row_count,
                "dur": result.duration_ms,
                "err": result.error_message,
                "samp": json.dumps(sample_rows, default=str, ensure_ascii=False),
                "uid": uid,
                "sa": result.started_at,
                "ca": result.completed_at,
            },
        )
        _ensure_contract_from_test_sample(
            s,
            spec=spec,
            sample_rows=sample_rows,
            user_id=uid,
        )

    await asyncio.to_thread(_run_in_sync, _log)

    return TestCallResponse(
        success=result.error_message is None,
        http_status=result.request_summary.get("last_http_status"),
        row_count=result.total_row_count,
        duration_ms=result.duration_ms,
        request_summary=result.request_summary,
        sample_rows=sample_rows,
        error_message=result.error_message,
    )


@router.get("/{connector_id}/runs", response_model=list[dict[str, Any]])
async def list_runs(
    connector_id: int, limit: int = Query(default=20, ge=1, le=200)
) -> list[dict[str, Any]]:
    def _do(s: Session) -> list[dict[str, Any]]:
        rows = s.execute(
            text(
                "SELECT run_id, run_kind, http_status, row_count, duration_ms, "
                "       error_message, started_at, completed_at "
                "FROM domain.public_api_run "
                "WHERE connector_id = :cid "
                "ORDER BY started_at DESC LIMIT :lim"
            ),
            {"cid": connector_id, "lim": limit},
        ).all()
        return [
            {
                "run_id": int(r.run_id),
                "run_kind": str(r.run_kind),
                "http_status": int(r.http_status) if r.http_status else None,
                "row_count": int(r.row_count) if r.row_count is not None else 0,
                "duration_ms": int(r.duration_ms) if r.duration_ms else 0,
                "error_message": str(r.error_message) if r.error_message else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
