"""HTTP — `/v2/load-policies` (Phase 6 Wave 3 — Mart Workbench LoadPolicy 탭).

`domain.load_policy` CRUD + transition.

자산 정책 (사용자 § 13.4): DRAFT 만 직접 수정. APPROVED/PUBLISHED 는 새 version.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.models.domain import LoadPolicy, ResourceDefinition

router = APIRouter(
    prefix="/v2/load-policies",
    tags=["v2-load-policies"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class LoadPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    policy_id: int
    resource_id: int
    mode: str
    key_columns: list[str]
    partition_expr: str | None
    scd_options_json: dict[str, Any]
    chunk_size: int
    statement_timeout_ms: int
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class LoadPolicyIn(BaseModel):
    resource_id: int = Field(ge=1)
    mode: str = Field(pattern=r"^(append_only|upsert|scd_type_2|current_snapshot)$")
    key_columns: list[str] = Field(default_factory=list)
    partition_expr: str | None = None
    scd_options_json: dict[str, Any] = Field(default_factory=dict)
    chunk_size: int = Field(default=1000, ge=1, le=100_000)
    statement_timeout_ms: int = Field(default=60_000, ge=100, le=600_000)
    version: int = Field(default=1, ge=1)


class LoadPolicyUpdate(BaseModel):
    mode: str | None = Field(
        default=None, pattern=r"^(append_only|upsert|scd_type_2|current_snapshot)$"
    )
    key_columns: list[str] | None = None
    partition_expr: str | None = None
    scd_options_json: dict[str, Any] | None = None
    chunk_size: int | None = Field(default=None, ge=1, le=100_000)
    statement_timeout_ms: int | None = Field(default=None, ge=100, le=600_000)


class StatusTransitionRequest(BaseModel):
    target_status: str = Field(pattern=r"^(REVIEW|APPROVED|PUBLISHED|DRAFT)$")


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


def _validate_mode_keys(mode: str, key_columns: list[str]) -> None:
    """mode 별 key_columns 요구사항 검증."""
    if mode in ("upsert", "scd_type_2", "current_snapshot") and not key_columns:
        raise HTTPException(
            422,
            detail=f"mode={mode} 은 key_columns 가 1개 이상 필요합니다.",
        )
    if mode == "append_only" and key_columns:
        # append_only 는 key_columns 무시 — 경고는 클라이언트 책임. 여기선 그냥 통과.
        pass


@router.get("", response_model=list[LoadPolicyOut])
async def list_load_policies(
    resource_id: int | None = None,
    status: str | None = None,
    mode: str | None = None,
) -> list[LoadPolicyOut]:
    def _do(s: Session) -> list[LoadPolicyOut]:
        q = select(LoadPolicy).order_by(
            LoadPolicy.resource_id, LoadPolicy.version.desc()
        )
        if resource_id is not None:
            q = q.where(LoadPolicy.resource_id == resource_id)
        if status:
            q = q.where(LoadPolicy.status == status)
        if mode:
            q = q.where(LoadPolicy.mode == mode)
        rows = s.execute(q).scalars().all()
        return [LoadPolicyOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{policy_id}", response_model=LoadPolicyOut)
async def get_load_policy(policy_id: int) -> LoadPolicyOut:
    def _do(s: Session) -> LoadPolicyOut:
        m = s.get(LoadPolicy, policy_id)
        if m is None:
            raise HTTPException(404, detail=f"load_policy {policy_id} not found")
        return LoadPolicyOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=LoadPolicyOut, status_code=201)
async def create_load_policy(body: LoadPolicyIn, user: CurrentUserDep) -> LoadPolicyOut:
    del user
    _validate_mode_keys(body.mode, body.key_columns)

    def _do(s: Session) -> LoadPolicyOut:
        if s.get(ResourceDefinition, body.resource_id) is None:
            raise HTTPException(404, detail=f"resource {body.resource_id} not found")
        # 동일 (resource_id, version) 중복 방지.
        dup = s.execute(
            select(LoadPolicy).where(
                LoadPolicy.resource_id == body.resource_id,
                LoadPolicy.version == body.version,
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                409,
                detail=(
                    f"load_policy resource={body.resource_id} v{body.version} 이미 존재 "
                    f"(policy_id={dup.policy_id}). 새 version 으로 등록."
                ),
            )
        m = LoadPolicy(
            resource_id=body.resource_id,
            mode=body.mode,
            key_columns=body.key_columns,
            partition_expr=body.partition_expr,
            scd_options_json=body.scd_options_json,
            chunk_size=body.chunk_size,
            statement_timeout_ms=body.statement_timeout_ms,
            version=body.version,
            status="DRAFT",
        )
        s.add(m)
        s.flush()
        return LoadPolicyOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{policy_id}", response_model=LoadPolicyOut)
async def update_load_policy(
    policy_id: int, body: LoadPolicyUpdate, user: CurrentUserDep
) -> LoadPolicyOut:
    del user

    def _do(s: Session) -> LoadPolicyOut:
        m = s.get(LoadPolicy, policy_id)
        if m is None:
            raise HTTPException(404, detail=f"load_policy {policy_id} not found")
        if m.status != "DRAFT":
            raise HTTPException(
                409,
                detail=(
                    f"load_policy status={m.status} — DRAFT 만 직접 수정 가능. "
                    "APPROVED/PUBLISHED 는 새 version 으로 등록."
                ),
            )
        if body.mode is not None:
            m.mode = body.mode
        if body.key_columns is not None:
            m.key_columns = body.key_columns
        if body.partition_expr is not None:
            m.partition_expr = body.partition_expr or None
        if body.scd_options_json is not None:
            m.scd_options_json = body.scd_options_json
        if body.chunk_size is not None:
            m.chunk_size = body.chunk_size
        if body.statement_timeout_ms is not None:
            m.statement_timeout_ms = body.statement_timeout_ms
        _validate_mode_keys(m.mode, m.key_columns or [])
        s.flush()
        return LoadPolicyOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{policy_id}", status_code=204)
async def delete_load_policy(policy_id: int) -> Response:
    def _do(s: Session) -> None:
        m = s.get(LoadPolicy, policy_id)
        if m is None:
            raise HTTPException(404, detail=f"load_policy {policy_id} not found")
        if m.status == "PUBLISHED":
            raise HTTPException(
                409,
                detail="PUBLISHED load_policy 는 삭제 불가 — DRAFT 로 transition 후",
            )
        s.delete(m)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


@router.post("/{policy_id}/transition", response_model=LoadPolicyOut)
async def transition_load_policy(
    policy_id: int, body: StatusTransitionRequest, user: CurrentUserDep
) -> LoadPolicyOut:
    del user
    valid: dict[str, set[str]] = {
        "DRAFT": {"REVIEW"},
        "REVIEW": {"APPROVED", "DRAFT"},
        "APPROVED": {"PUBLISHED", "DRAFT"},
        "PUBLISHED": {"DRAFT"},
    }

    def _do(s: Session) -> LoadPolicyOut:
        m = s.get(LoadPolicy, policy_id)
        if m is None:
            raise HTTPException(404, detail=f"load_policy {policy_id} not found")
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
        return LoadPolicyOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
