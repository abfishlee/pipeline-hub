"""Move collection schedule ownership to workflow jobs.

Revision ID: 0056
Revises: 0055
Create Date: 2026-04-28 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS domain.domain_public_api_connector_schedule;")
    op.execute("ALTER TABLE domain.public_api_connector DROP COLUMN IF EXISTS schedule_enabled;")
    op.execute("ALTER TABLE domain.public_api_connector DROP COLUMN IF EXISTS schedule_cron;")


def downgrade() -> None:
    op.execute("ALTER TABLE domain.public_api_connector ADD COLUMN IF NOT EXISTS schedule_cron TEXT;")
    op.execute(
        "ALTER TABLE domain.public_api_connector "
        "ADD COLUMN IF NOT EXISTS schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS domain_public_api_connector_schedule "
        "ON domain.public_api_connector (schedule_cron, schedule_enabled) "
        "WHERE schedule_enabled = TRUE AND status = 'PUBLISHED';"
    )
