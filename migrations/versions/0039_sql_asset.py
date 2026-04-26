"""Phase 5.2.2 — domain.sql_asset (Q2: SQL_ASSET_TRANSFORM 노드의 backing 테이블).

Revision ID: 0039
Revises: 0038
Create Date: 2026-04-27 02:00:00+00:00

설계:
  * v2 SQL_ASSET_TRANSFORM 노드는 *DB 에 등록·승인된* SQL 만 production 실행.
    INLINE 은 sandbox-only — 비교 표는 PHASE_5_GENERIC_PLATFORM.md § 5.2.2 참고.
  * 상태머신 (DRAFT→REVIEW→APPROVED→PUBLISHED) 은 ctl.approval_request 에 의해
    관리. 본 테이블은 *현재 status* + 본문 (sql_text / output_table / 정책 메타) 만 보관.
  * (asset_code, version) UNIQUE — 같은 asset_code 의 새 version 은 별 row.
  * checksum 으로 동일 SQL 중복 등록 방지.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.sql_asset (
            asset_id          BIGSERIAL PRIMARY KEY,
            asset_code        TEXT NOT NULL,
            domain_code       TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            version           INTEGER NOT NULL DEFAULT 1,
            sql_text          TEXT NOT NULL,
            checksum          TEXT NOT NULL,
            output_table      TEXT,
            description       TEXT,
            status            TEXT NOT NULL DEFAULT 'DRAFT',
            created_by        BIGINT REFERENCES ctl.app_user(user_id),
            approved_by       BIGINT REFERENCES ctl.app_user(user_id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sql_asset_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT ck_sql_asset_code_format CHECK (
                asset_code ~ '^[a-z][a-z0-9_]{1,62}$'
            ),
            CONSTRAINT uq_sql_asset_code_version UNIQUE (asset_code, version)
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_sql_asset_lookup "
        "ON domain.sql_asset (domain_code, asset_code, version DESC);"
    )
    op.execute(
        "CREATE INDEX domain_sql_asset_published "
        "ON domain.sql_asset (asset_code, version DESC) "
        "WHERE status = 'PUBLISHED';"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON domain.sql_asset TO app_rw; "
        "GRANT SELECT ON domain.sql_asset TO app_mart_write; "
        "GRANT USAGE, SELECT ON SEQUENCE domain.sql_asset_asset_id_seq TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.sql_asset CASCADE;")
