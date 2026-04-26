"""HTTP — `/v2/backfill` (Phase 5.2.8 STEP 11 Q4).

backfill 잡 생성 + chunk 진행 조회 + 완료 처리.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.perf_guards import (
    BackfillJobSpec,
    BackfillStatus,
    create_backfill_job,
    mark_chunk_done,
    update_job_status,
)
from app.domain.perf_guards.backfill import BackfillError, maybe_complete_job

router = APIRouter(
    prefix="/v2/backfill",
    tags=["v2-backfill"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "OPERATOR"))
    ],
)


class BackfillJobCreate(BaseModel):
    domain_code: str
    resource_code: str
    target_table: str
    start_at: datetime
    end_at: datetime
    chunk_unit: str = Field(default="day", pattern=r"^(hour|day|week|month)$")
    chunk_size: int = Field(default=1, ge=1, le=365)
    batch_size: int = Field(default=5_000, ge=100, le=100_000)
    max_parallel_runs: int = Field(default=2, ge=1, le=10)
    statement_timeout_ms: int = Field(default=60_000, ge=1_000, le=600_000)
    lock_timeout_ms: int = Field(default=3_000, ge=100, le=60_000)
    sleep_between_chunks_ms: int = Field(default=1_000, ge=0, le=60_000)
    sql_template: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BackfillJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: int
    domain_code: str
    resource_code: str
    target_table: str
    start_at: datetime
    end_at: datetime
    chunk_unit: str
    chunk_size: int
    batch_size: int
    max_parallel_runs: int
    status: str
    total_chunks: int
    completed_chunks: int
    failed_chunks: int
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BackfillChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: int
    chunk_index: int
    chunk_start: datetime
    chunk_end: datetime
    status: str
    attempts: int


class ChunkDoneRequest(BaseModel):
    chunk_id: int = Field(ge=1)
    success: bool
    rows_processed: int = Field(default=0, ge=0)
    error_message: str | None = None
    checkpoint: dict[str, Any] = Field(default_factory=dict)


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


def _row_to_job(row: Any) -> BackfillJobOut:
    return BackfillJobOut(
        job_id=int(row.job_id),
        domain_code=str(row.domain_code),
        resource_code=str(row.resource_code),
        target_table=str(row.target_table),
        start_at=row.start_at,
        end_at=row.end_at,
        chunk_unit=str(row.chunk_unit),
        chunk_size=int(row.chunk_size),
        batch_size=int(row.batch_size),
        max_parallel_runs=int(row.max_parallel_runs),
        status=str(row.status),
        total_chunks=int(row.total_chunks),
        completed_chunks=int(row.completed_chunks),
        failed_chunks=int(row.failed_chunks),
        requested_at=row.requested_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


@router.post("", response_model=BackfillJobOut, status_code=201)
async def create(body: BackfillJobCreate, user: CurrentUserDep) -> BackfillJobOut:
    def _do(s: Session) -> BackfillJobOut:
        spec = BackfillJobSpec(
            domain_code=body.domain_code,
            resource_code=body.resource_code,
            target_table=body.target_table,
            start_at=body.start_at,
            end_at=body.end_at,
            chunk_unit=body.chunk_unit,
            chunk_size=body.chunk_size,
            batch_size=body.batch_size,
            max_parallel_runs=body.max_parallel_runs,
            statement_timeout_ms=body.statement_timeout_ms,
            lock_timeout_ms=body.lock_timeout_ms,
            sleep_between_chunks_ms=body.sleep_between_chunks_ms,
            sql_template=body.sql_template,
            extra=body.extra,
        )
        try:
            job_id, _ = create_backfill_job(s, spec, requested_by=user.user_id)
        except BackfillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        row = s.execute(
            text(
                "SELECT * FROM ctl.backfill_job WHERE job_id = :j"
            ),
            {"j": job_id},
        ).first()
        assert row is not None
        return _row_to_job(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("", response_model=list[BackfillJobOut])
async def list_jobs(
    status: str | None = None, limit: int = 20
) -> list[BackfillJobOut]:
    def _do(s: Session) -> list[BackfillJobOut]:
        sql = "SELECT * FROM ctl.backfill_job "
        params: dict[str, Any] = {"lim": min(max(limit, 1), 100)}
        if status:
            sql += "WHERE status = :st "
            params["st"] = status
        sql += "ORDER BY requested_at DESC LIMIT :lim"
        rows = s.execute(text(sql), params).all()
        return [_row_to_job(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{job_id}", response_model=BackfillJobOut)
async def get_job(job_id: int) -> BackfillJobOut:
    def _do(s: Session) -> BackfillJobOut:
        row = s.execute(
            text("SELECT * FROM ctl.backfill_job WHERE job_id = :j"),
            {"j": job_id},
        ).first()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"job {job_id} not found"
            )
        return _row_to_job(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{job_id}/chunks", response_model=list[BackfillChunkOut])
async def list_chunks(
    job_id: int, status: str | None = None, limit: int = 50
) -> list[BackfillChunkOut]:
    def _do(s: Session) -> list[BackfillChunkOut]:
        sql = (
            "SELECT chunk_id, chunk_index, chunk_start, chunk_end, status, attempts "
            "FROM ctl.backfill_chunk WHERE job_id = :j "
        )
        params: dict[str, Any] = {"j": job_id, "lim": min(max(limit, 1), 500)}
        if status:
            sql += "AND status = :st "
            params["st"] = status
        sql += "ORDER BY chunk_index LIMIT :lim"
        rows = s.execute(text(sql), params).all()
        return [
            BackfillChunkOut(
                chunk_id=int(r.chunk_id),
                chunk_index=int(r.chunk_index),
                chunk_start=r.chunk_start,
                chunk_end=r.chunk_end,
                status=str(r.status),
                attempts=int(r.attempts),
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/{job_id}/start", response_model=BackfillJobOut)
async def start(job_id: int) -> BackfillJobOut:
    def _do(s: Session) -> BackfillJobOut:
        update_job_status(s, job_id=job_id, status=BackfillStatus.RUNNING)
        row = s.execute(
            text("SELECT * FROM ctl.backfill_job WHERE job_id = :j"),
            {"j": job_id},
        ).first()
        assert row is not None
        return _row_to_job(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/chunk/done", response_model=BackfillJobOut)
async def chunk_done(body: ChunkDoneRequest) -> BackfillJobOut:
    def _do(s: Session) -> BackfillJobOut:
        mark_chunk_done(
            s,
            chunk_id=body.chunk_id,
            success=body.success,
            rows_processed=body.rows_processed,
            error_message=body.error_message,
            checkpoint=body.checkpoint,
        )
        # 같은 row 의 job_id 조회.
        job_id = s.execute(
            text("SELECT job_id FROM ctl.backfill_chunk WHERE chunk_id = :c"),
            {"c": body.chunk_id},
        ).scalar_one()
        maybe_complete_job(s, job_id=int(job_id))
        row = s.execute(
            text("SELECT * FROM ctl.backfill_job WHERE job_id = :j"),
            {"j": int(job_id)},
        ).first()
        assert row is not None
        return _row_to_job(row)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
