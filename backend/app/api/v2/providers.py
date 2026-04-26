"""HTTP — `/v2/providers` (Phase 5.2.1.1).

provider_definition 의 list/get + source_provider_binding CRUD + circuit breaker
상태 조회/리셋.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles
from app.domain.providers.circuit_breaker import CircuitBreaker
from app.models.domain import ProviderDefinition, SourceProviderBinding

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
    secret_ref: str | None
    description: str | None
    is_active: bool
    created_at: datetime


class BindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    binding_id: int
    source_id: int
    provider_code: str
    priority: int
    fallback_order: int
    config_json: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BindingCreate(BaseModel):
    source_id: int = Field(ge=1)
    provider_code: str
    priority: int = Field(default=1, ge=1, le=10)
    fallback_order: int = Field(default=1, ge=1, le=10)
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class BindingUpdate(BaseModel):
    priority: int | None = Field(default=None, ge=1, le=10)
    fallback_order: int | None = Field(default=None, ge=1, le=10)
    config_json: dict[str, Any] | None = None
    is_active: bool | None = None


class CircuitStateOut(BaseModel):
    provider_code: str
    source_id: int
    state: str
    failure_count: int
    last_error: str | None


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


@router.get("/bindings", response_model=list[BindingOut])
async def list_bindings(
    source_id: int | None = Query(default=None, ge=1),
) -> list[BindingOut]:
    def _do(s: Session) -> list[BindingOut]:
        q = select(SourceProviderBinding).order_by(
            SourceProviderBinding.source_id,
            SourceProviderBinding.priority,
        )
        if source_id is not None:
            q = q.where(SourceProviderBinding.source_id == source_id)
        rows = s.execute(q).scalars().all()
        return [BindingOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/bindings", response_model=BindingOut, status_code=201)
async def create_binding(body: BindingCreate) -> BindingOut:
    def _do(s: Session) -> BindingOut:
        prov = s.get(ProviderDefinition, body.provider_code)
        if prov is None:
            raise app_errors.NotFoundError(f"provider {body.provider_code} not found")
        binding = SourceProviderBinding(
            source_id=body.source_id,
            provider_code=body.provider_code,
            priority=body.priority,
            fallback_order=body.fallback_order,
            config_json=body.config_json,
            is_active=body.is_active,
        )
        s.add(binding)
        s.flush()
        return BindingOut.model_validate(binding)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/bindings/{binding_id}", response_model=BindingOut)
async def update_binding(binding_id: int, body: BindingUpdate) -> BindingOut:
    def _do(s: Session) -> BindingOut:
        binding = s.get(SourceProviderBinding, binding_id)
        if binding is None:
            raise app_errors.NotFoundError(f"binding {binding_id} not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(binding, field_name, value)
        s.flush()
        return BindingOut.model_validate(binding)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/circuit/{provider_code}/{source_id}", response_model=CircuitStateOut)
async def get_circuit_state(provider_code: str, source_id: int) -> CircuitStateOut:
    """현재 (provider, source) 의 circuit breaker 상태."""
    cb = CircuitBreaker(provider_code=provider_code, source_id=source_id)
    snap = await cb.get_state()
    return CircuitStateOut(
        provider_code=provider_code,
        source_id=source_id,
        state=snap.state.value,
        failure_count=snap.failure_count,
        last_error=snap.last_error,
    )


@router.post("/circuit/{provider_code}/{source_id}/reset", status_code=204)
async def reset_circuit(provider_code: str, source_id: int) -> Response:
    """ADMIN 이 OPEN circuit 을 강제로 CLOSED 로 리셋 (운영 복구)."""
    cb = CircuitBreaker(provider_code=provider_code, source_id=source_id)
    await cb.reset()
    return Response(status_code=204)


__all__ = ["router"]
