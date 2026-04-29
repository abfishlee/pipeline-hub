"""HTTP API for reusable processing models.

The underlying table is still named ``sql_asset`` for migration compatibility,
but the product concept is now a model repository. Canvas can create SQL or
Python models; this endpoint lists them, handles approval state, and allows
operators to deactivate a model without deleting history.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.guardrails.sql_guard import (
    NodeKind,
    SqlGuardError,
    SqlNodeContext,
    guard_sql,
)
from app.models.domain import DomainDefinition, SqlAsset

router = APIRouter(
    prefix="/v2/sql-assets",
    tags=["v2-sql-assets"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)

SqlAssetType = Literal[
    "TRANSFORM_SQL",
    "STANDARDIZATION_SQL",
    "QUALITY_CHECK_SQL",
    "DML_SCRIPT",
    "FUNCTION",
    "PROCEDURE",
    "PYTHON_SCRIPT",
]

ModelCategory = Literal["TRANSFORM", "DQ", "STANDARDIZATION", "ENRICHMENT", "LOAD", "OTHER"]


class SqlAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: int
    asset_code: str
    domain_code: str
    version: int
    asset_type: str
    model_category: str
    is_active: bool
    sql_text: str
    checksum: str
    output_table: str | None
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SqlAssetIn(BaseModel):
    asset_code: str = Field(min_length=2, max_length=63, pattern=r"^[a-z][a-z0-9_]{1,62}$")
    domain_code: str = Field(min_length=1, max_length=64)
    asset_type: SqlAssetType = "TRANSFORM_SQL"
    model_category: ModelCategory = "TRANSFORM"
    sql_text: str = Field(min_length=1, max_length=200_000)
    output_table: str | None = None
    description: str | None = None
    version: int = Field(default=1, ge=1)


class SqlAssetUpdate(BaseModel):
    asset_type: SqlAssetType | None = None
    model_category: ModelCategory | None = None
    sql_text: str | None = Field(default=None, min_length=1, max_length=200_000)
    output_table: str | None = None
    description: str | None = None


class StatusTransitionRequest(BaseModel):
    target_status: str = Field(pattern=r"^(REVIEW|APPROVED|PUBLISHED|DRAFT)$")


class ActiveToggleRequest(BaseModel):
    is_active: bool


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


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _validate_script_asset(sql: str, asset_type: str) -> None:
    normalized = sql.strip()
    upper = normalized.upper()
    if asset_type == "PYTHON_SCRIPT":
        forbidden = (
            "import os",
            "import subprocess",
            "__import__",
            "open(",
            "eval(",
            "exec(",
            "compile(",
        )
        lowered = normalized.lower()
        if any(token in lowered for token in forbidden):
            raise HTTPException(
                422,
                detail="PYTHON_SCRIPT cannot use os/subprocess/import hooks/open/eval/exec",
            )
        return
    if asset_type == "FUNCTION":
        if not upper.startswith("CREATE OR REPLACE FUNCTION "):
            raise HTTPException(
                422,
                detail="FUNCTION asset must start with CREATE OR REPLACE FUNCTION",
            )
        return
    if asset_type == "PROCEDURE":
        if not upper.startswith("CREATE OR REPLACE PROCEDURE "):
            raise HTTPException(
                422,
                detail="PROCEDURE asset must start with CREATE OR REPLACE PROCEDURE",
            )
        return
    if asset_type == "DML_SCRIPT":
        forbidden = ("DROP ", "TRUNCATE ", "ALTER ", "CREATE EXTENSION", "GRANT ", "REVOKE ")
        if any(token in upper for token in forbidden):
            raise HTTPException(
                422,
                detail="DML_SCRIPT cannot contain DROP/TRUNCATE/ALTER/EXTENSION/GRANT/REVOKE",
            )
        if not upper.startswith(("INSERT ", "UPDATE ", "DELETE ", "WITH ")):
            raise HTTPException(
                422,
                detail="DML_SCRIPT must start with INSERT, UPDATE, DELETE, or WITH",
            )
        return


def _validate_sql(sql: str, domain_code: str, asset_type: str) -> None:
    if asset_type in {"DML_SCRIPT", "FUNCTION", "PROCEDURE", "PYTHON_SCRIPT"}:
        _validate_script_asset(sql, asset_type)
        return

    rendered = (
        sql.replace("{{input_table}}", f"{domain_code.lower()}_stg.__canvas_input")
        .replace("{{ output_table }}", "wf.__canvas_output")
        .replace("{{output_table}}", "wf.__canvas_output")
        .replace("{{run_id}}", "0")
        .replace("{{domain_code}}", domain_code)
        .replace("{{node_key}}", "sql_asset")
    )
    extra = frozenset({f"{domain_code.lower()}_stg", f"{domain_code.lower()}_mart"})
    ctx = SqlNodeContext(
        node_kind=NodeKind.DQ_CHECK
        if asset_type == "QUALITY_CHECK_SQL"
        else NodeKind.SQL_ASSET_TRANSFORM,
        domain_code=domain_code,
        allowed_extra_schemas=extra,
    )
    try:
        guard_sql(rendered, ctx=ctx)
    except SqlGuardError as exc:
        raise HTTPException(422, detail=f"SQL guard violation: {exc}") from exc


@router.get("", response_model=list[SqlAssetOut])
async def list_sql_assets(
    domain_code: str | None = None,
    status: str | None = None,
    asset_code: str | None = None,
    asset_type: str | None = None,
    model_category: str | None = None,
    is_active: bool | None = None,
) -> list[SqlAssetOut]:
    def _do(s: Session) -> list[SqlAssetOut]:
        q = select(SqlAsset).order_by(
            SqlAsset.domain_code,
            SqlAsset.asset_type,
            SqlAsset.asset_code,
            SqlAsset.version.desc(),
        )
        if domain_code:
            q = q.where(SqlAsset.domain_code == domain_code)
        if status:
            q = q.where(SqlAsset.status == status)
        if asset_code:
            q = q.where(SqlAsset.asset_code == asset_code)
        if asset_type:
            q = q.where(SqlAsset.asset_type == asset_type)
        if model_category:
            q = q.where(SqlAsset.model_category == model_category)
        if is_active is not None:
            q = q.where(SqlAsset.is_active == is_active)
        rows = s.execute(q).scalars().all()
        return [SqlAssetOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{asset_id}", response_model=SqlAssetOut)
async def get_sql_asset(asset_id: int) -> SqlAssetOut:
    def _do(s: Session) -> SqlAssetOut:
        asset = s.get(SqlAsset, asset_id)
        if asset is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        return SqlAssetOut.model_validate(asset)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=SqlAssetOut, status_code=201)
async def create_sql_asset(body: SqlAssetIn, user: CurrentUserDep) -> SqlAssetOut:
    _validate_sql(body.sql_text, body.domain_code, body.asset_type)

    def _do(s: Session) -> SqlAssetOut:
        if s.get(DomainDefinition, body.domain_code) is None:
            raise HTTPException(404, detail=f"domain {body.domain_code} not found")
        dup = s.execute(
            select(SqlAsset).where(
                SqlAsset.asset_code == body.asset_code,
                SqlAsset.version == body.version,
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                409,
                detail=(
                    f"sql_asset {body.asset_code} v{body.version} already exists "
                    f"(asset_id={dup.asset_id}). Use a new version."
                ),
            )
        asset = SqlAsset(
            asset_code=body.asset_code,
            domain_code=body.domain_code,
            version=body.version,
            asset_type=body.asset_type,
            model_category=body.model_category,
            is_active=True,
            sql_text=body.sql_text,
            checksum=_checksum(body.sql_text),
            output_table=body.output_table,
            description=body.description,
            status="DRAFT",
            created_by=user.user_id,
        )
        s.add(asset)
        s.flush()
        return SqlAssetOut.model_validate(asset)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{asset_id}", response_model=SqlAssetOut)
async def update_sql_asset(
    asset_id: int, body: SqlAssetUpdate, user: CurrentUserDep
) -> SqlAssetOut:
    del user

    def _do(s: Session) -> SqlAssetOut:
        asset = s.get(SqlAsset, asset_id)
        if asset is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        if asset.status != "DRAFT":
            raise HTTPException(
                409,
                detail=(
                    f"sql_asset status={asset.status}; only DRAFT can be edited. "
                    "Create a new version for approved/published SQL."
                ),
            )
        next_type = body.asset_type or asset.asset_type
        next_sql = body.sql_text if body.sql_text is not None else asset.sql_text
        _validate_sql(next_sql, asset.domain_code, next_type)
        if body.asset_type is not None:
            asset.asset_type = body.asset_type
        if body.model_category is not None:
            asset.model_category = body.model_category
        if body.sql_text is not None:
            asset.sql_text = body.sql_text
            asset.checksum = _checksum(body.sql_text)
        if body.output_table is not None:
            asset.output_table = body.output_table or None
        if body.description is not None:
            asset.description = body.description or None
        s.flush()
        return SqlAssetOut.model_validate(asset)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{asset_id}", status_code=204)
async def delete_sql_asset(asset_id: int) -> Response:
    def _do(s: Session) -> None:
        asset = s.get(SqlAsset, asset_id)
        if asset is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        if asset.status == "PUBLISHED":
            raise HTTPException(
                409,
                detail="PUBLISHED sql_asset cannot be deleted. Move it to DRAFT first.",
            )
        s.delete(asset)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


@router.post("/{asset_id}/active", response_model=SqlAssetOut)
async def set_sql_asset_active(asset_id: int, body: ActiveToggleRequest) -> SqlAssetOut:
    def _do(s: Session) -> SqlAssetOut:
        asset = s.get(SqlAsset, asset_id)
        if asset is None:
            raise HTTPException(404, detail=f"model {asset_id} not found")
        asset.is_active = body.is_active
        s.flush()
        return SqlAssetOut.model_validate(asset)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/{asset_id}/transition", response_model=SqlAssetOut)
async def transition_sql_asset(
    asset_id: int, body: StatusTransitionRequest, user: CurrentUserDep
) -> SqlAssetOut:
    valid: dict[str, set[str]] = {
        "DRAFT": {"REVIEW"},
        "REVIEW": {"APPROVED", "DRAFT"},
        "APPROVED": {"PUBLISHED", "DRAFT"},
        "PUBLISHED": {"DRAFT"},
    }

    def _do(s: Session) -> SqlAssetOut:
        asset = s.get(SqlAsset, asset_id)
        if asset is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        if body.target_status not in valid.get(asset.status, set()):
            raise HTTPException(
                422,
                detail=(
                    f"transition {asset.status}->{body.target_status} not allowed. "
                    f"valid: {sorted(valid.get(asset.status, set()))}"
                ),
            )
        if body.target_status in ("APPROVED", "PUBLISHED"):
            _validate_sql(asset.sql_text, asset.domain_code, asset.asset_type)
        if body.target_status == "APPROVED":
            asset.approved_by = user.user_id
        asset.status = body.target_status
        s.flush()
        return SqlAssetOut.model_validate(asset)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
