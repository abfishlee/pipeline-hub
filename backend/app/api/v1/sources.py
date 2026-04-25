"""HTTP 경계 — `/v1/sources` (data_source CRUD).

권한:
  - 조회 (GET 목록 / GET 상세)  → ADMIN 또는 OPERATOR
  - 변경 (POST/PATCH/DELETE)     → ADMIN
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.deps import SessionDep, require_roles
from app.repositories import sources as sources_repo
from app.schemas.sources import (
    DataSourceCreate,
    DataSourceOut,
    DataSourceUpdate,
    SourceType,
)

# 전체 라우터: ADMIN 또는 OPERATOR 가 기본 통과. 변경 라우트는 추가 ADMIN 가드.
router = APIRouter(
    prefix="/v1/sources",
    tags=["sources"],
    dependencies=[Depends(require_roles("ADMIN", "OPERATOR"))],
)


@router.post(
    "",
    response_model=DataSourceOut,
    status_code=201,
    dependencies=[Depends(require_roles("ADMIN"))],
)
async def create_source(body: DataSourceCreate, session: SessionDep) -> DataSourceOut:
    src = await sources_repo.create(
        session,
        source_code=body.source_code,
        source_name=body.source_name,
        source_type=body.source_type,
        retailer_id=body.retailer_id,
        owner_team=body.owner_team,
        is_active=body.is_active,
        config_json=body.config_json,
        schedule_cron=body.schedule_cron,
    )
    await session.commit()
    return DataSourceOut.model_validate(src)


@router.get("", response_model=list[DataSourceOut])
async def list_sources(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source_type: SourceType | None = Query(None),
    is_active: bool | None = Query(None),
) -> list[DataSourceOut]:
    items = await sources_repo.list_paginated(
        session,
        limit=limit,
        offset=offset,
        source_type=source_type,
        is_active=is_active,
    )
    return [DataSourceOut.model_validate(s) for s in items]


@router.get("/{source_id}", response_model=DataSourceOut)
async def get_source(source_id: int, session: SessionDep) -> DataSourceOut:
    src = await sources_repo.get_by_id(session, source_id)
    if src is None:
        from app.core import errors as app_errors

        raise app_errors.NotFoundError(f"data_source {source_id} not found")
    return DataSourceOut.model_validate(src)


@router.patch(
    "/{source_id}",
    response_model=DataSourceOut,
    dependencies=[Depends(require_roles("ADMIN"))],
)
async def update_source(
    source_id: int, body: DataSourceUpdate, session: SessionDep
) -> DataSourceOut:
    # exclude_unset=True → 미제공 필드는 변경 안 됨.
    # 명시적 None 으로 보낸 nullable 필드는 NULL 로 비워짐.
    fields = body.model_dump(exclude_unset=True)
    src = await sources_repo.update_fields(session, source_id, fields)
    await session.commit()
    return DataSourceOut.model_validate(src)


@router.delete(
    "/{source_id}",
    status_code=204,
    dependencies=[Depends(require_roles("ADMIN"))],
)
async def delete_source(source_id: int, session: SessionDep) -> Response:
    """Soft delete — is_active=FALSE. 수집 이력 보존."""
    await sources_repo.soft_delete(session, source_id)
    await session.commit()
    return Response(status_code=204)
