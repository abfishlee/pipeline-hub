"""HTTP — `/v2/contracts` (Phase 5.2.1).

source x domain x resource x version 4-key contract 의 CRUD + compatibility check +
resource_selector 검증.
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
from app.domain.registry.compatibility import check_schema_compatibility
from app.domain.registry.selector import (
    _ContractCandidate,
    match_resource_selector,
)
from app.models.domain import SourceContract

router = APIRouter(
    prefix="/v2/contracts",
    tags=["v2-contracts"],
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN"))],
)


class ContractCreate(BaseModel):
    """주의: Pydantic V2 의 BaseModel 에 `schema_json` 메서드가 있어서 같은 이름의
    필드를 정의하면 type 충돌. ORM 컬럼명 (`schema_json`) 은 유지하되 Pydantic 필드는
    별칭 사용."""

    model_config = ConfigDict(populate_by_name=True)

    source_id: int = Field(ge=1)
    domain_code: str
    resource_code: str
    schema_version: int = Field(default=1, ge=1)
    schema_payload: dict[str, Any] = Field(default_factory=dict, alias="schema_json")
    compatibility_mode: str = Field(default="backward")
    resource_selector_json: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    contract_id: int
    source_id: int
    domain_code: str
    resource_code: str
    schema_version: int
    schema_payload: dict[str, Any] = Field(alias="schema_json")
    compatibility_mode: str
    resource_selector_json: dict[str, Any]
    status: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class CompatibilityCheckRequest(BaseModel):
    source_id: int = Field(ge=1)
    domain_code: str
    resource_code: str
    new_schema_json: dict[str, Any]
    mode: str = "backward"


class CompatibilityCheckResponse(BaseModel):
    is_compatible: bool
    mode: str
    breaking_changes: list[str]
    additive_changes: list[str]


class SelectorEvalRequest(BaseModel):
    source_id: int = Field(ge=1)
    payload: dict[str, Any]
    request_endpoint: str | None = None


class SelectorEvalResponse(BaseModel):
    matched: bool
    contract_id: int | None = None
    domain_code: str | None = None
    resource_code: str | None = None
    schema_version: int | None = None
    matched_by: str | None = None


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


@router.post("", response_model=ContractOut, status_code=201)
async def create_contract(body: ContractCreate) -> ContractOut:
    def _do(s: Session) -> ContractOut:
        contract = SourceContract(
            source_id=body.source_id,
            domain_code=body.domain_code,
            resource_code=body.resource_code,
            schema_version=body.schema_version,
            schema_json=body.schema_payload,
            compatibility_mode=body.compatibility_mode,
            resource_selector_json=body.resource_selector_json,
            description=body.description,
        )
        s.add(contract)
        s.flush()
        return ContractOut.model_validate(contract)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("", response_model=list[ContractOut])
async def list_contracts(source_id: int | None = None) -> list[ContractOut]:
    def _do(s: Session) -> list[ContractOut]:
        q = select(SourceContract).order_by(
            SourceContract.source_id,
            SourceContract.domain_code,
            SourceContract.resource_code,
            SourceContract.schema_version.desc(),
        )
        if source_id:
            q = q.where(SourceContract.source_id == source_id)
        rows = s.execute(q).scalars().all()
        return [ContractOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/check-compatibility", response_model=CompatibilityCheckResponse)
async def check_compatibility(
    body: CompatibilityCheckRequest,
) -> CompatibilityCheckResponse:
    """기존 (가장 최신) schema_version 과 새 schema 의 호환성 비교."""

    def _do(s: Session) -> CompatibilityCheckResponse:
        existing = s.execute(
            select(SourceContract)
            .where(SourceContract.source_id == body.source_id)
            .where(SourceContract.domain_code == body.domain_code)
            .where(SourceContract.resource_code == body.resource_code)
            .order_by(SourceContract.schema_version.desc())
            .limit(1)
        ).scalar_one_or_none()
        old_schema = existing.schema_json if existing else None
        result = check_schema_compatibility(
            old_schema=old_schema,
            new_schema=body.new_schema_json,
            mode=body.mode,
        )
        return CompatibilityCheckResponse(
            is_compatible=result.is_compatible,
            mode=result.mode,
            breaking_changes=result.breaking_changes,
            additive_changes=result.additive_changes,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/evaluate-selector", response_model=SelectorEvalResponse)
async def evaluate_selector(body: SelectorEvalRequest) -> SelectorEvalResponse:
    """주어진 source_id 의 모든 contract 중 payload 가 어디 매치되는지."""

    def _do(s: Session) -> SelectorEvalResponse:
        contracts = list(
            s.execute(
                select(SourceContract).where(SourceContract.source_id == body.source_id)
            ).scalars()
        )
        candidates = [
            _ContractCandidate(
                contract_id=c.contract_id,
                domain_code=c.domain_code,
                resource_code=c.resource_code,
                schema_version=c.schema_version,
                selector=dict(c.resource_selector_json or {}),
            )
            for c in contracts
        ]
        match = match_resource_selector(
            payload=body.payload,
            request_endpoint=body.request_endpoint,
            candidates=candidates,
        )
        if match is None:
            return SelectorEvalResponse(matched=False)
        return SelectorEvalResponse(
            matched=True,
            contract_id=match.contract_id,
            domain_code=match.domain_code,
            resource_code=match.resource_code,
            schema_version=match.schema_version,
            matched_by=match.matched_by,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{contract_id}", response_model=ContractOut)
async def get_contract(contract_id: int) -> ContractOut:
    def _do(s: Session) -> ContractOut:
        row = s.get(SourceContract, contract_id)
        if row is None:
            raise app_errors.NotFoundError(f"contract {contract_id} not found")
        return ContractOut.model_validate(row)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
