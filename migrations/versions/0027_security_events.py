"""Phase 4.2.6 — Gateway / 보안: audit.security_event 테이블.

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-26 21:00:00+00:00

abuse_detector 가 적재 + frontend SecurityEventsPage 가 조회. NOTIFY outbox 도 동시
발행해 Slack 알람.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit.security_event (
            event_id      BIGSERIAL PRIMARY KEY,
            kind          TEXT NOT NULL,
            severity      TEXT NOT NULL DEFAULT 'WARN',
            api_key_id    BIGINT REFERENCES ctl.api_key(api_key_id),
            ip_addr       INET,
            user_agent    TEXT,
            details_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_security_event_kind CHECK (
                kind IN (
                    'IP_MULTI_KEY',
                    'KEY_HIGH_4XX',
                    'IP_BURST',
                    'TLS_FAIL',
                    'OTHER'
                )
            ),
            CONSTRAINT ck_security_event_severity CHECK (
                severity IN ('INFO','WARN','ERROR','CRITICAL')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_security_event_kind_idx "
        "ON audit.security_event (kind, occurred_at DESC);"
    )
    op.execute(
        "CREATE INDEX audit_security_event_ip_idx "
        "ON audit.security_event (ip_addr, occurred_at DESC);"
    )
    op.execute(
        "GRANT SELECT, INSERT ON audit.security_event TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE audit.security_event_event_id_seq TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.security_event CASCADE;")
