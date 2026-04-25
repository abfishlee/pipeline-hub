"""Pydantic DTOs — `run.ingest_job` 조회."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"]
JobType = Literal["ON_DEMAND", "SCHEDULED", "RETRY", "BACKFILL"]


class JobOut(BaseModel):
    """단일 ingest_job 직렬화."""

    model_config = ConfigDict(from_attributes=True)

    job_id: int
    source_id: int
    job_type: JobType
    status: JobStatus
    requested_by: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_count: int = 0
    output_count: int = 0
    error_count: int = 0
    error_message: str | None = None
    created_at: datetime


__all__ = ["JobOut", "JobStatus", "JobType"]
