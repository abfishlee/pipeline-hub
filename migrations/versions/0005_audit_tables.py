"""audit tables — access_log (PARTITIONED) + sql_execution_log + download_log

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-25 11:00:00+00:00

docs/03_DATA_MODEL.md 3.9 정합.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- audit.access_log (PARTITION BY RANGE on occurred_at) ---
    op.execute(
        """
        CREATE TABLE audit.access_log (
            log_id            BIGSERIAL,
            user_id           BIGINT REFERENCES ctl.app_user(user_id),
            api_key_id        BIGINT REFERENCES ctl.api_key(api_key_id),
            method            TEXT NOT NULL,
            path              TEXT NOT NULL,
            status_code       INT,
            ip                INET,
            user_agent        TEXT,
            duration_ms       INT,
            request_id        TEXT,
            occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_access_log PRIMARY KEY (log_id, occurred_at)
        ) PARTITION BY RANGE (occurred_at);
        """
    )
    op.execute(
        """
        CREATE TABLE audit.access_log_2026_04 PARTITION OF audit.access_log
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
        """
    )
    op.execute(
        "CREATE INDEX audit_access_log_user_time "
        "ON audit.access_log (user_id, occurred_at DESC);"
    )

    # --- audit.sql_execution_log ---
    op.execute(
        """
        CREATE TABLE audit.sql_execution_log (
            sql_log_id        BIGSERIAL PRIMARY KEY,
            user_id           BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
            sql_text          TEXT NOT NULL,
            sql_hash          TEXT NOT NULL,
            execution_kind    TEXT NOT NULL CHECK (
                execution_kind IN ('PREVIEW','SANDBOX','APPROVED','SCHEDULED')
            ),
            target_schema     TEXT,
            approved_by       BIGINT REFERENCES ctl.app_user(user_id),
            approved_at       TIMESTAMPTZ,
            started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at       TIMESTAMPTZ,
            row_count         BIGINT,
            status            TEXT NOT NULL CHECK (
                status IN ('SUCCESS','FAILED','BLOCKED','PENDING_APPROVAL')
            ),
            error_message     TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_sql_log_user_time "
        "ON audit.sql_execution_log (user_id, started_at DESC);"
    )

    # --- audit.download_log ---
    op.execute(
        """
        CREATE TABLE audit.download_log (
            download_id       BIGSERIAL PRIMARY KEY,
            user_id           BIGINT REFERENCES ctl.app_user(user_id),
            api_key_id        BIGINT REFERENCES ctl.api_key(api_key_id),
            resource_kind     TEXT NOT NULL,
            resource_ref      TEXT NOT NULL,
            byte_count        BIGINT,
            occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.download_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.sql_execution_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.access_log_2026_04 CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.access_log CASCADE;")
