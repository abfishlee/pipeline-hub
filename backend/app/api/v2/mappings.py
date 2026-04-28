"""HTTP — `/v2/mappings` (Phase 6 Wave 2A — Field Mapping workbench backend).

Phase 5 의 list-only 에서 CRUD + dry-run + helper endpoints 로 확장.
Field Mapping Designer 가 사용. Workbench 가 자산 (mapping) 을 row 단위로 관리.

자산 정책 (사용자 § 13.4):
  DRAFT 만 직접 수정. APPROVED/PUBLISHED 는 새 버전 생성 (Phase 7 backlog).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.functions import list_functions
from app.domain.inbound_contracts import get_contract
from app.models.domain import FieldMapping

router = APIRouter(
    prefix="/v2/mappings",
    tags=["v2-mappings"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "OPERATOR", "APPROVER"))
    ],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FieldMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mapping_id: int
    contract_id: int
    source_path: str
    target_table: str
    target_column: str
    transform_expr: str | None
    data_type: str | None
    is_required: bool
    order_no: int
    status: str
    created_at: datetime
    updated_at: datetime


class FieldMappingIn(BaseModel):
    contract_id: int = Field(ge=1)
    source_path: str = Field(min_length=1, max_length=500)
    target_table: str = Field(min_length=1, max_length=200)
    target_column: str = Field(min_length=1, max_length=120)
    transform_expr: str | None = None
    data_type: str | None = None
    is_required: bool = False
    order_no: int = Field(default=0, ge=0)


class StatusTransitionRequest(BaseModel):
    target_status: str = Field(pattern=r"^(REVIEW|APPROVED|PUBLISHED|DRAFT)$")


class FunctionSpecOut(BaseModel):
    name: str
    category: str
    description: str
    arity_min: int
    arity_max: int | None


class TableColumnOut(BaseModel):
    column_name: str
    data_type: str
    is_nullable: bool
    ordinal_position: int


class MappingSourceOut(BaseModel):
    source_type: str
    source_id: str
    contract_id: int
    domain_code: str
    resource_code: str
    label: str
    status: str
    item_path: str | None = None
    payload_schema: dict[str, Any]
    sample_payload: dict[str, Any]


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


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[FieldMappingOut])
async def list_mappings(
    contract_id: int | None = None,
    target_table: str | None = None,
    status: str | None = None,
) -> list[FieldMappingOut]:
    def _do(s: Session) -> list[FieldMappingOut]:
        q = select(FieldMapping).order_by(
            FieldMapping.contract_id, FieldMapping.order_no, FieldMapping.mapping_id
        )
        if contract_id is not None:
            q = q.where(FieldMapping.contract_id == contract_id)
        if target_table:
            q = q.where(FieldMapping.target_table == target_table)
        if status:
            q = q.where(FieldMapping.status == status)
        rows = s.execute(q).scalars().all()
        return [FieldMappingOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=FieldMappingOut, status_code=201)
async def create_mapping(body: FieldMappingIn, user: CurrentUserDep) -> FieldMappingOut:
    del user

    def _do(s: Session) -> FieldMappingOut:
        m = FieldMapping(
            contract_id=body.contract_id,
            source_path=body.source_path,
            target_table=body.target_table,
            target_column=body.target_column,
            transform_expr=body.transform_expr,
            data_type=body.data_type,
            is_required=body.is_required,
            order_no=body.order_no,
            status="DRAFT",
        )
        s.add(m)
        s.flush()
        return FieldMappingOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{mapping_id}", response_model=FieldMappingOut)
async def update_mapping(
    mapping_id: int, body: FieldMappingIn, user: CurrentUserDep
) -> FieldMappingOut:
    del user

    def _do(s: Session) -> FieldMappingOut:
        m = s.get(FieldMapping, mapping_id)
        if m is None:
            raise HTTPException(404, detail=f"mapping {mapping_id} not found")
        if m.status != "DRAFT":
            raise HTTPException(
                409,
                detail=(
                    f"mapping status={m.status} — DRAFT 만 직접 수정 가능. "
                    "APPROVED/PUBLISHED 는 새 버전 생성 (Phase 7 backlog)."
                ),
            )
        m.contract_id = body.contract_id
        m.source_path = body.source_path
        m.target_table = body.target_table
        m.target_column = body.target_column
        m.transform_expr = body.transform_expr
        m.data_type = body.data_type
        m.is_required = body.is_required
        m.order_no = body.order_no
        s.flush()
        return FieldMappingOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{mapping_id}", status_code=204)
async def delete_mapping(mapping_id: int) -> Response:
    def _do(s: Session) -> None:
        m = s.get(FieldMapping, mapping_id)
        if m is None:
            raise HTTPException(404, detail=f"mapping {mapping_id} not found")
        if m.status == "PUBLISHED":
            raise HTTPException(
                409, detail="PUBLISHED mapping 은 삭제 불가 — DRAFT 로 transition 후"
            )
        s.delete(m)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


@router.post("/{mapping_id}/transition", response_model=FieldMappingOut)
async def transition_mapping(
    mapping_id: int, body: StatusTransitionRequest, user: CurrentUserDep
) -> FieldMappingOut:
    del user
    valid: dict[str, set[str]] = {
        "DRAFT": {"REVIEW"},
        "REVIEW": {"APPROVED", "DRAFT"},
        "APPROVED": {"PUBLISHED", "DRAFT"},
        "PUBLISHED": {"DRAFT"},
    }

    def _do(s: Session) -> FieldMappingOut:
        m = s.get(FieldMapping, mapping_id)
        if m is None:
            raise HTTPException(404, detail=f"mapping {mapping_id} not found")
        if body.target_status not in valid.get(m.status, set()):
            raise HTTPException(
                422,
                detail=(
                    f"transition {m.status}→{body.target_status} not allowed. "
                    f"valid: {sorted(valid.get(m.status, set()))}"
                ),
            )
        m.status = body.target_status
        s.flush()
        return FieldMappingOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


# ---------------------------------------------------------------------------
# Helpers — UI 도움말
# ---------------------------------------------------------------------------
@router.get("/sources/list", response_model=list[MappingSourceOut])
async def list_mapping_sources(
    domain_code: str | None = None,
    source_type: str | None = None,
) -> list[MappingSourceOut]:
    """Unified mapping source list for API Pull and Inbound contracts."""

    def _do(s: Session) -> list[MappingSourceOut]:
        out: list[MappingSourceOut] = []
        wanted = source_type or ""
        if wanted in ("", "api"):
            params: dict[str, Any] = {}
            where = ""
            if domain_code:
                where = "WHERE sc.domain_code = :domain_code"
                params["domain_code"] = domain_code
            rows = s.execute(
                text(
                    f"""
                    SELECT sc.contract_id, sc.domain_code, sc.resource_code,
                           sc.schema_version, sc.status, sc.schema_json,
                           ds.source_name
                      FROM domain.source_contract sc
                      JOIN ctl.data_source ds ON ds.source_id = sc.source_id
                      {where}
                     ORDER BY sc.domain_code, sc.resource_code, sc.schema_version DESC
                     LIMIT 200
                    """
                ),
                params,
            ).all()
            for r in rows:
                schema_json = r.schema_json or {}
                sample_rows = schema_json.get("sample_rows")
                sample_payload = {"items": sample_rows[:3]} if isinstance(sample_rows, list) and sample_rows else _sample_from_schema(schema_json)
                out.append(
                    MappingSourceOut(
                        source_type="api",
                        source_id=f"contract:{r.contract_id}",
                        contract_id=int(r.contract_id),
                        domain_code=str(r.domain_code),
                        resource_code=str(r.resource_code),
                        label=f"API #{r.contract_id} {r.source_name} / {r.resource_code} [{r.status}]",
                        status=str(r.status),
                        item_path="items" if isinstance(sample_rows, list) and sample_rows else None,
                        payload_schema=schema_json,
                        sample_payload=sample_payload,
                    )
                )
        if wanted in ("", "inbound"):
            params = {}
            where = ""
            if domain_code:
                where = "WHERE c.domain_code = :domain_code"
                params["domain_code"] = domain_code
            rows = s.execute(
                text(
                    f"""
                    SELECT c.channel_id, c.channel_code, c.domain_code, c.name,
                           c.channel_kind, c.status
                      FROM domain.inbound_channel c
                      {where}
                     ORDER BY c.channel_code
                    """
                ),
                params,
            ).all()
            for r in rows:
                contract = get_contract(s, str(r.channel_code)) or {}
                source_type_db = "OCR" if r.channel_kind == "OCR_RESULT" else "CRAWLER" if r.channel_kind == "CRAWLER_RESULT" else "APP"
                source_code = f"INBOUND_{str(r.channel_code).upper()}"[:64]
                source_id = s.execute(
                    text(
                        """
                        INSERT INTO ctl.data_source
                          (source_code, source_name, source_type, is_active, config_json)
                        VALUES
                          (:code, :name, :type, TRUE, CAST(:cfg AS JSONB))
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
                        "name": str(r.name),
                        "type": source_type_db,
                        "cfg": json.dumps({"channel_id": int(r.channel_id), "channel_code": str(r.channel_code), "channel_kind": str(r.channel_kind)}, ensure_ascii=False),
                    },
                ).scalar_one()
                schema_json = contract.get("payload_schema") or {}
                sample_payload = contract.get("sample_payload") or {}
                contract_id = s.execute(
                    text(
                        """
                        INSERT INTO domain.source_contract
                          (source_id, domain_code, resource_code, schema_version,
                           schema_json, compatibility_mode, resource_selector_json,
                           status, description)
                        VALUES
                          (:sid, :domain, :resource, 1, CAST(:schema AS JSONB),
                           'backward', CAST(:selector AS JSONB), 'PUBLISHED', :desc)
                        ON CONFLICT (source_id, domain_code, resource_code, schema_version)
                        DO UPDATE SET
                          schema_json = EXCLUDED.schema_json,
                          resource_selector_json = EXCLUDED.resource_selector_json,
                          status = 'PUBLISHED',
                          description = EXCLUDED.description,
                          updated_at = now()
                        RETURNING contract_id
                        """
                    ),
                    {
                        "sid": int(source_id),
                        "domain": str(r.domain_code),
                        "resource": str(r.channel_code),
                        "schema": json.dumps(schema_json, ensure_ascii=False),
                        "selector": json.dumps({"source_type": "inbound", "channel_code": str(r.channel_code), "item_path": contract.get("item_path")}, ensure_ascii=False),
                        "desc": f"Inbound contract for {r.channel_code}",
                    },
                ).scalar_one()
                out.append(
                    MappingSourceOut(
                        source_type="inbound",
                        source_id=f"inbound:{r.channel_id}",
                        contract_id=int(contract_id),
                        domain_code=str(r.domain_code),
                        resource_code=str(r.channel_code),
                        label=f"Inbound #{r.channel_id} {r.name} / {r.channel_kind} [{r.status}]",
                        status=str(r.status),
                        item_path=contract.get("item_path"),
                        payload_schema=schema_json,
                        sample_payload=sample_payload,
                    )
                )
        return out

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/functions/list", response_model=list[FunctionSpecOut])
async def list_function_registry() -> list[FunctionSpecOut]:
    """26+ 함수 allowlist — UI 의 transform_expr 입력 도움말."""

    def _do() -> list[FunctionSpecOut]:
        return [
            FunctionSpecOut(
                name=spec.name,
                category=spec.category,
                description=spec.description,
                arity_min=spec.arity_min,
                arity_max=spec.arity_max,
            )
            for spec in list_functions()
        ]

    return await asyncio.to_thread(_do)


class CatalogTableOut(BaseModel):
    schema_name: str
    table_name: str
    table_type: str  # 'BASE TABLE' | 'VIEW' | 'PARTITIONED TABLE'
    estimated_rows: int | None = None


@router.get("/catalog/tables", response_model=list[CatalogTableOut])
async def list_catalog_tables(
    schema: str | None = None,
) -> list[CatalogTableOut]:
    """Phase 8.6 — SQL Studio / Quality Workbench 테이블 카탈로그.

    공용 워크벤치 schema (wf/stg/<domain>_stg/<domain>_mart/mart/raw/run/audit) 만 노출.
    """
    import re

    if schema is not None and not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", schema):
        raise HTTPException(422, detail=f"invalid schema: {schema!r}")

    def _do(s: Session) -> list[CatalogTableOut]:
        params: dict[str, Any] = {}
        where = (
            "table_schema NOT IN ('pg_catalog','information_schema','pg_toast') "
            "AND table_schema NOT LIKE 'pg_temp%' "
            "AND table_schema NOT LIKE 'pg_toast_temp%'"
        )
        if schema:
            where += " AND table_schema = :schema"
            params["schema"] = schema
        rows = s.execute(
            text(
                f"""
                SELECT t.table_schema, t.table_name, t.table_type,
                       c.reltuples::bigint AS estimated_rows
                  FROM information_schema.tables t
                  LEFT JOIN pg_namespace n
                         ON n.nspname = t.table_schema
                  LEFT JOIN pg_class c
                         ON c.relname = t.table_name
                        AND c.relnamespace = n.oid
                 WHERE {where}
                 ORDER BY t.table_schema, t.table_name
                """
            ),
            params,
        ).all()
        return [
            CatalogTableOut(
                schema_name=str(r.table_schema),
                table_name=str(r.table_name),
                table_type=str(r.table_type),
                estimated_rows=int(r.estimated_rows)
                if r.estimated_rows is not None and r.estimated_rows > 0
                else None,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/columns/{schema}/{table}", response_model=list[TableColumnOut])
async def list_table_columns(schema: str, table: str) -> list[TableColumnOut]:
    """target table 의 컬럼 목록 — Mapping Designer 우측 panel."""
    import re

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", schema):
        raise HTTPException(422, detail=f"invalid schema: {schema!r}")
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", table):
        raise HTTPException(422, detail=f"invalid table: {table!r}")

    def _do(s: Session) -> list[TableColumnOut]:
        rows = s.execute(
            text(
                "SELECT column_name, data_type, is_nullable, ordinal_position "
                "FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t "
                "ORDER BY ordinal_position"
            ),
            {"s": schema, "t": table},
        ).all()
        if not rows:
            raise HTTPException(
                404, detail=f"table {schema}.{table} not found or has no columns"
            )
        return [
            TableColumnOut(
                column_name=str(r.column_name),
                data_type=str(r.data_type),
                is_nullable=(r.is_nullable == "YES"),
                ordinal_position=int(r.ordinal_position),
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/contracts/list-light", response_model=list[dict[str, Any]])
async def list_contracts_light(
    domain_code: str | None = None,
) -> list[dict[str, Any]]:
    """Mapping Designer dropdown 용 — contract_id + 도메인/리소스만."""

    def _do(s: Session) -> list[dict[str, Any]]:
        sql = (
            "SELECT contract_id, domain_code, resource_code, schema_version, status "
            "FROM domain.source_contract "
        )
        params: dict[str, Any] = {}
        if domain_code:
            sql += "WHERE domain_code = :d "
            params["d"] = domain_code
        sql += "ORDER BY domain_code, resource_code, schema_version DESC LIMIT 200"
        rows = s.execute(text(sql), params).all()
        return [
            {
                "contract_id": int(r.contract_id),
                "domain_code": str(r.domain_code),
                "resource_code": str(r.resource_code),
                "schema_version": int(r.schema_version),
                "status": str(r.status),
                "label": (
                    f"#{r.contract_id} {r.domain_code}/{r.resource_code} "
                    f"v{r.schema_version} [{r.status}]"
                ),
            }
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]


def _sample_from_schema(schema_json: dict[str, Any]) -> dict[str, Any]:
    props = schema_json.get("properties")
    if not isinstance(props, dict):
        return {}
    sample: dict[str, Any] = {}
    for key, spec in props.items():
        typ = spec.get("type") if isinstance(spec, dict) else None
        if typ in {"number", "integer"}:
            sample[key] = 0
        elif typ == "boolean":
            sample[key] = False
        elif typ == "array":
            sample[key] = []
        elif typ == "object":
            sample[key] = {}
        else:
            sample[key] = ""
    return sample
