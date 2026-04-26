"""Phase 5.2.1 — domain.dq_rule registry.

Revision ID: 0036
Revises: 0035
Create Date: 2026-04-27 00:20:00+00:00

DQ rule registry — Phase 4.2.2 의 DQ 게이트가 *runtime 평가* 만 담당했다면, 본 테이블은
*도메인 별 DQ rule 카탈로그*. v2 의 Mart Designer / DQ Rule Builder UI 가 본 테이블을
조회/편집.

rule_kind:
  - row_count_min  : { "min": 100 }
  - null_pct_max   : { "column": "name", "max_pct": 5.0 }
  - unique_columns : { "columns": ["sku"] }
  - reference      : { "ref_table": "mart.product_master", "ref_column": "product_id" }
  - custom_sql     : { "sql": "...", "expect": 0 }
  - range          : { "column": "price_krw", "min": 0, "max": 1e9 }
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.dq_rule (
            rule_id          BIGSERIAL PRIMARY KEY,
            domain_code      TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            target_table     TEXT NOT NULL,
            rule_kind        TEXT NOT NULL,
            rule_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
            severity         TEXT NOT NULL DEFAULT 'ERROR',
            timeout_ms       INTEGER NOT NULL DEFAULT 30000,
            sample_limit     INTEGER NOT NULL DEFAULT 10,
            max_scan_rows    BIGINT,
            incremental_only BOOLEAN NOT NULL DEFAULT FALSE,
            status           TEXT NOT NULL DEFAULT 'DRAFT',
            version          INTEGER NOT NULL DEFAULT 1,
            description      TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_dq_rule_kind CHECK (
                rule_kind IN (
                    'row_count_min','null_pct_max','unique_columns',
                    'reference','range','custom_sql'
                )
            ),
            CONSTRAINT ck_dq_rule_severity CHECK (
                severity IN ('INFO','WARN','ERROR','BLOCK')
            ),
            CONSTRAINT ck_dq_rule_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_dq_rule_target_idx "
        "ON domain.dq_rule (domain_code, target_table, status);"
    )

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
              ON domain.dq_rule TO app_rw;
        GRANT SELECT ON domain.dq_rule TO app_mart_write;
        GRANT USAGE, SELECT
              ON SEQUENCE domain.dq_rule_rule_id_seq TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.dq_rule CASCADE;")
