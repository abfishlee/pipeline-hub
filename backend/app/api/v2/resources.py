"""HTTP — `/v2/resources` (Phase 6 Wave 3 — Mart Workbench resource dropdown).

`domain.resource_definition` list-light. Mart Designer / Load Policy Designer 의
dropdown 보조용 (CRUD 는 Phase 5 wizard 가 담당).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles
from app.models.domain import ResourceDefinition

router = APIRouter(
    prefix="/v2/resources",
    tags=["v2-resources"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class ResourceLight(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    domain_code: str
    resource_code: str
    canonical_table: str | None
    fact_table: str | None
    standard_code_namespace: str | None
    status: str
    version: int
    created_at: datetime


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        return fn(session)


@router.get("", response_model=list[ResourceLight])
async def list_resources(
    domain_code: str | None = None,
    status: str | None = None,
) -> list[ResourceLight]:
    """resource_definition 목록 — Mart Designer 의 dropdown 등에서 사용."""

    def _do(s: Session) -> list[ResourceLight]:
        q = select(ResourceDefinition).order_by(
            ResourceDefinition.domain_code,
            ResourceDefinition.resource_code,
            ResourceDefinition.version.desc(),
        )
        if domain_code:
            q = q.where(ResourceDefinition.domain_code == domain_code)
        if status:
            q = q.where(ResourceDefinition.status == status)
        rows = s.execute(q).scalars().all()
        return [ResourceLight.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
