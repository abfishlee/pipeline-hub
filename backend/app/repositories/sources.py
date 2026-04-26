"""Repository — `ctl.data_source`.

API/도메인은 직접 ORM 쿼리를 작성하지 않는다. 모든 함수는 async,
commit 책임은 호출자(api).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.ctl import DataSource


async def get_by_id(session: AsyncSession, source_id: int) -> DataSource | None:
    stmt = select(DataSource).where(DataSource.source_id == source_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_by_code(session: AsyncSession, source_code: str) -> DataSource | None:
    stmt = select(DataSource).where(DataSource.source_code == source_code)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_paginated(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    source_type: str | None = None,
    is_active: bool | None = None,
) -> list[DataSource]:
    stmt = select(DataSource).order_by(DataSource.source_id.asc()).limit(limit).offset(offset)
    if source_type is not None:
        stmt = stmt.where(DataSource.source_type == source_type)
    if is_active is not None:
        stmt = stmt.where(DataSource.is_active == is_active)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create(
    session: AsyncSession,
    *,
    source_code: str,
    source_name: str,
    source_type: str,
    retailer_id: int | None = None,
    owner_team: str | None = None,
    is_active: bool = True,
    config_json: dict[str, Any] | None = None,
    schedule_cron: str | None = None,
) -> DataSource:
    if await get_by_code(session, source_code):
        raise ConflictError(f"source_code '{source_code}' already exists")
    src = DataSource(
        source_code=source_code,
        source_name=source_name,
        source_type=source_type,
        retailer_id=retailer_id,
        owner_team=owner_team,
        is_active=is_active,
        config_json=config_json or {},
        schedule_cron=schedule_cron,
    )
    session.add(src)
    await session.flush()
    return src


# 부분 업데이트 — None 으로 명시 전송된 필드도 그대로 적용 (nullable 컬럼 unset 의도).
# 호출부(api)는 Pydantic `model_dump(exclude_unset=True)` 로 미제공 필드 제거.
_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "source_name",
        "source_type",
        "retailer_id",
        "owner_team",
        "is_active",
        "config_json",
        "schedule_cron",
        "cdc_enabled",
    }
)


async def update_fields(
    session: AsyncSession, source_id: int, fields: dict[str, Any]
) -> DataSource:
    src = await get_by_id(session, source_id)
    if src is None:
        raise NotFoundError(f"data_source {source_id} not found")
    for key, value in fields.items():
        if key not in _UPDATABLE_FIELDS:
            continue  # source_code 등 immutable 은 무시
        setattr(src, key, value)
    # server_default 는 INSERT 전용 → updated_at 명시 갱신.
    src.updated_at = datetime.now(UTC)
    await session.flush()
    return src


async def soft_delete(session: AsyncSession, source_id: int) -> DataSource:
    """is_active=FALSE. 실제 row 는 보존 (수집 이력의 source_id FK 보호)."""
    return await update_fields(session, source_id, {"is_active": False})


__all__ = [
    "create",
    "get_by_code",
    "get_by_id",
    "list_paginated",
    "soft_delete",
    "update_fields",
]
