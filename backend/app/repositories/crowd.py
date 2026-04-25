"""Crowd 검수 큐 repository (Phase 2.2.10)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw import OcrResult, RawObject
from app.models.run import CrowdTask


async def list_tasks(
    session: AsyncSession,
    *,
    status: str | None = None,
    reason: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[CrowdTask]:
    stmt = select(CrowdTask)
    if status:
        stmt = stmt.where(CrowdTask.status == status)
    if reason:
        stmt = stmt.where(CrowdTask.reason == reason)
    stmt = stmt.order_by(CrowdTask.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_task(session: AsyncSession, crowd_task_id: int) -> CrowdTask | None:
    return await session.get(CrowdTask, crowd_task_id)


async def get_raw_object(
    session: AsyncSession, *, raw_object_id: int, partition_date: object
) -> RawObject | None:
    stmt = (
        select(RawObject)
        .where(RawObject.raw_object_id == raw_object_id)
        .where(RawObject.partition_date == partition_date)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_ocr_results(
    session: AsyncSession, *, raw_object_id: int, partition_date: object
) -> Sequence[OcrResult]:
    stmt = (
        select(OcrResult)
        .where(OcrResult.raw_object_id == raw_object_id)
        .where(OcrResult.partition_date == partition_date)
        .order_by(OcrResult.page_no.asc().nulls_last(), OcrResult.ocr_result_id.asc())
    )
    return (await session.execute(stmt)).scalars().all()


async def update_status(
    session: AsyncSession,
    *,
    task: CrowdTask,
    new_status: str,
    reviewer_user_id: int,
) -> CrowdTask:
    task.status = new_status
    task.reviewed_by = reviewer_user_id
    task.reviewed_at = datetime.now(UTC)
    await session.flush()
    return task


__all__ = [
    "get_ocr_results",
    "get_raw_object",
    "get_task",
    "list_tasks",
    "update_status",
]
