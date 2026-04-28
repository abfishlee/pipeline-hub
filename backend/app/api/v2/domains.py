"""HTTP — `/v2/domains` (Phase 5.2.1, ADMIN/DOMAIN_ADMIN).

도메인 등록/조회. yaml 업로드는 별도 endpoint (load).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles
from app.domain.registry.loader import load_domain_from_dict
from app.models.domain import DomainDefinition, ResourceDefinition

router = APIRouter(
    prefix="/v2/domains",
    tags=["v2-domains"],
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN"))],
)


class DomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain_code: str
    name: str
    description: str | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    domain_code: str
    resource_code: str
    canonical_table: str | None
    fact_table: str | None
    standard_code_namespace: str | None
    embedding_model: str | None
    embedding_dim: int | None
    status: str
    version: int


class DomainLoadRequest(BaseModel):
    """yaml 또는 dict 형태의 domain 정의 업로드."""

    spec: dict[str, Any]


class DomainCreateRequest(BaseModel):
    domain_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,30}$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class DomainLoadResponse(BaseModel):
    domain_code: str
    resource_codes: list[str]
    namespace_names: list[str]


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


@router.get("", response_model=list[DomainOut])
async def list_domains() -> list[DomainOut]:
    def _do(s: Session) -> list[DomainOut]:
        rows = s.execute(
            select(DomainDefinition).order_by(DomainDefinition.domain_code)
        ).scalars().all()
        return [DomainOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=DomainOut, status_code=201)
async def create_domain(body: DomainCreateRequest) -> DomainOut:
    """Source/API 실증 흐름용 최소 도메인 생성."""

    def _do(s: Session) -> DomainOut:
        existing = s.get(DomainDefinition, body.domain_code)
        if existing is not None:
            existing.name = body.name
            existing.description = body.description
            existing.status = "PUBLISHED"
            s.flush()
            return DomainOut.model_validate(existing)
        row = DomainDefinition(
            domain_code=body.domain_code,
            name=body.name,
            description=body.description,
            schema_yaml={},
            status="PUBLISHED",
        )
        s.add(row)
        s.flush()
        return DomainOut.model_validate(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{domain_code}", response_model=DomainOut)
async def get_domain(domain_code: str) -> DomainOut:
    def _do(s: Session) -> DomainOut:
        row = s.get(DomainDefinition, domain_code)
        if row is None:
            raise app_errors.NotFoundError(f"domain {domain_code} not found")
        return DomainOut.model_validate(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{domain_code}/resources", response_model=list[ResourceOut])
async def list_resources(domain_code: str) -> list[ResourceOut]:
    def _do(s: Session) -> list[ResourceOut]:
        rows = s.execute(
            select(ResourceDefinition)
            .where(ResourceDefinition.domain_code == domain_code)
            .order_by(ResourceDefinition.resource_code, ResourceDefinition.version.desc())
        ).scalars().all()
        return [ResourceOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/load", response_model=DomainLoadResponse, status_code=201)
async def load_domain(body: DomainLoadRequest) -> DomainLoadResponse:
    """yaml/dict 의 domain 정의를 domain.* 에 upsert. idempotent."""

    def _do(s: Session) -> DomainLoadResponse:
        loaded = load_domain_from_dict(s, data=body.spec)
        return DomainLoadResponse(
            domain_code=loaded.domain_code,
            resource_codes=sorted(loaded.resource_ids.keys()),
            namespace_names=sorted(loaded.namespace_ids.keys()),
        )

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
