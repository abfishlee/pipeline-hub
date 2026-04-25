"""run tables — ingest_job + event_outbox + processed_event + dead_letter

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-25 10:30:00+00:00

docs/03_DATA_MODEL.md 3.7 정합. pipeline_run/node_run 은 wf 함께 Phase 3 에 추가.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- run.ingest_job ---
    op.execute(
        """
        CREATE TABLE run.ingest_job (
            job_id            BIGSERIAL PRIMARY KEY,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            job_type          TEXT NOT NULL CHECK (
                job_type IN ('ON_DEMAND','SCHEDULED','RETRY','BACKFILL')
            ),
            status            TEXT NOT NULL DEFAULT 'PENDING' CHECK (
                status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED')
            ),
            requested_by      BIGINT REFERENCES ctl.app_user(user_id),
            parameters        JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at        TIMESTAMPTZ,
            finished_at       TIMESTAMPTZ,
            input_count       BIGINT DEFAULT 0,
            output_count      BIGINT DEFAULT 0,
            error_count       BIGINT DEFAULT 0,
            error_message     TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX run_ingest_job_source_created "
        "ON run.ingest_job (source_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX run_ingest_job_status "
        "ON run.ingest_job (status) WHERE status IN ('PENDING','RUNNING','FAILED');"
    )

    # --- run.event_outbox ---
    op.execute(
        """
        CREATE TABLE run.event_outbox (
            event_id          BIGSERIAL PRIMARY KEY,
            aggregate_type    TEXT NOT NULL,
            aggregate_id      TEXT NOT NULL,
            event_type        TEXT NOT NULL,
            payload_json      JSONB NOT NULL,
            status            TEXT NOT NULL DEFAULT 'PENDING' CHECK (
                status IN ('PENDING','PUBLISHED','FAILED')
            ),
            attempt_no        INT NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at      TIMESTAMPTZ,
            last_error        TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX run_event_outbox_pending "
        "ON run.event_outbox (created_at) WHERE status = 'PENDING';"
    )

    # --- run.processed_event (idempotent consumer marker) ---
    op.execute(
        """
        CREATE TABLE run.processed_event (
            event_id          TEXT PRIMARY KEY,
            consumer_name     TEXT NOT NULL,
            processed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX run_processed_event_consumer "
        "ON run.processed_event (consumer_name, processed_at);"
    )

    # --- run.dead_letter ---
    op.execute(
        """
        CREATE TABLE run.dead_letter (
            dl_id             BIGSERIAL PRIMARY KEY,
            origin            TEXT NOT NULL,
            payload_json      JSONB NOT NULL,
            error_message     TEXT,
            stack_trace       TEXT,
            failed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            replayed_at       TIMESTAMPTZ,
            replayed_by       BIGINT REFERENCES ctl.app_user(user_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run.dead_letter CASCADE;")
    op.execute("DROP TABLE IF EXISTS run.processed_event CASCADE;")
    op.execute("DROP TABLE IF EXISTS run.event_outbox CASCADE;")
    op.execute("DROP TABLE IF EXISTS run.ingest_job CASCADE;")
