"""Phase 5.2.8 STEP 11 — SLO baseline 측정 + 7+3종 자동 적재.

10종 SLO (Q1):
  ingest_p95_ms / raw_insert_throughput_per_sec / redis_lag_ms / sse_delay_ms /
  sql_preview_p95_ms / dq_custom_sql_p95_ms / backfill_chunk_duration_ms +
  db_query_p95_ms / worker_job_duration_p95_ms / dlq_pending_count.

본 모듈은 *측정 + 적재* 만. 실 측정값은 prometheus 또는 application middleware 가
계산해 record_slo() 호출.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


VALID_METRICS: Final[tuple[str, ...]] = (
    "ingest_p95_ms",
    "raw_insert_throughput_per_sec",
    "redis_lag_ms",
    "sse_delay_ms",
    "sql_preview_p95_ms",
    "dq_custom_sql_p95_ms",
    "backfill_chunk_duration_ms",
    "db_query_p95_ms",
    "worker_job_duration_p95_ms",
    "dlq_pending_count",
)


# 임계값 default (Q1 — 10만~30만 rows/일 baseline 가정).
SLO_DEFAULTS: Final[dict[str, dict[str, float]]] = {
    "ingest_p95_ms": {"warn": 5_000, "block": 30_000},
    "raw_insert_throughput_per_sec": {"warn": 50, "block": 10},  # 낮을수록 위험.
    "redis_lag_ms": {"warn": 5_000, "block": 60_000},
    "sse_delay_ms": {"warn": 3_000, "block": 15_000},
    "sql_preview_p95_ms": {"warn": 2_000, "block": 10_000},
    "dq_custom_sql_p95_ms": {"warn": 5_000, "block": 30_000},
    "backfill_chunk_duration_ms": {"warn": 60_000, "block": 300_000},
    "db_query_p95_ms": {"warn": 1_000, "block": 5_000},
    "worker_job_duration_p95_ms": {"warn": 30_000, "block": 120_000},
    "dlq_pending_count": {"warn": 100, "block": 1_000},
}


@dataclass(slots=True, frozen=True)
class PerfSloSample:
    metric_code: str
    value: float
    unit: str
    domain_code: str | None = None
    sample_count: int = 0
    window_seconds: int = 60
    tags: dict[str, Any] = field(default_factory=dict)


def record_slo(
    session: Session,
    sample: PerfSloSample,
    *,
    measured_at: datetime | None = None,
) -> int:
    """audit.perf_slo 1행 INSERT. metric_code 검증."""
    if sample.metric_code not in VALID_METRICS:
        raise ValueError(f"unknown metric_code: {sample.metric_code}")
    when = measured_at or datetime.now(UTC)
    import json as _json

    sid = session.execute(
        text(
            "INSERT INTO audit.perf_slo "
            "(metric_code, domain_code, value_num, unit, sample_count, "
            " window_seconds, tags, measured_at) "
            "VALUES (:m, :d, :v, :u, :sc, :ws, CAST(:t AS JSONB), :ts) "
            "RETURNING slo_id"
        ),
        {
            "m": sample.metric_code,
            "d": sample.domain_code,
            "v": float(sample.value),
            "u": sample.unit,
            "sc": int(sample.sample_count),
            "ws": int(sample.window_seconds),
            "t": _json.dumps(sample.tags, default=str),
            "ts": when,
        },
    ).scalar_one()
    return int(sid)


@dataclass(slots=True)
class SloSummary:
    metric_code: str
    domain_code: str | None
    last_value: float | None
    avg_value: float | None
    max_value: float | None
    sample_count: int
    verdict: str  # OK / WARN / BLOCK


def _verdict_for(metric_code: str, value: float) -> str:
    th = SLO_DEFAULTS.get(metric_code)
    if not th:
        return "OK"
    warn = th["warn"]
    block = th["block"]
    # raw_insert_throughput 은 *낮을수록 위험* (역방향).
    if metric_code == "raw_insert_throughput_per_sec":
        if value <= block:
            return "BLOCK"
        if value <= warn:
            return "WARN"
        return "OK"
    if value >= block:
        return "BLOCK"
    if value >= warn:
        return "WARN"
    return "OK"


def summarize_slo(
    session: Session,
    *,
    metrics: Iterable[str] | None = None,
    domain_code: str | None = None,
    window_minutes: int = 60,
) -> list[SloSummary]:
    """지난 window 동안의 metric 별 last/avg/max + verdict."""
    metric_filter = list(metrics) if metrics else list(VALID_METRICS)
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)
    sql = (
        "SELECT metric_code, domain_code, "
        "       AVG(value_num) AS avg_v, "
        "       MAX(value_num) AS max_v, "
        "       COUNT(*) AS cnt, "
        "       (ARRAY_AGG(value_num ORDER BY measured_at DESC))[1] AS last_v "
        "FROM audit.perf_slo "
        "WHERE metric_code = ANY(:metrics) AND measured_at >= :ts "
    )
    params: dict[str, Any] = {"metrics": metric_filter, "ts": since}
    if domain_code is not None:
        sql += "AND (domain_code = :d OR domain_code IS NULL) "
        params["d"] = domain_code
    sql += "GROUP BY metric_code, domain_code ORDER BY metric_code, domain_code NULLS FIRST"
    rows = session.execute(text(sql), params).all()
    out: list[SloSummary] = []
    for r in rows:
        last = float(r.last_v) if r.last_v is not None else None
        verdict = _verdict_for(str(r.metric_code), last) if last is not None else "OK"
        out.append(
            SloSummary(
                metric_code=str(r.metric_code),
                domain_code=str(r.domain_code) if r.domain_code else None,
                last_value=last,
                avg_value=float(r.avg_v) if r.avg_v is not None else None,
                max_value=float(r.max_v) if r.max_v is not None else None,
                sample_count=int(r.cnt),
                verdict=verdict,
            )
        )
    return out


def measure_db_baseline(session: Session) -> dict[str, PerfSloSample]:
    """DB 에서 직접 읽을 수 있는 baseline metric 자동 측정 (Q1).

    측정 가능한 metric:
      - dlq_pending_count   = run.dead_letter 의 미처리 row 수
      - redis_lag_ms        = (별도 Redis 측정 필요 — 본 모듈은 0 placeholder)
      - db_query_p95_ms     = pg_stat_statements 가 있으면 p95, 없으면 0

    다른 metric (ingest/sse/sql_preview 등) 은 application middleware 가 별도 측정.
    """
    out: dict[str, PerfSloSample] = {}

    dlq = session.execute(
        text(
            "SELECT COUNT(*) FROM run.dead_letter "
            "WHERE replayed_at IS NULL"
        )
    ).scalar_one()
    out["dlq_pending_count"] = PerfSloSample(
        metric_code="dlq_pending_count",
        value=float(dlq),
        unit="count",
        sample_count=int(dlq),
        window_seconds=0,
    )

    # pg_stat_statements 가 enable 되어 있으면 db_query_p95.
    # SAVEPOINT 로 감싸 — extension 미설치 시 outer transaction 살림.
    p95 = None
    try:
        with session.begin_nested():
            p95 = session.execute(
                text(
                    "SELECT percentile_cont(0.95) WITHIN GROUP "
                    "(ORDER BY mean_exec_time) FROM pg_stat_statements"
                )
            ).scalar_one_or_none()
    except Exception:
        p95 = None
    if p95 is not None:
        out["db_query_p95_ms"] = PerfSloSample(
            metric_code="db_query_p95_ms",
            value=float(p95),
            unit="ms",
            window_seconds=60,
        )

    return out


def record_baseline_batch(
    session: Session, samples: Mapping[str, PerfSloSample]
) -> int:
    n = 0
    for s in samples.values():
        record_slo(session, s)
        n += 1
    return n


__all__ = [
    "SLO_DEFAULTS",
    "VALID_METRICS",
    "PerfSloSample",
    "SloSummary",
    "measure_db_baseline",
    "record_baseline_batch",
    "record_slo",
    "summarize_slo",
]
