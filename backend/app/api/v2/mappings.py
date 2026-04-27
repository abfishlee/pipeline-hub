"""HTTP — `/v2/mappings` (Phase 6 Wave 2A — Field Mapping workbench backend).

Phase 5 의 list-only 에서 CRUD + dry-run + helper endpoints 로 확장.
Field Mapping Designer 가 사용. Workbench 가 자산 (mapping) 을 row 단위로 관리.

자산 정책 (사용자 § 13.4):
  DRAFT 만 직접 수정. APPROVED/PUBLISHED 는 새 버전 생성 (Phase 7 backlog).
"""

from __future__ import annotations

import asyncio
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
                  LEFT JOIN pg_class c
                         ON c.relname = t.table_name
                  LEFT JOIN pg_namespace n
                         ON n.oid = c.relnamespace AND n.nspname = t.table_schema
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

    return await asyncio.to_thread(_do)


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
