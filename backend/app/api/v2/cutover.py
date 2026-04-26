"""HTTP — `/v2/cutover` (Phase 5.2.5 STEP 8 Q2).

Cutover Flag CRUD + ADMIN 명시 승인 endpoint.

흐름 예시 (agri PRICE_FACT):
  1. POST /v2/cutover/start          — shadow 시작 (active='v1', v2_read=true)
  2. (1주 dual-active 운영, audit.shadow_diff 누적)
  3. GET  /v2/cutover/diff-report    — mismatch_ratio_1h 확인
  4. POST /v2/cutover/apply          — ADMIN 명시 승인 후 v2 전환 (Q4 가드)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.v1_to_v2 import (
    CutoverError,
    apply_cutover,
    get_cutover_flag,
    upsert_cutover_flag,
)

router = APIRouter(
    prefix="/v2/cutover",
    tags=["v2-cutover"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


class CutoverFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain_code: str
    resource_code: str
    active_path: str
    v2_read_enabled: bool
    v1_write_disabled: bool
    shadow_started_at: datetime | None
    cutover_at: datetime | None
    approved_by: int | None
    notes: str | None
    updated_at: datetime


class StartShadowRequest(BaseModel):
    domain_code: str
    resource_code: str
    notes: str | None = None


class ApplyCutoverRequest(BaseModel):
    domain_code: str
    resource_code: str
    target_path: str = Field(default="v2", pattern=r"^(v2|shadow)$")
    acknowledge_warning: bool = False
    notes: str | None = None
    window_hours: int = Field(default=1, ge=1, le=168)


class DiffReport(BaseModel):
    domain_code: str
    resource_code: str
    window_hours: int
    total_count: int
    mismatch_count: int
    mismatch_ratio: float
    by_kind: dict[str, int]


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


@router.get("", response_model=list[CutoverFlagOut])
async def list_flags(domain_code: str | None = None) -> list[CutoverFlagOut]:
    def _do(s: Session) -> list[CutoverFlagOut]:
        sql = (
            "SELECT domain_code, resource_code, active_path, v2_read_enabled, "
            "       v1_write_disabled, shadow_started_at, cutover_at, "
            "       approved_by, notes, updated_at "
            "FROM ctl.cutover_flag "
        )
        params: dict[str, Any] = {}
        if domain_code:
            sql += "WHERE domain_code = :d "
            params["d"] = domain_code
        sql += "ORDER BY domain_code, resource_code"
        rows = s.execute(text(sql), params).all()
        return [
            CutoverFlagOut(
                domain_code=str(r.domain_code),
                resource_code=str(r.resource_code),
                active_path=str(r.active_path),
                v2_read_enabled=bool(r.v2_read_enabled),
                v1_write_disabled=bool(r.v1_write_disabled),
                shadow_started_at=r.shadow_started_at,
                cutover_at=r.cutover_at,
                approved_by=int(r.approved_by) if r.approved_by else None,
                notes=str(r.notes) if r.notes else None,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/start", response_model=CutoverFlagOut)
async def start_shadow(body: StartShadowRequest) -> CutoverFlagOut:
    def _do(s: Session) -> CutoverFlagOut:
        upsert_cutover_flag(
            s,
            domain_code=body.domain_code,
            resource_code=body.resource_code,
            active_path="v1",
            v2_read_enabled=True,
            v1_write_disabled=False,
            notes=body.notes or "shadow start (v2-cutover-api)",
        )
        s.execute(
            text(
                "UPDATE ctl.cutover_flag SET "
                "  shadow_started_at = COALESCE(shadow_started_at, now()) "
                "WHERE domain_code = :d AND resource_code = :r"
            ),
            {"d": body.domain_code, "r": body.resource_code},
        )
        flag = get_cutover_flag(
            s,
            domain_code=body.domain_code,
            resource_code=body.resource_code,
        )
        assert flag is not None
        return CutoverFlagOut(
            domain_code=flag.domain_code,
            resource_code=flag.resource_code,
            active_path=flag.active_path,
            v2_read_enabled=flag.v2_read_enabled,
            v1_write_disabled=flag.v1_write_disabled,
            shadow_started_at=flag.shadow_started_at,
            cutover_at=flag.cutover_at,
            approved_by=flag.approved_by,
            notes=flag.notes,
            updated_at=flag.updated_at,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/apply", response_model=CutoverFlagOut)
async def apply(body: ApplyCutoverRequest, user: CurrentUserDep) -> CutoverFlagOut:
    def _do(s: Session) -> CutoverFlagOut:
        try:
            flag = apply_cutover(
                s,
                domain_code=body.domain_code,
                resource_code=body.resource_code,
                target_path=body.target_path,
                approver_user_id=user.user_id,
                acknowledge_warning=body.acknowledge_warning,
                notes=body.notes,
                window_hours=body.window_hours,
            )
        except CutoverError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return CutoverFlagOut(
            domain_code=flag.domain_code,
            resource_code=flag.resource_code,
            active_path=flag.active_path,
            v2_read_enabled=flag.v2_read_enabled,
            v1_write_disabled=flag.v1_write_disabled,
            shadow_started_at=flag.shadow_started_at,
            cutover_at=flag.cutover_at,
            approved_by=flag.approved_by,
            notes=flag.notes,
            updated_at=flag.updated_at,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/diff-report", response_model=DiffReport)
async def diff_report(
    domain_code: str, resource_code: str, window_hours: int = 1
) -> DiffReport:
    def _do(s: Session) -> DiffReport:
        rows = s.execute(
            text(
                "SELECT diff_kind, COUNT(*) AS c FROM audit.shadow_diff "
                "WHERE domain_code = :d AND resource_code = :r "
                "  AND occurred_at >= (now() - (:w || ' hours')::interval) "
                "GROUP BY diff_kind"
            ),
            {"d": domain_code, "r": resource_code, "w": window_hours},
        ).all()
        by_kind = {str(r.diff_kind): int(r.c) for r in rows}
        total = sum(by_kind.values())
        mismatch = sum(v for k, v in by_kind.items() if k != "identical_skipped")
        ratio = float(mismatch) / float(total) if total else 0.0
        return DiffReport(
            domain_code=domain_code,
            resource_code=resource_code,
            window_hours=window_hours,
            total_count=total,
            mismatch_count=mismatch,
            mismatch_ratio=ratio,
            by_kind=by_kind,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{domain_code}/{resource_code}", response_model=CutoverFlagOut)
async def get_flag(domain_code: str, resource_code: str) -> CutoverFlagOut:
    def _do(s: Session) -> CutoverFlagOut:
        flag = get_cutover_flag(
            s, domain_code=domain_code, resource_code=resource_code
        )
        if flag is None:
            raise HTTPException(
                status_code=404,
                detail=f"cutover_flag ({domain_code},{resource_code}) not found",
            )
        return CutoverFlagOut(
            domain_code=flag.domain_code,
            resource_code=flag.resource_code,
            active_path=flag.active_path,
            v2_read_enabled=flag.v2_read_enabled,
            v1_write_disabled=flag.v1_write_disabled,
            shadow_started_at=flag.shadow_started_at,
            cutover_at=flag.cutover_at,
            approved_by=flag.approved_by,
            notes=flag.notes,
            updated_at=flag.updated_at,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
