"""Remove Mock API feature.

Revision ID: 0055
Revises: 0054
Create Date: 2026-04-28 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ctl.mock_api_endpoint CASCADE;")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ctl.mock_api_endpoint (
            mock_id          BIGSERIAL PRIMARY KEY,
            code             TEXT NOT NULL UNIQUE,
            name             TEXT NOT NULL,
            description      TEXT,
            response_format  TEXT NOT NULL DEFAULT 'json',
            response_body    TEXT NOT NULL,
            response_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
            status_code      INT NOT NULL DEFAULT 200,
            delay_ms         INT NOT NULL DEFAULT 0,
            is_active        BOOLEAN NOT NULL DEFAULT TRUE,
            call_count       BIGINT NOT NULL DEFAULT 0,
            last_called_at   TIMESTAMPTZ,
            created_by       BIGINT REFERENCES ctl.app_user(user_id),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_mock_api_format
                CHECK (response_format IN ('json','xml','csv','tsv','text')),
            CONSTRAINT ck_mock_api_status
                CHECK (status_code BETWEEN 100 AND 599),
            CONSTRAINT ck_mock_api_code_format
                CHECK (code ~ '^[a-z][a-z0-9_]{1,62}$'),
            CONSTRAINT ck_mock_api_delay
                CHECK (delay_ms BETWEEN 0 AND 30000)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mock_api_active "
        "ON ctl.mock_api_endpoint (is_active, code);"
    )
