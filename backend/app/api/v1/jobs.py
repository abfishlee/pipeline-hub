"""HTTP 경계 — `/v1/jobs` (수집 작업 조회).

권한: ADMIN 또는 OPERATOR.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core import errors as app_errors
from app.deps import SessionDep, require_roles
from app.repositories import raw as raw_repo
from app.schemas.jobs import JobOut, JobStatus, JobType

router = APIRouter(
    prefix="/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_roles("ADMIN", "OPERATOR"))],
)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    session: SessionDep,
    source_id: Annotated[int | None, Query(ge=1)] = None,
    status: JobStatus | None = Query(default=None),
    job_type: JobType | None = Query(default=None),
    from_ts: Annotated[
        datetime | None, Query(alias="from", description="created_at >= (ISO 8601)")
    ] = None,
    to_ts: Annotated[
        datetime | None, Query(alias="to", description="created_at <= (ISO 8601)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[JobOut]:
    items = await raw_repo.list_ingest_jobs(
        session,
        source_id=source_id,
        status=status,
        job_type=job_type,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        offset=offset,
    )
    return [JobOut.model_validate(j) for j in items]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, session: SessionDep) -> JobOut:
    job = await raw_repo.get_ingest_job(session, job_id)
    if job is None:
        raise app_errors.NotFoundError(f"ingest_job {job_id} not found")
    return JobOut.model_validate(job)
