"""HTTP — `/v2/mart-drafts` (Phase 6 Wave 3 — Mart Workbench).

`domain.mart_design_draft` list/get/transition + helper (resources).

작성/저장은 [`/v2/dryrun/mart-designer`](dryrun.py) 가 담당 (DDL 생성 + DRAFT 저장).
본 라우트는 *목록 / 상태머신 / 삭제* 만 제공.
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
from app.models.domain import MartDesignDraft

router = APIRouter(
    prefix="/v2/mart-drafts",
    tags=["v2-mart-drafts"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class MartDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft_id: int
    domain_code: str
    target_table: str
    ddl_text: str
    diff_summary: dict[str, Any]
    status: str
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StatusTransitionRequest(BaseModel):
    target_status: str = Field(
        pattern=r"^(REVIEW|APPROVED|PUBLISHED|DRAFT|ROLLED_BACK)$"
    )


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


@router.get("", response_model=list[MartDraftOut])
async def list_mart_drafts(
    domain_code: str | None = None,
    status: str | None = None,
    target_table: str | None = None,
) -> list[MartDraftOut]:
    def _do(s: Session) -> list[MartDraftOut]:
        q = select(MartDesignDraft).order_by(MartDesignDraft.draft_id.desc())
        if domain_code:
            q = q.where(MartDesignDraft.domain_code == domain_code)
        if status:
            q = q.where(MartDesignDraft.status == status)
        if target_table:
            q = q.where(MartDesignDraft.target_table == target_table)
        rows = s.execute(q).scalars().all()
        return [MartDraftOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{draft_id}", response_model=MartDraftOut)
async def get_mart_draft(draft_id: int) -> MartDraftOut:
    def _do(s: Session) -> MartDraftOut:
        m = s.get(MartDesignDraft, draft_id)
        if m is None:
            raise HTTPException(404, detail=f"mart_draft {draft_id} not found")
        return MartDraftOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{draft_id}", status_code=204)
async def delete_mart_draft(draft_id: int) -> Response:
    def _do(s: Session) -> None:
        m = s.get(MartDesignDraft, draft_id)
        if m is None:
            raise HTTPException(404, detail=f"mart_draft {draft_id} not found")
        if m.status == "PUBLISHED":
            raise HTTPException(
                409,
                detail="PUBLISHED mart_draft 은 삭제 불가 — DRAFT 로 transition 후",
            )
        s.delete(m)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


@router.post("/{draft_id}/transition", response_model=MartDraftOut)
async def transition_mart_draft(
    draft_id: int, body: StatusTransitionRequest, user: CurrentUserDep
) -> MartDraftOut:
    valid: dict[str, set[str]] = {
        "DRAFT": {"REVIEW"},
        "REVIEW": {"APPROVED", "DRAFT"},
        "APPROVED": {"PUBLISHED", "DRAFT"},
        "PUBLISHED": {"DRAFT", "ROLLED_BACK"},
        "ROLLED_BACK": {"DRAFT"},
    }

    def _do(s: Session) -> MartDraftOut:
        m = s.get(MartDesignDraft, draft_id)
        if m is None:
            raise HTTPException(404, detail=f"mart_draft {draft_id} not found")
        if body.target_status not in valid.get(m.status, set()):
            raise HTTPException(
                422,
                detail=(
                    f"transition {m.status}→{body.target_status} not allowed. "
                    f"valid: {sorted(valid.get(m.status, set()))}"
                ),
            )
        if body.target_status == "APPROVED":
            m.approved_by = user.user_id
        m.status = body.target_status
        s.flush()
        return MartDraftOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
