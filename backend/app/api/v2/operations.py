"""HTTP — `/v2/operations` (Phase 7 Wave 5 — Operations Dashboard).

15~20개 Canvas 프로세스 동시 운영 시 한눈에 볼 수 있는 채널/노드 단위 통합
모니터링 endpoint.

엔드포인트:
  GET /v2/operations/summary       — 전체 workflow 24h 성공률 + pending replay
  GET /v2/operations/channels      — 채널 (workflow) 별 상태
  GET /v2/operations/heatmap       — workflow 의 노드별 24h status heatmap
  POST /v1/pipelines/runs/{id}/replay-from?node_key=...  — 별도 라우터
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles

router = APIRouter(
    prefix="/v2/operations",
    tags=["v2-operations"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class OperationsSummary(BaseModel):
    workflow_count: int
    runs_24h: int
    success_24h: int
    failed_24h: int
    success_rate_pct: float
    rows_ingested_24h: int
    pending_replay: int
    provider_failures_24h: int


class ChannelStatusOut(BaseModel):
    workflow_id: int
    workflow_name: str
    status: str
    schedule_cron: str | None
    schedule_enabled: bool
    last_run_at: datetime | None
    last_run_status: str | None
    runs_24h: int
    success_24h: int
    failed_24h: int
    rows_24h: int
    success_rate_pct: float


class NodeHeatmapCell(BaseModel):
    node_key: str
    node_type: str
    success_count: int
    failed_count: int
    skipped_count: int


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        return fn(session)


@router.get("/summary", response_model=OperationsSummary)
async def get_summary() -> OperationsSummary:
    def _do(s: Session) -> OperationsSummary:
        since = datetime.utcnow() - timedelta(hours=24)
        wf_count = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM wf.workflow_definition "
                    "WHERE status = 'PUBLISHED'"
                )
            ).scalar_one()
        )
        runs = s.execute(
            text(
                "SELECT status, COUNT(*) AS cnt FROM run.pipeline_run "
                "WHERE started_at >= :since "
                "GROUP BY status"
            ),
            {"since": since},
        ).all()
        run_map = {str(r.status): int(r.cnt) for r in runs}
        runs_24h = sum(run_map.values())
        success = run_map.get("SUCCESS", 0)
        failed = run_map.get("FAILED", 0)
        rate = (success / runs_24h * 100.0) if runs_24h > 0 else 100.0

        rows_ingested = int(
            s.execute(
                text(
                    "SELECT COALESCE(SUM(output_count), 0) "
                    "FROM run.ingest_job WHERE finished_at >= :since"
                ),
                {"since": since},
            ).scalar_one()
            or 0
        )
        pending_replay = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM run.pipeline_run "
                    "WHERE status IN ('FAILED','CANCELLED') "
                    "  AND finished_at >= :since"
                ),
                {"since": since},
            ).scalar_one()
        )

        try:
            provider_failures = int(
                s.execute(
                    text(
                        "SELECT COALESCE(SUM(error_count), 0) "
                        "FROM audit.provider_usage "
                        "WHERE occurred_at >= :since"
                    ),
                    {"since": since},
                ).scalar_one()
                or 0
            )
        except Exception:
            provider_failures = 0

        return OperationsSummary(
            workflow_count=wf_count,
            runs_24h=runs_24h,
            success_24h=success,
            failed_24h=failed,
            success_rate_pct=round(rate, 1),
            rows_ingested_24h=rows_ingested,
            pending_replay=pending_replay,
            provider_failures_24h=provider_failures,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/channels", response_model=list[ChannelStatusOut])
async def list_channels(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ChannelStatusOut]:
    """모든 PUBLISHED workflow 를 채널처럼 나열 + 24h aggregate."""

    def _do(s: Session) -> list[ChannelStatusOut]:
        since = datetime.utcnow() - timedelta(hours=24)
        # workflow + 24h 통계 + 최근 run
        rows = s.execute(
            text(
                """
                WITH stats AS (
                  SELECT workflow_id,
                         COUNT(*) AS runs_24h,
                         COUNT(*) FILTER (WHERE status='SUCCESS') AS success_24h,
                         COUNT(*) FILTER (WHERE status='FAILED') AS failed_24h,
                         MAX(started_at) AS last_run_at
                    FROM run.pipeline_run
                   WHERE started_at >= :since
                   GROUP BY workflow_id
                ),
                row_stats AS (
                  SELECT pr.workflow_id,
                         SUM(COALESCE((nr.output_json->>'row_count')::bigint, 0))
                           AS rows_24h
                    FROM run.pipeline_run pr
                    JOIN run.node_run nr USING (pipeline_run_id, run_date)
                   WHERE pr.started_at >= :since
                     AND nr.node_type IN ('LOAD_TARGET','LOAD_MASTER')
                   GROUP BY pr.workflow_id
                ),
                latest AS (
                  SELECT DISTINCT ON (workflow_id) workflow_id, status AS last_status
                    FROM run.pipeline_run
                   WHERE started_at >= :since
                   ORDER BY workflow_id, started_at DESC
                )
                SELECT w.workflow_id, w.name, w.status, w.schedule_cron,
                       w.schedule_enabled,
                       COALESCE(s.runs_24h, 0) AS runs_24h,
                       COALESCE(s.success_24h, 0) AS success_24h,
                       COALESCE(s.failed_24h, 0) AS failed_24h,
                       COALESCE(rs.rows_24h, 0) AS rows_24h,
                       s.last_run_at,
                       l.last_status
                  FROM wf.workflow_definition w
                  LEFT JOIN stats s ON w.workflow_id = s.workflow_id
                  LEFT JOIN row_stats rs ON w.workflow_id = rs.workflow_id
                  LEFT JOIN latest l ON w.workflow_id = l.workflow_id
                 WHERE w.status IN ('PUBLISHED', 'DRAFT')
                 ORDER BY (COALESCE(s.failed_24h, 0) > 0) DESC,
                          (s.runs_24h IS NULL),
                          s.last_run_at DESC NULLS LAST,
                          w.workflow_id DESC
                 LIMIT :lim
                """
            ),
            {"since": since, "lim": limit},
        ).all()
        out: list[ChannelStatusOut] = []
        for r in rows:
            runs = int(r.runs_24h or 0)
            success = int(r.success_24h or 0)
            rate = (success / runs * 100.0) if runs > 0 else 100.0
            out.append(
                ChannelStatusOut(
                    workflow_id=int(r.workflow_id),
                    workflow_name=str(r.name),
                    status=str(r.status),
                    schedule_cron=(
                        str(r.schedule_cron) if r.schedule_cron else None
                    ),
                    schedule_enabled=bool(r.schedule_enabled),
                    last_run_at=r.last_run_at,
                    last_run_status=(
                        str(r.last_status) if r.last_status else None
                    ),
                    runs_24h=runs,
                    success_24h=success,
                    failed_24h=int(r.failed_24h or 0),
                    rows_24h=int(getattr(r, "rows_24h", 0) or 0),
                    success_rate_pct=round(rate, 1),
                )
            )
        return out

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/heatmap/{workflow_id}", response_model=list[NodeHeatmapCell])
async def get_workflow_heatmap(
    workflow_id: int, days: int = Query(default=7, ge=1, le=30)
) -> list[NodeHeatmapCell]:
    """workflow 의 노드별 N일 status heatmap."""

    def _do(s: Session) -> list[NodeHeatmapCell]:
        since = datetime.utcnow() - timedelta(days=days)
        rows = s.execute(
            text(
                """
                SELECT nr.node_key, nr.node_type,
                       COUNT(*) FILTER (WHERE nr.status = 'SUCCESS') AS success_count,
                       COUNT(*) FILTER (WHERE nr.status = 'FAILED') AS failed_count,
                       COUNT(*) FILTER (WHERE nr.status = 'SKIPPED') AS skipped_count
                  FROM run.node_run nr
                  JOIN run.pipeline_run pr ON nr.pipeline_run_id = pr.pipeline_run_id
                 WHERE pr.workflow_id = :wid AND pr.started_at >= :since
                 GROUP BY nr.node_key, nr.node_type
                 ORDER BY nr.node_key
                """
            ),
            {"wid": workflow_id, "since": since},
        ).all()
        return [
            NodeHeatmapCell(
                node_key=str(r.node_key),
                node_type=str(r.node_type),
                success_count=int(r.success_count),
                failed_count=int(r.failed_count),
                skipped_count=int(r.skipped_count),
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


# ---------------------------------------------------------------------------
# Phase 8.2 — 24h 시간별 success/failed 추이
# ---------------------------------------------------------------------------
class HourlyTrendBucket(BaseModel):
    bucket_hour: datetime
    success: int
    failed: int
    total: int


@router.get("/hourly-trend", response_model=list[HourlyTrendBucket])
async def hourly_trend() -> list[HourlyTrendBucket]:
    def _do(s: Session) -> list[HourlyTrendBucket]:
        since = datetime.utcnow() - timedelta(hours=24)
        rows = s.execute(
            text(
                """
                SELECT date_trunc('hour', started_at) AS bucket,
                       COUNT(*) FILTER (WHERE status='SUCCESS') AS success,
                       COUNT(*) FILTER (WHERE status='FAILED') AS failed,
                       COUNT(*) AS total
                  FROM run.pipeline_run
                 WHERE started_at >= :since
                 GROUP BY bucket
                 ORDER BY bucket
                """
            ),
            {"since": since},
        ).all()
        return [
            HourlyTrendBucket(
                bucket_hour=r.bucket,
                success=int(r.success),
                failed=int(r.failed),
                total=int(r.total),
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


# ---------------------------------------------------------------------------
# Phase 8.2 — workflow 재실행 (PENDING run 즉시 생성)
# ---------------------------------------------------------------------------
class TriggerRerunRequest(BaseModel):
    workflow_id: int
    reason: str | None = None


class TriggerRerunResult(BaseModel):
    pipeline_run_id: int
    workflow_id: int
    status: str


@router.post("/trigger-rerun", response_model=TriggerRerunResult)
async def trigger_rerun(body: TriggerRerunRequest) -> TriggerRerunResult:
    def _do(s: Session) -> TriggerRerunResult:
        wf = s.execute(
            text(
                "SELECT workflow_id, status FROM wf.workflow_definition "
                "WHERE workflow_id = :w"
            ),
            {"w": body.workflow_id},
        ).first()
        if wf is None:
            raise HTTPException(404, detail=f"workflow {body.workflow_id} not found")
        if wf.status != "PUBLISHED":
            raise HTTPException(
                422,
                detail=f"workflow status={wf.status} — PUBLISHED 만 재실행 가능",
            )
        run_id = s.execute(
            text(
                "INSERT INTO run.pipeline_run "
                "(workflow_id, run_date, status) "
                "VALUES (:w, CURRENT_DATE, 'PENDING') "
                "RETURNING pipeline_run_id"
            ),
            {"w": body.workflow_id},
        ).scalar_one()
        return TriggerRerunResult(
            pipeline_run_id=int(run_id),
            workflow_id=body.workflow_id,
            status="PENDING",
        )

    return await asyncio.to_thread(_run_in_sync, _do)


# ---------------------------------------------------------------------------
# Phase 8.1 — 실패 원인 분류 (Operations Dashboard 보강)
# ---------------------------------------------------------------------------
class FailureCategoryRow(BaseModel):
    category: str
    failed_count: int
    sample_error: str | None
    sample_workflow_name: str | None
    last_failed_at: datetime | None


@router.get("/failure-summary", response_model=list[FailureCategoryRow])
async def failure_summary() -> list[FailureCategoryRow]:
    """24h 실패 원인 분류 — node_type 별 집계 + 최근 샘플."""

    def _do(s: Session) -> list[FailureCategoryRow]:
        since = datetime.utcnow() - timedelta(hours=24)
        rows = s.execute(
            text(
                """
                WITH cats AS (
                  SELECT
                    CASE nr.node_type
                      WHEN 'PUBLIC_API_FETCH' THEN '외부 API 실패'
                      WHEN 'WEBHOOK_INGEST' THEN 'Inbound 수신 실패'
                      WHEN 'FILE_UPLOAD_INGEST' THEN '업로드 실패'
                      WHEN 'OCR_RESULT_INGEST' THEN 'OCR 결과 실패'
                      WHEN 'CRAWLER_RESULT_INGEST' THEN '크롤러 결과 실패'
                      WHEN 'DB_INCREMENTAL_FETCH' THEN 'DB 증분 실패'
                      WHEN 'MAP_FIELDS' THEN '매핑 실패'
                      WHEN 'DQ_CHECK' THEN 'DQ 실패'
                      WHEN 'STANDARDIZE' THEN '표준화 실패'
                      WHEN 'LOAD_TARGET' THEN '마트 적재 실패'
                      WHEN 'LOAD_MASTER' THEN '마스터 적재 실패'
                      WHEN 'HTTP_TRANSFORM' THEN '외부 API 변환 실패'
                      WHEN 'SQL_INLINE_TRANSFORM' THEN 'SQL 변환 실패'
                      WHEN 'SQL_ASSET_TRANSFORM' THEN 'SQL 자산 실패'
                      ELSE nr.node_type
                    END AS category,
                    nr.error_message,
                    pr.workflow_id,
                    nr.finished_at
                    FROM run.node_run nr
                    JOIN run.pipeline_run pr USING (pipeline_run_id, run_date)
                   WHERE nr.status = 'FAILED'
                     AND pr.started_at >= :since
                ),
                grouped AS (
                  SELECT category,
                         COUNT(*) AS failed_count,
                         MAX(finished_at) AS last_failed_at
                    FROM cats
                   GROUP BY category
                ),
                samples AS (
                  SELECT DISTINCT ON (category)
                         category, error_message, workflow_id
                    FROM cats
                   ORDER BY category, finished_at DESC
                )
                SELECT g.category, g.failed_count, g.last_failed_at,
                       s.error_message AS sample_error,
                       w.name AS sample_workflow_name
                  FROM grouped g
                  LEFT JOIN samples s ON g.category = s.category
                  LEFT JOIN wf.workflow_definition w ON s.workflow_id = w.workflow_id
                 ORDER BY g.failed_count DESC, g.category
                """
            ),
            {"since": since},
        ).all()
        return [
            FailureCategoryRow(
                category=str(r.category),
                failed_count=int(r.failed_count),
                sample_error=(
                    str(r.sample_error)[:200] if r.sample_error else None
                ),
                sample_workflow_name=(
                    str(r.sample_workflow_name) if r.sample_workflow_name else None
                ),
                last_failed_at=r.last_failed_at,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


# ---------------------------------------------------------------------------
# Phase 8.4 — 최근 실패 N건 (운영자 즉시 대응)
# ---------------------------------------------------------------------------
class RecentFailureRow(BaseModel):
    pipeline_run_id: int
    run_date: str
    workflow_id: int
    workflow_name: str | None
    failed_node_key: str | None
    failed_node_type: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    # 원천 추적용 (있으면 채움 — 없으면 null).
    raw_object_id: int | None
    inbound_envelope_id: int | None


@router.get("/recent-failures", response_model=list[RecentFailureRow])
async def recent_failures(
    limit: int = Query(default=10, ge=1, le=50),
) -> list[RecentFailureRow]:
    """24h 내 FAILED 상태 pipeline_run 최근 N건 — 노드/원천 링크 포함."""

    def _do(s: Session) -> list[RecentFailureRow]:
        since = datetime.utcnow() - timedelta(hours=24)
        rows = s.execute(
            text(
                """
                WITH failed_runs AS (
                  SELECT pipeline_run_id, run_date, workflow_id,
                         started_at, finished_at, trigger_payload
                    FROM run.pipeline_run
                   WHERE status = 'FAILED'
                     AND started_at >= :since
                   ORDER BY started_at DESC
                   LIMIT :limit
                ),
                first_failed_node AS (
                  SELECT DISTINCT ON (nr.pipeline_run_id, nr.run_date)
                         nr.pipeline_run_id, nr.run_date,
                         nr.node_key, nr.node_type, nr.error_message
                    FROM run.node_run nr
                    JOIN failed_runs fr USING (pipeline_run_id, run_date)
                   WHERE nr.status = 'FAILED'
                   ORDER BY nr.pipeline_run_id, nr.run_date, nr.finished_at
                )
                SELECT fr.pipeline_run_id, fr.run_date, fr.workflow_id,
                       w.name AS workflow_name,
                       fn.node_key AS failed_node_key,
                       fn.node_type AS failed_node_type,
                       fn.error_message,
                       fr.started_at, fr.finished_at,
                       (fr.trigger_payload->>'raw_object_id')::bigint
                         AS raw_object_id,
                       (fr.trigger_payload->>'envelope_id')::bigint
                         AS inbound_envelope_id
                  FROM failed_runs fr
                  LEFT JOIN first_failed_node fn USING (pipeline_run_id, run_date)
                  LEFT JOIN wf.workflow_definition w
                         ON w.workflow_id = fr.workflow_id
                 ORDER BY fr.started_at DESC
                """
            ),
            {"since": since, "limit": limit},
        ).all()
        return [
            RecentFailureRow(
                pipeline_run_id=int(r.pipeline_run_id),
                run_date=str(r.run_date),
                workflow_id=int(r.workflow_id),
                workflow_name=r.workflow_name,
                failed_node_key=r.failed_node_key,
                failed_node_type=r.failed_node_type,
                error_message=r.error_message,
                started_at=r.started_at,
                finished_at=r.finished_at,
                raw_object_id=int(r.raw_object_id) if r.raw_object_id else None,
                inbound_envelope_id=(
                    int(r.inbound_envelope_id) if r.inbound_envelope_id else None
                ),
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


# ---------------------------------------------------------------------------
# Phase 7 Wave 6 — outbox dispatch (manual trigger 우선)
# ---------------------------------------------------------------------------
class DispatchSummary(BaseModel):
    pending_before: int
    dispatched: int
    manual: int
    failed: int
    pending_after: int
    items: list[dict[str, Any]]


@router.post("/dispatch-pending", response_model=DispatchSummary)
async def dispatch_pending_envelopes(
    limit: int = Query(default=50, ge=1, le=500),
) -> DispatchSummary:
    """RECEIVED 상태의 inbound envelope 을 일괄 처리 → workflow trigger.

    Wave 6 의 manual 트리거 endpoint. 이후 Dramatiq actor 가 cron 으로 호출.
    """
    from app.domain.inbound_dispatch import (
        dispatch_received_envelopes,
        fetch_pending_envelope_count,
    )

    def _do() -> DispatchSummary:
        sm = get_sync_sessionmaker()
        with sm() as session:
            try:
                pending_before = fetch_pending_envelope_count(session)
                results = dispatch_received_envelopes(session, limit=limit)
                session.commit()
            except Exception:
                session.rollback()
                raise
        with sm() as session2:
            pending_after = fetch_pending_envelope_count(session2)

        dispatched = sum(1 for r in results if r.status == "dispatched")
        manual = sum(1 for r in results if r.status == "manual")
        failed = sum(1 for r in results if r.status == "failed")
        return DispatchSummary(
            pending_before=pending_before,
            dispatched=dispatched,
            manual=manual,
            failed=failed,
            pending_after=pending_after,
            items=[
                {
                    "envelope_id": r.envelope_id,
                    "channel_code": r.channel_code,
                    "workflow_id": r.workflow_id,
                    "pipeline_run_id": r.pipeline_run_id,
                    "status": r.status,
                    "error": r.error,
                }
                for r in results
            ],
        )

    return await asyncio.to_thread(_do)


__all__ = ["router"]
