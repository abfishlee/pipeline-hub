"""Phase 5.2.1 — domain.* schema 신설.

Revision ID: 0032
Revises: 0031
Create Date: 2026-04-27 00:00:00+00:00

domain.* 는 *플랫폼 설정/계약/승인* 영역. v2 generic 의 source_contract /
field_mapping / load_policy / dq_rule / provider_registry 가 본 schema 안에 있음.

권한 (Q2 답변):
  - app_rw          : RW
  - app_mart_write  : RO (worker 가 mart 적재 시 load_policy/contract 읽기)
  - app_readonly    : 접근 X
  - app_public      : 접근 X
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS domain;")
    op.execute(
        """
        GRANT USAGE ON SCHEMA domain TO app_rw, app_mart_write;
        ALTER DEFAULT PRIVILEGES IN SCHEMA domain
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
        ALTER DEFAULT PRIVILEGES IN SCHEMA domain
            GRANT SELECT ON TABLES TO app_mart_write;
        ALTER DEFAULT PRIVILEGES IN SCHEMA domain
            GRANT USAGE, SELECT ON SEQUENCES TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS domain CASCADE;")
