"""Phase 5.2.8 STEP 11 — 성능 SLO baseline + Backfill 인프라.

Revision ID: 0045
Revises: 0044
Create Date: 2026-04-27 07:00:00+00:00

배경 (STEP 11 답변):

  Q1. baseline 미측정 → 본 STEP 의 첫 작업으로 자동 측정 + audit.perf_slo 적재.
       7+3 = 10종 SLO.
  Q2. Kafka 미도입. ADR-0020 으로 도입 트리거만 명시.
  Q3. Performance Coach backend 만 — sql_explain_log 테이블에 검사 결과 저장.
       UI 는 Phase 6.
  Q4. backfill default — chunk_unit=day, chunk_size=1d, max_parallel=2,
       batch_size=5000~10000. checkpoint resume 필수.

테이블:
  audit.perf_slo            — 10종 SLO 측정값 시계열
  audit.sql_explain_log     — Performance Coach 의 EXPLAIN/검사 결과
  ctl.backfill_job          — backfill 잡 헤더
  ctl.backfill_chunk        — chunk 단위 진행 + checkpoint
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # audit.perf_slo
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE audit.perf_slo (
            slo_id         BIGSERIAL PRIMARY KEY,
            metric_code    TEXT NOT NULL,
            domain_code    TEXT,
            value_num      DOUBLE PRECISION NOT NULL,
            unit           TEXT NOT NULL,
            sample_count   INTEGER NOT NULL DEFAULT 0,
            window_seconds INTEGER NOT NULL DEFAULT 60,
            tags           JSONB NOT NULL DEFAULT '{}'::jsonb,
            measured_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_perf_slo_metric_code CHECK (
                metric_code IN (
                    'ingest_p95_ms',
                    'raw_insert_throughput_per_sec',
                    'redis_lag_ms',
                    'sse_delay_ms',
                    'sql_preview_p95_ms',
                    'dq_custom_sql_p95_ms',
                    'backfill_chunk_duration_ms',
                    'db_query_p95_ms',
                    'worker_job_duration_p95_ms',
                    'dlq_pending_count'
                )
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_perf_slo_lookup "
        "ON audit.perf_slo (metric_code, measured_at DESC);"
    )
    op.execute(
        "CREATE INDEX audit_perf_slo_domain "
        "ON audit.perf_slo (domain_code, metric_code, measured_at DESC) "
        "WHERE domain_code IS NOT NULL;"
    )
    op.execute(
        "GRANT SELECT, INSERT ON audit.perf_slo TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE audit.perf_slo_slo_id_seq TO app_rw;"
    )

    # ------------------------------------------------------------------
    # audit.sql_explain_log — Performance Coach (Q3 backend)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE audit.sql_explain_log (
            log_id          BIGSERIAL PRIMARY KEY,
            domain_code     TEXT,
            sql_hash        TEXT NOT NULL,
            sql_text_short  TEXT NOT NULL,
            verdict         TEXT NOT NULL,
            warnings        TEXT[] NOT NULL DEFAULT '{}',
            explain_json    JSONB,
            estimated_rows  BIGINT,
            estimated_cost  DOUBLE PRECISION,
            scanned_relations TEXT[] NOT NULL DEFAULT '{}',
            requested_by    BIGINT REFERENCES ctl.app_user(user_id),
            requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sql_explain_verdict CHECK (
                verdict IN ('OK','WARN','BLOCK')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_sql_explain_recent "
        "ON audit.sql_explain_log (requested_at DESC);"
    )
    op.execute(
        "CREATE INDEX audit_sql_explain_verdict "
        "ON audit.sql_explain_log (verdict, requested_at DESC) "
        "WHERE verdict <> 'OK';"
    )
    op.execute(
        "GRANT SELECT, INSERT ON audit.sql_explain_log TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE audit.sql_explain_log_log_id_seq TO app_rw;"
    )

    # ------------------------------------------------------------------
    # ctl.backfill_job + ctl.backfill_chunk (Q4)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ctl.backfill_job (
            job_id              BIGSERIAL PRIMARY KEY,
            domain_code         TEXT NOT NULL,
            resource_code       TEXT NOT NULL,
            target_table        TEXT NOT NULL,
            start_at            TIMESTAMPTZ NOT NULL,
            end_at              TIMESTAMPTZ NOT NULL,
            chunk_unit          TEXT NOT NULL DEFAULT 'day',
            chunk_size          INTEGER NOT NULL DEFAULT 1,
            batch_size          INTEGER NOT NULL DEFAULT 5000,
            max_parallel_runs   INTEGER NOT NULL DEFAULT 2,
            statement_timeout_ms INTEGER NOT NULL DEFAULT 60000,
            lock_timeout_ms     INTEGER NOT NULL DEFAULT 3000,
            sleep_between_chunks_ms INTEGER NOT NULL DEFAULT 1000,
            status              TEXT NOT NULL DEFAULT 'PENDING',
            total_chunks        INTEGER NOT NULL DEFAULT 0,
            completed_chunks    INTEGER NOT NULL DEFAULT 0,
            failed_chunks       INTEGER NOT NULL DEFAULT 0,
            requested_by        BIGINT REFERENCES ctl.app_user(user_id),
            sql_template        TEXT,
            extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
            requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            CONSTRAINT ck_backfill_job_chunk_unit CHECK (
                chunk_unit IN ('hour','day','week','month')
            ),
            CONSTRAINT ck_backfill_job_status CHECK (
                status IN ('PENDING','RUNNING','PAUSED','COMPLETED','FAILED','CANCELLED')
            ),
            CONSTRAINT ck_backfill_job_window CHECK (start_at <= end_at)
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_backfill_job_recent "
        "ON ctl.backfill_job (requested_at DESC);"
    )
    op.execute(
        "CREATE INDEX ctl_backfill_job_status "
        "ON ctl.backfill_job (status, requested_at DESC);"
    )

    op.execute(
        """
        CREATE TABLE ctl.backfill_chunk (
            chunk_id        BIGSERIAL PRIMARY KEY,
            job_id          BIGINT NOT NULL REFERENCES ctl.backfill_job(job_id)
                            ON DELETE CASCADE,
            chunk_index     INTEGER NOT NULL,
            chunk_start     TIMESTAMPTZ NOT NULL,
            chunk_end       TIMESTAMPTZ NOT NULL,
            status          TEXT NOT NULL DEFAULT 'PENDING',
            attempts        INTEGER NOT NULL DEFAULT 0,
            rows_processed  BIGINT NOT NULL DEFAULT 0,
            error_message   TEXT,
            checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            CONSTRAINT uq_backfill_chunk_job_idx UNIQUE (job_id, chunk_index),
            CONSTRAINT ck_backfill_chunk_status CHECK (
                status IN ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_backfill_chunk_pending "
        "ON ctl.backfill_chunk (job_id, chunk_index) "
        "WHERE status = 'PENDING';"
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON ctl.backfill_job TO app_rw; "
        "GRANT SELECT, INSERT, UPDATE ON ctl.backfill_chunk TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE ctl.backfill_job_job_id_seq TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE ctl.backfill_chunk_chunk_id_seq TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ctl.backfill_chunk CASCADE;")
    op.execute("DROP TABLE IF EXISTS ctl.backfill_job CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.sql_explain_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.perf_slo CASCADE;")
