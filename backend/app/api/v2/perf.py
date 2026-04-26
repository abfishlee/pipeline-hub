"""HTTP — `/v2/perf` (Phase 5.2.8 STEP 11).

SLO 측정 적재/요약 + SQL Performance Coach + DB baseline 자동 측정 endpoint.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.perf_guards import (
    PerfSloSample,
    SqlCoachOutcome,
    analyze_sql,
    record_slo,
    summarize_slo,
)
from app.domain.perf_guards.slo import (
    measure_db_baseline,
    record_baseline_batch,
)

router = APIRouter(
    prefix="/v2/perf",
    tags=["v2-perf"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "OPERATOR", "APPROVER"))
    ],
)


class SloSampleIn(BaseModel):
    metric_code: str
    value: float
    unit: str
    domain_code: str | None = None
    sample_count: int = 0
    window_seconds: int = 60
    tags: dict[str, Any] = Field(default_factory=dict)


class SloRecordResponse(BaseModel):
    slo_id: int


class SloSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_code: str
    domain_code: str | None
    last_value: float | None
    avg_value: float | None
    max_value: float | None
    sample_count: int
    verdict: str


class BaselineMeasureResponse(BaseModel):
    measured_count: int
    metrics: list[str]
    measured_at: datetime


class CoachAnalyzeRequest(BaseModel):
    domain_code: str | None = None
    sql: str = Field(min_length=1, max_length=10_000)


class CoachAnalyzeResponse(BaseModel):
    verdict: str
    warnings: list[str]
    estimated_rows: int | None = None
    estimated_cost: float | None = None
    scanned_relations: list[str] = Field(default_factory=list)


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


@router.post("/slo", response_model=SloRecordResponse, status_code=201)
async def record_one_slo(body: SloSampleIn) -> SloRecordResponse:
    def _do(s: Session) -> SloRecordResponse:
        try:
            sid = record_slo(
                s,
                PerfSloSample(
                    metric_code=body.metric_code,
                    value=body.value,
                    unit=body.unit,
                    domain_code=body.domain_code,
                    sample_count=body.sample_count,
                    window_seconds=body.window_seconds,
                    tags=body.tags,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SloRecordResponse(slo_id=sid)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/slo/summary", response_model=list[SloSummaryOut])
async def slo_summary(
    domain_code: str | None = None,
    window_minutes: int = 60,
) -> list[SloSummaryOut]:
    def _do(s: Session) -> list[SloSummaryOut]:
        rows = summarize_slo(
            s, domain_code=domain_code, window_minutes=window_minutes
        )
        return [
            SloSummaryOut(
                metric_code=r.metric_code,
                domain_code=r.domain_code,
                last_value=r.last_value,
                avg_value=r.avg_value,
                max_value=r.max_value,
                sample_count=r.sample_count,
                verdict=r.verdict,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/baseline/measure", response_model=BaselineMeasureResponse)
async def measure_baseline(user: CurrentUserDep) -> BaselineMeasureResponse:
    """STEP 11 의 첫 작업 (Q1) — DB baseline 자동 측정 + 적재."""
    del user

    def _do(s: Session) -> BaselineMeasureResponse:
        samples = measure_db_baseline(s)
        n = record_baseline_batch(s, samples)
        from datetime import UTC
        from datetime import datetime as _dt

        return BaselineMeasureResponse(
            measured_count=n,
            metrics=list(samples.keys()),
            measured_at=_dt.now(UTC),
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/coach/analyze", response_model=CoachAnalyzeResponse)
async def coach_analyze(
    body: CoachAnalyzeRequest, user: CurrentUserDep
) -> CoachAnalyzeResponse:
    def _do(s: Session) -> CoachAnalyzeResponse:
        out: SqlCoachOutcome = analyze_sql(
            s,
            sql=body.sql,
            domain_code=body.domain_code,
            requested_by=user.user_id,
        )
        return CoachAnalyzeResponse(
            verdict=out.verdict,
            warnings=out.warnings,
            estimated_rows=out.estimated_rows,
            estimated_cost=out.estimated_cost,
            scanned_relations=out.scanned_relations,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
