"""Phase 5.2.8 STEP 11 — 성능 & 확장성 5축 가드레일.

5축:
  1. **수집** (`source_throttle`) — poll_interval / batch_size / rate_limit_per_min /
     max_concurrency. 본 모듈은 *기본값 + validate*. 실 적용은 ingest_worker.
  2. **Worker/Queue** (`worker_routing`) — domain/source 별 queue routing helper.
  3. **DB/Schema** (`db_advisor`) — partition / JSONB linter / row_size 추정.
  4. **DQ/SQL** (`sql_coach`) — EXPLAIN 수집 + seq scan / unbounded query 등 검사
     (Q3 backend only).
  5. **Backfill** (`backfill`) — chunk + checkpoint/resume + parallel 가드 (Q4).
"""

from __future__ import annotations

from app.domain.perf_guards.backfill import (
    BackfillChunkSpec,
    BackfillJobSpec,
    BackfillStatus,
    create_backfill_job,
    list_pending_chunks,
    mark_chunk_done,
    plan_chunks,
    update_job_status,
)
from app.domain.perf_guards.slo import (
    SLO_DEFAULTS,
    PerfSloSample,
    record_slo,
    summarize_slo,
)
from app.domain.perf_guards.sql_coach import (
    CoachVerdict,
    SqlCoachOutcome,
    analyze_sql,
)

__all__ = [
    "SLO_DEFAULTS",
    "BackfillChunkSpec",
    "BackfillJobSpec",
    "BackfillStatus",
    "CoachVerdict",
    "PerfSloSample",
    "SqlCoachOutcome",
    "analyze_sql",
    "create_backfill_job",
    "list_pending_chunks",
    "mark_chunk_done",
    "plan_chunks",
    "record_slo",
    "summarize_slo",
    "update_job_status",
]
