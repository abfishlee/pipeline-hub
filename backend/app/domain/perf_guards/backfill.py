"""Phase 5.2.8 STEP 11 — Backfill chunk + checkpoint/resume + parallel 가드 (Q4).

Default (Q4 추천):
  chunk_unit              = day
  chunk_size              = 1
  max_parallel_runs       = 2
  batch_size              = 5_000
  statement_timeout_ms    = 60_000
  lock_timeout_ms         = 3_000
  sleep_between_chunks_ms = 1_000

흐름:
  1. create_backfill_job(spec) → ctl.backfill_job 1행 + plan_chunks 자동 생성.
  2. worker 가 list_pending_chunks 로 N개 (max_parallel) 잡고 SQL 실행.
  3. 각 chunk 종료 시 mark_chunk_done(checkpoint_json) → resume 가능.
  4. 모든 chunk 완료 → update_job_status(COMPLETED).

가드:
  * window 1년치 = 365 chunks. 너무 큰 plan 은 caller 가 거부 (10_000 chunk 한도).
  * pending chunk 가 *parallel* 만 허용 — over-pickup 차단은 worker 책임 (advisory lock).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


MAX_CHUNKS_PER_JOB: Final[int] = 10_000


class BackfillStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BackfillError(ValueError):
    pass


@dataclass(slots=True)
class BackfillJobSpec:
    domain_code: str
    resource_code: str
    target_table: str
    start_at: datetime
    end_at: datetime
    chunk_unit: str = "day"  # 'hour' / 'day' / 'week' / 'month'
    chunk_size: int = 1
    batch_size: int = 5_000
    max_parallel_runs: int = 2
    statement_timeout_ms: int = 60_000
    lock_timeout_ms: int = 3_000
    sleep_between_chunks_ms: int = 1_000
    sql_template: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BackfillChunkSpec:
    chunk_id: int
    job_id: int
    chunk_index: int
    chunk_start: datetime
    chunk_end: datetime
    attempts: int = 0
    status: str = "PENDING"


def _chunk_delta(unit: str, size: int) -> timedelta:
    if unit == "hour":
        return timedelta(hours=size)
    if unit == "day":
        return timedelta(days=size)
    if unit == "week":
        return timedelta(weeks=size)
    if unit == "month":
        return timedelta(days=size * 30)  # 근사 — exact 는 caller 가 chunk_unit='day'.
    raise BackfillError(f"unsupported chunk_unit: {unit!r}")


def plan_chunks(spec: BackfillJobSpec) -> list[tuple[datetime, datetime]]:
    """spec 의 [start_at, end_at] 을 chunk_unit × chunk_size 단위로 분할.

    마지막 chunk 는 end_at 으로 잘림. 총 chunks > MAX_CHUNKS_PER_JOB 이면 BackfillError.
    """
    if spec.start_at >= spec.end_at:
        raise BackfillError("start_at must be < end_at")
    delta = _chunk_delta(spec.chunk_unit, spec.chunk_size)
    if delta.total_seconds() <= 0:
        raise BackfillError("chunk_unit/chunk_size produces non-positive delta")

    chunks: list[tuple[datetime, datetime]] = []
    cursor = spec.start_at
    while cursor < spec.end_at:
        next_cursor = min(cursor + delta, spec.end_at)
        chunks.append((cursor, next_cursor))
        cursor = next_cursor
        if len(chunks) > MAX_CHUNKS_PER_JOB:
            raise BackfillError(
                f"plan would produce > {MAX_CHUNKS_PER_JOB} chunks; "
                "use larger chunk_size"
            )
    return chunks


def create_backfill_job(
    session: Session,
    spec: BackfillJobSpec,
    *,
    requested_by: int | None = None,
) -> tuple[int, int]:
    """ctl.backfill_job 1 row + ctl.backfill_chunk N rows. (job_id, chunk_count) 반환."""
    chunks = plan_chunks(spec)
    import json as _json

    job_id = session.execute(
        text(
            "INSERT INTO ctl.backfill_job "
            "(domain_code, resource_code, target_table, start_at, end_at, "
            " chunk_unit, chunk_size, batch_size, max_parallel_runs, "
            " statement_timeout_ms, lock_timeout_ms, sleep_between_chunks_ms, "
            " status, total_chunks, sql_template, extra, requested_by) "
            "VALUES (:d, :r, :tt, :sa, :ea, :cu, :cs, :bs, :mp, :st, :lt, "
            "        :sl, 'PENDING', :tc, :tpl, CAST(:ext AS JSONB), :rb) "
            "RETURNING job_id"
        ),
        {
            "d": spec.domain_code,
            "r": spec.resource_code,
            "tt": spec.target_table,
            "sa": spec.start_at,
            "ea": spec.end_at,
            "cu": spec.chunk_unit,
            "cs": spec.chunk_size,
            "bs": spec.batch_size,
            "mp": spec.max_parallel_runs,
            "st": spec.statement_timeout_ms,
            "lt": spec.lock_timeout_ms,
            "sl": spec.sleep_between_chunks_ms,
            "tc": len(chunks),
            "tpl": spec.sql_template,
            "ext": _json.dumps(spec.extra, default=str),
            "rb": requested_by,
        },
    ).scalar_one()

    insert_chunk = text(
        "INSERT INTO ctl.backfill_chunk "
        "(job_id, chunk_index, chunk_start, chunk_end) "
        "VALUES (:j, :i, :s, :e)"
    )
    for idx, (s, e) in enumerate(chunks):
        session.execute(insert_chunk, {"j": int(job_id), "i": idx, "s": s, "e": e})

    return int(job_id), len(chunks)


def list_pending_chunks(
    session: Session, *, job_id: int, limit: int | None = None
) -> list[BackfillChunkSpec]:
    sql = (
        "SELECT chunk_id, job_id, chunk_index, chunk_start, chunk_end, "
        "       attempts, status FROM ctl.backfill_chunk "
        "WHERE job_id = :j AND status = 'PENDING' "
        "ORDER BY chunk_index "
    )
    params: dict[str, Any] = {"j": job_id}
    if limit:
        sql += "LIMIT :lim"
        params["lim"] = int(limit)
    rows = session.execute(text(sql), params).all()
    return [
        BackfillChunkSpec(
            chunk_id=int(r.chunk_id),
            job_id=int(r.job_id),
            chunk_index=int(r.chunk_index),
            chunk_start=r.chunk_start,
            chunk_end=r.chunk_end,
            attempts=int(r.attempts),
            status=str(r.status),
        )
        for r in rows
    ]


def mark_chunk_done(
    session: Session,
    *,
    chunk_id: int,
    success: bool,
    rows_processed: int = 0,
    error_message: str | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    import json as _json

    new_status = "SUCCESS" if success else "FAILED"
    session.execute(
        text(
            "UPDATE ctl.backfill_chunk SET "
            "  status = :st, "
            "  attempts = attempts + 1, "
            "  rows_processed = :rp, "
            "  error_message = :em, "
            "  checkpoint_json = CAST(:ck AS JSONB), "
            "  completed_at = now() "
            "WHERE chunk_id = :c"
        ),
        {
            "st": new_status,
            "rp": int(rows_processed),
            "em": error_message,
            "ck": _json.dumps(dict(checkpoint or {}), default=str),
            "c": int(chunk_id),
        },
    )
    # job 의 carry counter 업데이트.
    if success:
        session.execute(
            text(
                "UPDATE ctl.backfill_job SET "
                "  completed_chunks = completed_chunks + 1 "
                "WHERE job_id = (SELECT job_id FROM ctl.backfill_chunk "
                "                WHERE chunk_id = :c)"
            ),
            {"c": int(chunk_id)},
        )
    else:
        session.execute(
            text(
                "UPDATE ctl.backfill_job SET "
                "  failed_chunks = failed_chunks + 1 "
                "WHERE job_id = (SELECT job_id FROM ctl.backfill_chunk "
                "                WHERE chunk_id = :c)"
            ),
            {"c": int(chunk_id)},
        )


def update_job_status(
    session: Session, *, job_id: int, status: BackfillStatus
) -> None:
    if status not in BackfillStatus:
        raise BackfillError(f"invalid status: {status}")
    set_started = (
        ", started_at = COALESCE(started_at, now())"
        if status == BackfillStatus.RUNNING
        else ""
    )
    set_completed = (
        ", completed_at = now()"
        if status in (BackfillStatus.COMPLETED, BackfillStatus.FAILED, BackfillStatus.CANCELLED)
        else ""
    )
    session.execute(
        text(
            f"UPDATE ctl.backfill_job SET status = :s{set_started}{set_completed} "
            f"WHERE job_id = :j"
        ),
        {"s": status.value, "j": int(job_id)},
    )


def maybe_complete_job(session: Session, *, job_id: int) -> str:
    """모든 chunk 가 SUCCESS 면 COMPLETED 로 자동 전환. status 반환."""
    counts = session.execute(
        text(
            "SELECT total_chunks, completed_chunks, failed_chunks, status "
            "FROM ctl.backfill_job WHERE job_id = :j"
        ),
        {"j": int(job_id)},
    ).first()
    if counts is None:
        raise BackfillError(f"job {job_id} not found")
    total = int(counts.total_chunks)
    done = int(counts.completed_chunks)
    failed = int(counts.failed_chunks)
    if done >= total:
        update_job_status(session, job_id=job_id, status=BackfillStatus.COMPLETED)
        return BackfillStatus.COMPLETED.value
    if failed > 0 and (done + failed) >= total:
        # 일부 chunk 실패 + 더 이상 pending 없음 → FAILED.
        update_job_status(session, job_id=job_id, status=BackfillStatus.FAILED)
        return BackfillStatus.FAILED.value
    return str(counts.status)


__all__ = [
    "MAX_CHUNKS_PER_JOB",
    "BackfillChunkSpec",
    "BackfillError",
    "BackfillJobSpec",
    "BackfillStatus",
    "create_backfill_job",
    "list_pending_chunks",
    "mark_chunk_done",
    "maybe_complete_job",
    "plan_chunks",
    "update_job_status",
]
