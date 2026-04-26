"""HTTP — `/v2/providers` (Phase 5.2.1, 최소 CRUD).

provider_definition 의 list/get. binding 관리는 5.2.1.1 에서 확장.
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
from app.models.domain import ProviderDefinition

router = APIRouter(
    prefix="/v2/providers",
    tags=["v2-providers"],
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN"))],
)


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_code: str
    provider_kind: str
    implementation_type: str
    config_schema: dict[str, Any]
    description: str | None
    is_active: bool
    created_at: datetime


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


@router.get("", response_model=list[ProviderOut])
async def list_providers(provider_kind: str | None = None) -> list[ProviderOut]:
    def _do(s: Session) -> list[ProviderOut]:
        q = select(ProviderDefinition).order_by(ProviderDefinition.provider_code)
        if provider_kind:
            q = q.where(ProviderDefinition.provider_kind == provider_kind)
        rows = s.execute(q).scalars().all()
        return [ProviderOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
