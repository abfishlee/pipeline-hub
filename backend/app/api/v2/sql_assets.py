"""HTTP — `/v2/sql-assets` (Phase 6 Wave 2B — Transform Designer SQL Asset 탭).

SQL_ASSET_TRANSFORM 노드의 backing entity (`domain.sql_asset`) CRUD + transition.

자산 정책 (사용자 § 13.4): DRAFT 만 직접 수정. APPROVED/PUBLISHED 는 새 버전.
SQL 본문은 저장 시 `sql_guard` (NodeKind.SQL_ASSET_TRANSFORM) 통과 필수.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any

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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SqlAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: int
    asset_code: str
    domain_code: str
    version: int
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
    sql_text: str = Field(min_length=1, max_length=200_000)
    output_table: str | None = None
    description: str | None = None
    version: int = Field(default=1, ge=1)


class SqlAssetUpdate(BaseModel):
    sql_text: str | None = Field(default=None, min_length=1, max_length=200_000)
    output_table: str | None = None
    description: str | None = None


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


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _validate_sql(sql: str, domain_code: str) -> None:
    """sql_guard SQL_ASSET_TRANSFORM 컨텍스트로 검증. 실패 시 422."""
    extra = frozenset(
        {f"{domain_code.lower()}_stg", f"{domain_code.lower()}_mart"}
    )
    ctx = SqlNodeContext(
        node_kind=NodeKind.SQL_ASSET_TRANSFORM,
        domain_code=domain_code,
        allowed_extra_schemas=extra,
    )
    try:
        guard_sql(sql, ctx=ctx)
    except SqlGuardError as exc:
        raise HTTPException(422, detail=f"SQL guard 위반: {exc}") from exc


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[SqlAssetOut])
async def list_sql_assets(
    domain_code: str | None = None,
    status: str | None = None,
    asset_code: str | None = None,
) -> list[SqlAssetOut]:
    def _do(s: Session) -> list[SqlAssetOut]:
        q = select(SqlAsset).order_by(
            SqlAsset.domain_code, SqlAsset.asset_code, SqlAsset.version.desc()
        )
        if domain_code:
            q = q.where(SqlAsset.domain_code == domain_code)
        if status:
            q = q.where(SqlAsset.status == status)
        if asset_code:
            q = q.where(SqlAsset.asset_code == asset_code)
        rows = s.execute(q).scalars().all()
        return [SqlAssetOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{asset_id}", response_model=SqlAssetOut)
async def get_sql_asset(asset_id: int) -> SqlAssetOut:
    def _do(s: Session) -> SqlAssetOut:
        m = s.get(SqlAsset, asset_id)
        if m is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        return SqlAssetOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=SqlAssetOut, status_code=201)
async def create_sql_asset(body: SqlAssetIn, user: CurrentUserDep) -> SqlAssetOut:
    _validate_sql(body.sql_text, body.domain_code)

    def _do(s: Session) -> SqlAssetOut:
        if s.get(DomainDefinition, body.domain_code) is None:
            raise HTTPException(404, detail=f"domain {body.domain_code} not found")
        # 동일 (asset_code, version) 충돌 방지.
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
                    f"sql_asset {body.asset_code} v{body.version} 이미 존재 "
                    f"(asset_id={dup.asset_id}). 새 version 으로 등록."
                ),
            )
        m = SqlAsset(
            asset_code=body.asset_code,
            domain_code=body.domain_code,
            version=body.version,
            sql_text=body.sql_text,
            checksum=_checksum(body.sql_text),
            output_table=body.output_table,
            description=body.description,
            status="DRAFT",
            created_by=user.user_id,
        )
        s.add(m)
        s.flush()
        return SqlAssetOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{asset_id}", response_model=SqlAssetOut)
async def update_sql_asset(
    asset_id: int, body: SqlAssetUpdate, user: CurrentUserDep
) -> SqlAssetOut:
    del user

    def _do(s: Session) -> SqlAssetOut:
        m = s.get(SqlAsset, asset_id)
        if m is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        if m.status != "DRAFT":
            raise HTTPException(
                409,
                detail=(
                    f"sql_asset status={m.status} — DRAFT 만 직접 수정 가능. "
                    "APPROVED/PUBLISHED 는 새 version 으로 등록."
                ),
            )
        if body.sql_text is not None:
            _validate_sql(body.sql_text, m.domain_code)
            m.sql_text = body.sql_text
            m.checksum = _checksum(body.sql_text)
        if body.output_table is not None:
            m.output_table = body.output_table or None
        if body.description is not None:
            m.description = body.description or None
        s.flush()
        return SqlAssetOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{asset_id}", status_code=204)
async def delete_sql_asset(asset_id: int) -> Response:
    def _do(s: Session) -> None:
        m = s.get(SqlAsset, asset_id)
        if m is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        if m.status == "PUBLISHED":
            raise HTTPException(
                409, detail="PUBLISHED sql_asset 은 삭제 불가 — DRAFT 로 transition 후"
            )
        s.delete(m)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


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
        m = s.get(SqlAsset, asset_id)
        if m is None:
            raise HTTPException(404, detail=f"sql_asset {asset_id} not found")
        if body.target_status not in valid.get(m.status, set()):
            raise HTTPException(
                422,
                detail=(
                    f"transition {m.status}→{body.target_status} not allowed. "
                    f"valid: {sorted(valid.get(m.status, set()))}"
                ),
            )
        # APPROVED 시 본문 재검증 (저장 후 sql_guard 정책이 강화될 수 있으므로).
        if body.target_status in ("APPROVED", "PUBLISHED"):
            _validate_sql(m.sql_text, m.domain_code)
        if body.target_status == "APPROVED":
            m.approved_by = user.user_id
        m.status = body.target_status
        s.flush()
        return SqlAssetOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
