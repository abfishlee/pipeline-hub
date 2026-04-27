"""Phase 8.5 — audit.alert_log (System Alert 발사 이력).

Revision ID: 0053
Revises: 0052
Create Date: 2026-04-27 12:00:00+00:00

System Alert 채널 (Slack webhook + log fallback) 의 발사 기록.
중복 발사 억제 (rate limit) 를 위해 (rule_code, target_key) 별 last_fired_at
조회에도 사용.

provider_usage 의 cost_estimate 는 이미 존재 (migration 0040 이전).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit.alert_log (
            alert_id      BIGSERIAL PRIMARY KEY,
            rule_code     TEXT NOT NULL,
            severity      TEXT NOT NULL DEFAULT 'WARN',
            target_key    TEXT,
            title         TEXT NOT NULL,
            message       TEXT,
            metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
            channel       TEXT NOT NULL DEFAULT 'log',
            delivered     BOOLEAN NOT NULL DEFAULT FALSE,
            delivery_error TEXT,
            fired_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_alert_severity
                CHECK (severity IN ('INFO','WARN','ERROR','CRITICAL')),
            CONSTRAINT ck_alert_channel
                CHECK (channel IN ('log','slack','email'))
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_log_rule_target_time "
        "ON audit.alert_log (rule_code, target_key, fired_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_log_severity_time "
        "ON audit.alert_log (severity, fired_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.alert_log CASCADE;")
