"""Phase 4.2.5 — Public API 정식: api_key 메타 확장 + audit.public_api_usage.

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-26 19:30:00+00:00

변경:
  1. ctl.api_key 에 last_used_at, revoked_at, expires_at (기존 expired_at 와 별개) 추가.
     - 기존 `expired_at` 은 유지 (호환), 신규 코드는 `expires_at` 사용.
  2. audit.public_api_usage — Public API 호출 1건 단위 적재.
  3. audit.public_api_usage_daily — 일별 집계 view.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) ctl.api_key 메타 확장.
    op.execute(
        """
        ALTER TABLE ctl.api_key
            ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS revoked_at   TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS expires_at   TIMESTAMPTZ;
        """
    )
    # 기존 expired_at 와 expires_at 정합 — 기존 값 마이그.
    op.execute(
        "UPDATE ctl.api_key SET expires_at = expired_at "
        "WHERE expires_at IS NULL AND expired_at IS NOT NULL;"
    )

    # 2) audit.public_api_usage.
    op.execute(
        """
        CREATE TABLE audit.public_api_usage (
            usage_id       BIGSERIAL PRIMARY KEY,
            api_key_id     BIGINT NOT NULL REFERENCES ctl.api_key(api_key_id),
            endpoint       TEXT NOT NULL,
            scope          TEXT,
            status_code    INTEGER NOT NULL,
            duration_ms    INTEGER NOT NULL DEFAULT 0,
            ip_addr        INET,
            occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_public_api_usage_key_idx "
        "ON audit.public_api_usage (api_key_id, occurred_at DESC);"
    )
    op.execute(
        "CREATE INDEX audit_public_api_usage_endpoint_idx "
        "ON audit.public_api_usage (endpoint, occurred_at DESC);"
    )

    # 3) 일별 집계 view (운영자가 대시보드/알람에 사용).
    op.execute(
        """
        CREATE OR REPLACE VIEW audit.public_api_usage_daily AS
        SELECT
            api_key_id,
            endpoint,
            date_trunc('day', occurred_at) AS day,
            COUNT(*)::BIGINT AS count,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p50_ms,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p99_ms,
            SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END)::BIGINT AS error_count
          FROM audit.public_api_usage
         GROUP BY api_key_id, endpoint, date_trunc('day', occurred_at);
        """
    )

    # 4) Phase 4.2.4 의 GRANT 매트릭스에 새 테이블 합류.
    op.execute(
        """
        GRANT SELECT, INSERT ON audit.public_api_usage TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE audit.public_api_usage_usage_id_seq TO app_rw;
        GRANT SELECT ON audit.public_api_usage_daily TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS audit.public_api_usage_daily;")
    op.execute("DROP TABLE IF EXISTS audit.public_api_usage CASCADE;")
    op.execute(
        """
        ALTER TABLE ctl.api_key
            DROP COLUMN IF EXISTS expires_at,
            DROP COLUMN IF EXISTS revoked_at,
            DROP COLUMN IF EXISTS last_used_at;
        """
    )
