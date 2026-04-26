"""Phase 5.2.8 STEP 11 — perf SLO + SQL Performance Coach + Backfill 통합 테스트.

검증:
  1. record_slo / summarize_slo — 10종 metric verdict.
  2. measure_db_baseline — DLQ + (옵션) pg_stat_statements.
  3. analyze_sql — OK / WARN / BLOCK 분기 + audit.sql_explain_log 적재.
  4. plan_chunks — chunk_unit 별 정확한 분할 + MAX_CHUNKS 가드.
  5. create_backfill_job + list_pending_chunks + mark_chunk_done +
     maybe_complete_job (1년치 365 chunks 시나리오 축소판).
  6. /v2/perf/slo + /summary + /baseline/measure + /coach/analyze endpoint.
  7. /v2/backfill CRUD endpoint.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.perf_guards import (
    BackfillJobSpec,
    PerfSloSample,
    analyze_sql,
    create_backfill_job,
    list_pending_chunks,
    mark_chunk_done,
    plan_chunks,
    record_slo,
    summarize_slo,
)
from app.domain.perf_guards.backfill import (
    BackfillError,
    BackfillStatus,
    maybe_complete_job,
    update_job_status,
)
from app.domain.perf_guards.slo import measure_db_baseline


@pytest.fixture
def cleanup_perf() -> Iterator[dict[str, list[Any]]]:
    state: dict[str, list[Any]] = {
        "slo_metrics": [],
        "job_ids": [],
        "tables": [],
    }
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        if state["slo_metrics"]:
            for m in state["slo_metrics"]:
                session.execute(
                    text(
                        "DELETE FROM audit.perf_slo "
                        "WHERE tags ->> 'test_marker' = :m"
                    ),
                    {"m": m},
                )
        if state["job_ids"]:
            session.execute(
                text(
                    "DELETE FROM ctl.backfill_chunk WHERE job_id = ANY(:ids)"
                ),
                {"ids": state["job_ids"]},
            )
            session.execute(
                text("DELETE FROM ctl.backfill_job WHERE job_id = ANY(:ids)"),
                {"ids": state["job_ids"]},
            )
        for t in state["tables"]:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        session.commit()
    dispose_sync_engine()


# ===========================================================================
# 1. SLO record + summarize
# ===========================================================================
def test_slo_record_and_summary(cleanup_perf: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    marker = secrets.token_hex(3)
    cleanup_perf["slo_metrics"].append(marker)
    with sm() as session:
        for v in (1_000, 2_500, 8_000):
            record_slo(
                session,
                PerfSloSample(
                    metric_code="ingest_p95_ms",
                    value=float(v),
                    unit="ms",
                    tags={"test_marker": marker},
                ),
            )
        session.commit()
    with sm() as session:
        summary = summarize_slo(
            session, metrics=["ingest_p95_ms"], window_minutes=60
        )
    assert any(s.metric_code == "ingest_p95_ms" for s in summary)
    ingest = next(s for s in summary if s.metric_code == "ingest_p95_ms")
    # 임계: warn=5_000, block=30_000. last=8_000 → WARN.
    assert ingest.last_value == 8_000
    assert ingest.verdict == "WARN"


def test_slo_block_threshold(cleanup_perf: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    marker = secrets.token_hex(3)
    cleanup_perf["slo_metrics"].append(marker)
    with sm() as session:
        record_slo(
            session,
            PerfSloSample(
                metric_code="dlq_pending_count",
                value=2_000.0,  # block=1_000.
                unit="count",
                tags={"test_marker": marker},
            ),
        )
        session.commit()
    with sm() as session:
        summary = summarize_slo(
            session, metrics=["dlq_pending_count"], window_minutes=10
        )
    dlq = next(s for s in summary if s.metric_code == "dlq_pending_count")
    assert dlq.verdict == "BLOCK"


def test_slo_unknown_metric_rejected() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session, pytest.raises(ValueError):
        record_slo(
            session,
            PerfSloSample(metric_code="invalid_metric", value=1.0, unit="x"),
        )


def test_measure_db_baseline_runs() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        samples = measure_db_baseline(session)
    assert "dlq_pending_count" in samples
    # pg_stat_statements 가 enable 안 되어 있을 수 있음 — 옵션.
    for s in samples.values():
        assert s.value >= 0


# ===========================================================================
# 2. SQL Performance Coach
# ===========================================================================
def test_coach_ok_simple_select() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        out = analyze_sql(
            session, sql="SELECT 1 WHERE 1=1 LIMIT 1", persist=False
        )
    assert out.verdict == "OK"


def test_coach_warns_on_unbounded_query() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        out = analyze_sql(
            session, sql="SELECT 1", persist=False
        )
    # WHERE/LIMIT 없음 → unbounded warning. SELECT 1 은 cost 낮으므로 WARN.
    assert out.verdict in ("WARN", "BLOCK")
    assert any("unbounded_query" in w for w in out.warnings)


def test_coach_blocks_invalid_sql() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        out = analyze_sql(session, sql="SELECT FROM WHERE", persist=False)
    assert out.verdict == "BLOCK"


def test_coach_persists_to_log(cleanup_perf: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    sql = f"SELECT 1 AS marker_{secrets.token_hex(3)}"
    with sm() as session:
        out = analyze_sql(session, sql=sql, persist=True)
        session.commit()
    assert out.verdict in ("OK", "WARN", "BLOCK")
    with sm() as session:
        cnt = session.execute(
            text(
                "SELECT COUNT(*) FROM audit.sql_explain_log "
                "WHERE sql_text_short = :s"
            ),
            {"s": sql[:500]},
        ).scalar_one()
    assert int(cnt) >= 1


# ===========================================================================
# 3. Backfill plan_chunks
# ===========================================================================
def test_plan_chunks_day_unit() -> None:
    spec = BackfillJobSpec(
        domain_code="agri",
        resource_code="PRICE_FACT",
        target_table="mart.price_fact",
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 8, tzinfo=UTC),
        chunk_unit="day",
        chunk_size=1,
    )
    chunks = plan_chunks(spec)
    assert len(chunks) == 7
    assert chunks[0] == (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )


def test_plan_chunks_too_many_rejected() -> None:
    spec = BackfillJobSpec(
        domain_code="agri",
        resource_code="X",
        target_table="mart.x",
        start_at=datetime(2000, 1, 1, tzinfo=UTC),
        end_at=datetime(2050, 1, 1, tzinfo=UTC),
        chunk_unit="hour",
        chunk_size=1,
    )
    with pytest.raises(BackfillError):
        plan_chunks(spec)


# ===========================================================================
# 4. Backfill e2e — 7-day plan + complete chunks
# ===========================================================================
def test_backfill_e2e_complete(cleanup_perf: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    spec = BackfillJobSpec(
        domain_code="agri",
        resource_code="PRICE_FACT",
        target_table="mart.price_fact",
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 4, tzinfo=UTC),
        chunk_unit="day",
        chunk_size=1,
        max_parallel_runs=2,
    )
    with sm() as session:
        job_id, n = create_backfill_job(session, spec, requested_by=None)
        session.commit()
    cleanup_perf["job_ids"].append(job_id)
    assert n == 3
    with sm() as session:
        update_job_status(session, job_id=job_id, status=BackfillStatus.RUNNING)
        pending = list_pending_chunks(session, job_id=job_id)
        session.commit()
    assert len(pending) == 3

    with sm() as session:
        for c in pending:
            mark_chunk_done(
                session,
                chunk_id=c.chunk_id,
                success=True,
                rows_processed=1_000,
                checkpoint={"last_id": c.chunk_index * 1000},
            )
        final_status = maybe_complete_job(session, job_id=job_id)
        session.commit()
    assert final_status == "COMPLETED"

    with sm() as session:
        row = session.execute(
            text(
                "SELECT total_chunks, completed_chunks, failed_chunks, status "
                "FROM ctl.backfill_job WHERE job_id = :j"
            ),
            {"j": job_id},
        ).first()
    assert row is not None
    assert row.total_chunks == 3
    assert row.completed_chunks == 3
    assert row.status == "COMPLETED"


def test_backfill_partial_failure(cleanup_perf: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    spec = BackfillJobSpec(
        domain_code="agri",
        resource_code="X",
        target_table="mart.x",
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 3, tzinfo=UTC),
        chunk_unit="day",
        chunk_size=1,
    )
    with sm() as session:
        job_id, _ = create_backfill_job(session, spec)
        session.commit()
    cleanup_perf["job_ids"].append(job_id)
    with sm() as session:
        pending = list_pending_chunks(session, job_id=job_id)
        # 1번째 성공, 2번째 실패.
        mark_chunk_done(
            session, chunk_id=pending[0].chunk_id, success=True, rows_processed=10
        )
        mark_chunk_done(
            session,
            chunk_id=pending[1].chunk_id,
            success=False,
            error_message="simulated",
        )
        final = maybe_complete_job(session, job_id=job_id)
        session.commit()
    assert final == "FAILED"


# ===========================================================================
# 5. /v2/perf endpoint
# ===========================================================================
def test_perf_record_and_summary_endpoint(  # type: ignore[no-untyped-def]
    it_client, admin_auth, cleanup_perf: dict[str, list[Any]]
) -> None:
    marker = secrets.token_hex(3)
    cleanup_perf["slo_metrics"].append(marker)
    r = it_client.post(
        "/v2/perf/slo",
        json={
            "metric_code": "ingest_p95_ms",
            "value": 120.5,
            "unit": "ms",
            "tags": {"test_marker": marker},
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    assert r.json()["slo_id"] > 0

    r2 = it_client.get(
        "/v2/perf/slo/summary?window_minutes=10", headers=admin_auth
    )
    assert r2.status_code == 200
    body = r2.json()
    assert any(s["metric_code"] == "ingest_p95_ms" for s in body)


def test_perf_baseline_measure_endpoint(  # type: ignore[no-untyped-def]
    it_client, admin_auth
) -> None:
    r = it_client.post("/v2/perf/baseline/measure", headers=admin_auth)
    assert r.status_code == 200
    body = r.json()
    assert body["measured_count"] >= 1
    assert "dlq_pending_count" in body["metrics"]


def test_perf_coach_endpoint(it_client, admin_auth) -> None:  # type: ignore[no-untyped-def]
    r = it_client.post(
        "/v2/perf/coach/analyze",
        json={"sql": "SELECT 1 WHERE 1=1 LIMIT 1"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] in ("OK", "WARN")


# ===========================================================================
# 6. /v2/backfill endpoint
# ===========================================================================
def test_backfill_endpoint_create_and_progress(  # type: ignore[no-untyped-def]
    it_client, admin_auth, cleanup_perf: dict[str, list[Any]]
) -> None:
    r = it_client.post(
        "/v2/backfill",
        json={
            "domain_code": "agri",
            "resource_code": "PRICE_FACT",
            "target_table": "mart.price_fact",
            "start_at": "2026-01-01T00:00:00+00:00",
            "end_at": "2026-01-03T00:00:00+00:00",
            "chunk_unit": "day",
            "chunk_size": 1,
            "max_parallel_runs": 2,
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    job_body = r.json()
    cleanup_perf["job_ids"].append(int(job_body["job_id"]))
    assert job_body["total_chunks"] == 2
    assert job_body["status"] == "PENDING"

    r2 = it_client.get(
        f"/v2/backfill/{job_body['job_id']}/chunks", headers=admin_auth
    )
    assert r2.status_code == 200
    assert len(r2.json()) == 2
