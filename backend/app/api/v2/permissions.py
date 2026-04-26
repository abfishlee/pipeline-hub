"""HTTP — `/v2/permissions` (Phase 5.2.4 STEP 7 Q1).

user × domain 권한 매트릭스 CRUD. 전역 ADMIN 만 grant/revoke 가능.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.permissions import (
    DomainRole,
    grant_domain_role,
    list_user_domain_roles,
    revoke_domain_role,
)

router = APIRouter(
    prefix="/v2/permissions",
    tags=["v2-permissions"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


class DomainRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    domain_code: str
    role: str
    granted_by: int | None
    granted_at: datetime


class GrantRequest(BaseModel):
    user_id: int = Field(ge=1)
    domain_code: str
    role: DomainRole


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


@router.get("/domains/{user_id}", response_model=list[dict[str, str]])
async def list_user_roles(user_id: int) -> list[dict[str, str]]:
    """user 의 (domain_code, role) 목록. 전역 ADMIN 은 ('*', 'ADMIN') 추가."""

    def _do(s: Session) -> list[dict[str, str]]:
        rows = list_user_domain_roles(s, user_id=user_id)
        return [{"domain_code": d, "role": r} for d, r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/domain/{domain_code}", response_model=list[DomainRoleOut])
async def list_domain_grantees(domain_code: str) -> list[DomainRoleOut]:
    def _do(s: Session) -> list[DomainRoleOut]:
        rows = s.execute(
            text(
                "SELECT user_id, domain_code, role, granted_by, granted_at "
                "FROM ctl.user_domain_role "
                "WHERE domain_code = :dom ORDER BY user_id"
            ),
            {"dom": domain_code},
        ).all()
        return [
            DomainRoleOut(
                user_id=int(r.user_id),
                domain_code=str(r.domain_code),
                role=str(r.role),
                granted_by=int(r.granted_by) if r.granted_by else None,
                granted_at=r.granted_at,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/grant", status_code=204)
async def grant(body: GrantRequest, user: CurrentUserDep) -> Response:
    def _do(s: Session) -> None:
        ok = s.execute(
            text(
                "SELECT 1 FROM domain.domain_definition WHERE domain_code = :d"
            ),
            {"d": body.domain_code},
        ).first()
        if ok is None:
            raise HTTPException(
                status_code=404,
                detail=f"domain {body.domain_code!r} not found",
            )
        grant_domain_role(
            s,
            user_id=body.user_id,
            domain_code=body.domain_code,
            role=body.role,
            granted_by=user.user_id,
        )

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


@router.post("/revoke", status_code=204)
async def revoke(body: GrantRequest) -> Response:
    def _do(s: Session) -> None:
        revoke_domain_role(s, user_id=body.user_id, domain_code=body.domain_code)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


__all__ = ["router"]
