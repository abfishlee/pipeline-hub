"""HTTP — `/v1/admin/partitions` (Phase 4.2.7, ADMIN 만).

운영자가 ctl.partition_archive_log 를 조회하고, 1건씩 *수동 archive 실행* 또는
*복원* 트리거.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.partition_archive import (
    PartitionRef,
    archive_partition,
    restore_partition,
)
from app.integrations.object_storage import get_object_storage

router = APIRouter(
    prefix="/v1/admin/partitions",
    tags=["admin-partitions"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


class PartitionArchiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    archive_id: int
    schema_name: str
    table_name: str
    partition_name: str
    row_count: int | None
    byte_size: int | None
    checksum: str | None
    object_uri: str | None
    status: str
    archived_at: datetime | None
    restored_at: datetime | None
    restored_to: str | None
    error_message: str | None
    created_at: datetime


class RestoreRequest(BaseModel):
    target_table: str | None = None


class ArchiveActionResponse(BaseModel):
    archive_id: int
    status: str
    detail: str
    object_uri: str | None = None
    row_count: int | None = None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


@router.get("", response_model=list[PartitionArchiveOut])
async def list_archives(
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[PartitionArchiveOut]:
    def _do(s: Session) -> list[dict[str, Any]]:
        q = (
            "SELECT * FROM ctl.partition_archive_log "
            + ("WHERE status = :st " if status else "")
            + "ORDER BY archive_id DESC LIMIT :lim"
        )
        rows = s.execute(
            text(q),
            {"st": status, "lim": limit} if status else {"lim": limit},
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    rows = await asyncio.to_thread(_run_in_sync, _do)
    return [PartitionArchiveOut(**r) for r in rows]


@router.post("/{archive_id}/run", response_model=ArchiveActionResponse)
async def run_archive(
    archive_id: int, user: CurrentUserDep
) -> ArchiveActionResponse:
    """PENDING 상태의 row 1건을 실제 archive 처리 (Object Storage 복제 + DETACH + DROP)."""

    def _do(s: Session) -> ArchiveActionResponse:
        row = s.execute(
            text(
                "SELECT schema_name, table_name, partition_name, status "
                "FROM ctl.partition_archive_log WHERE archive_id = :id"
            ),
            {"id": archive_id},
        ).one_or_none()
        if row is None:
            raise app_errors.NotFoundError(f"archive {archive_id} not found")
        if row.status not in ("PENDING", "FAILED"):
            raise app_errors.ValidationError(
                f"archive {archive_id} status={row.status} is not PENDING/FAILED"
            )
        ref = PartitionRef(
            schema_name=row.schema_name,
            table_name=row.table_name,
            partition_name=row.partition_name,
        )
        storage = get_object_storage()
        stats = archive_partition(
            s, ref=ref, object_storage=storage, archived_by=user.user_id
        )
        return ArchiveActionResponse(
            archive_id=stats.archive_id,
            status="DROPPED",
            detail=f"archived {stats.row_count} rows ({stats.byte_size} bytes)",
            object_uri=stats.object_uri,
            row_count=stats.row_count,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/{archive_id}/restore", response_model=ArchiveActionResponse)
async def run_restore(
    archive_id: int, body: RestoreRequest, user: CurrentUserDep
) -> ArchiveActionResponse:
    """archive_id 의 데이터를 임시 테이블로 복원."""

    def _do(s: Session) -> ArchiveActionResponse:
        try:
            target = restore_partition(
                s,
                archive_id=archive_id,
                object_storage=get_object_storage(),
                target_table=body.target_table,
                restored_by=user.user_id,
            )
        except ValueError as exc:
            raise app_errors.ValidationError(str(exc)) from exc
        return ArchiveActionResponse(
            archive_id=archive_id,
            status="RESTORED",
            detail=f"restored to {target}",
        )

    return await asyncio.to_thread(_run_in_sync, _do)


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


__all__ = ["router"]
