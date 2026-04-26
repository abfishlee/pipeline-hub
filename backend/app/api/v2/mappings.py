"""HTTP — `/v2/mappings` (Phase 5.2.1, 최소 CRUD).

field_mapping 의 list/get/create. validation 은 5.2.4 ETL UX MVP 에서 본격.
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
from app.models.domain import FieldMapping

router = APIRouter(
    prefix="/v2/mappings",
    tags=["v2-mappings"],
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN"))],
)


class FieldMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mapping_id: int
    contract_id: int
    source_path: str
    target_table: str
    target_column: str
    transform_expr: str | None
    data_type: str | None
    is_required: bool
    order_no: int
    status: str
    created_at: datetime
    updated_at: datetime


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


@router.get("", response_model=list[FieldMappingOut])
async def list_mappings(contract_id: int | None = None) -> list[FieldMappingOut]:
    def _do(s: Session) -> list[FieldMappingOut]:
        q = select(FieldMapping).order_by(FieldMapping.contract_id, FieldMapping.order_no)
        if contract_id is not None:
            q = q.where(FieldMapping.contract_id == contract_id)
        rows = s.execute(q).scalars().all()
        return [FieldMappingOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
