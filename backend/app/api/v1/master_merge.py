"""HTTP — `/v1/admin/master-merge` (Phase 4.2.8, ADMIN/APPROVER).

운영자가 머지 후보를 조회 + 자동 머지 실행 + un-merge.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.master_merge import (
    find_merge_candidates,
    run_daily_auto_merge,
    unmerge_op,
)
from app.models.mart import MasterMergeOp

router = APIRouter(
    prefix="/v1/admin/master-merge",
    tags=["master-merge"],
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)


class MergeCandidateOut(BaseModel):
    std_code: str
    cluster_size: int
    products: list[dict[str, Any]]


class MergeOpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merge_op_id: int
    source_product_ids: list[int]
    target_product_id: int
    merged_at: datetime
    merged_by: int | None
    reason: str | None
    is_unmerged: bool
    unmerged_at: datetime | None
    unmerged_by: int | None
    mapping_count: int | None


class RunSummary(BaseModel):
    candidates: int
    merged: int
    disputed: int


class UnmergeResponse(BaseModel):
    merge_op_id: int
    new_product_ids: list[int]


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


@router.get("/candidates", response_model=list[MergeCandidateOut])
async def list_candidates(
    std_code: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> list[MergeCandidateOut]:
    def _do(s: Session) -> list[MergeCandidateOut]:
        cs = find_merge_candidates(s, std_code=std_code)
        return [
            MergeCandidateOut(
                std_code=c.std_code,
                cluster_size=len(c.products),
                products=[
                    {
                        "product_id": p.product_id,
                        "canonical_name": p.canonical_name,
                        "grade": p.grade,
                        "package_type": p.package_type,
                        "sale_unit_norm": p.sale_unit_norm,
                        "weight_g": float(p.weight_g) if p.weight_g else None,
                        "confidence_score": float(p.confidence_score)
                        if p.confidence_score
                        else None,
                    }
                    for p in c.products
                ],
            )
            for c in cs
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/run", response_model=RunSummary)
async def run_auto_merge(
    user: CurrentUserDep,
    std_code: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> RunSummary:
    """매일 03:00 cron 진입점과 동일한 로직 — 운영자가 즉시 실행 가능."""

    def _do(s: Session) -> RunSummary:
        out = run_daily_auto_merge(s, std_code=std_code, merged_by=user.user_id)
        return RunSummary(**out)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/ops", response_model=list[MergeOpOut])
async def list_ops(
    only_active: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MergeOpOut]:
    def _do(s: Session) -> list[MergeOpOut]:
        q = select(MasterMergeOp)
        if only_active:
            q = q.where(MasterMergeOp.is_unmerged.is_(False))
        q = q.order_by(MasterMergeOp.merge_op_id.desc()).limit(limit)
        rows = s.execute(q).scalars().all()
        return [MergeOpOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/ops/{merge_op_id}/unmerge", response_model=UnmergeResponse)
async def unmerge(
    merge_op_id: int, user: CurrentUserDep
) -> UnmergeResponse:
    def _do(s: Session) -> UnmergeResponse:
        try:
            res = unmerge_op(s, merge_op_id=merge_op_id, unmerged_by=user.user_id)
        except ValueError as exc:
            raise app_errors.ValidationError(str(exc)) from exc
        return UnmergeResponse(
            merge_op_id=res.merge_op_id, new_product_ids=res.new_product_ids
        )

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]


_ = text  # 미사용 경고 회피.
