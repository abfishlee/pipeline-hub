"""HTTP — `/v1/security-events` (Phase 4.2.6, ADMIN 만)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.deps import SessionDep, require_roles
from app.models.audit import SecurityEvent

router = APIRouter(
    prefix="/v1/security-events",
    tags=["security"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


class SecurityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    kind: str
    severity: str
    api_key_id: int | None
    ip_addr: str | None
    user_agent: str | None
    details_json: dict[str, Any]
    occurred_at: datetime


@router.get("", response_model=list[SecurityEventOut])
async def list_security_events(
    session: SessionDep,
    kind: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    severity: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SecurityEventOut]:
    q = select(SecurityEvent).order_by(SecurityEvent.event_id.desc())
    if kind:
        q = q.where(SecurityEvent.kind == kind)
    if severity:
        q = q.where(SecurityEvent.severity == severity)
    q = q.limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    return [SecurityEventOut.model_validate(r) for r in rows]


__all__ = ["router"]
