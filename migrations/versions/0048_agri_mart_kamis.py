"""Phase 6 Wave 3.5 — agri_mart schema + KAMIS 도매시장 가격 fact + resource seed.

Revision ID: 0048
Revises: 0047
Create Date: 2026-04-26 21:00:00+00:00

Wave 3.5 KAMIS vertical slice (Phase 6 product UX § 13.2):
  Canvas 없이 backend + dry-run 으로 e2e 검증하기 위한 최소 schema.

테이블:
  agri_mart.kamis_price       — KAMIS OpenAPI 도매시장 일별가격 fact

도메인 등록:
  domain.domain_definition    — 'agri' 도메인이 없으면 INSERT
  domain.resource_definition  — KAMIS_WHOLESALE_PRICE resource (PUBLISHED)

운영 절차 (Wave 6 시연 시):
  1. 본 migration 적용 → agri_mart.kamis_price 테이블 + resource 등록
  2. scripts/seed_kamis_vertical_slice.py 실행 → connector/mapping/policy/rule/workflow
  3. /v2/dryrun/workflow/{id} 호출 → 4박스 e2e dry-run 검증
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- schema ----
    op.execute("CREATE SCHEMA IF NOT EXISTS agri_mart;")
    op.execute("CREATE SCHEMA IF NOT EXISTS agri_stg;")
    op.execute(
        "GRANT USAGE ON SCHEMA agri_mart TO app_rw, app_mart_write; "
        "GRANT USAGE ON SCHEMA agri_stg  TO app_rw;"
    )

    # ---- KAMIS 도매시장 가격 fact ----
    # 단순 mart (Phase 7+ 에서 SCD2 / partition / index 추가 가능).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agri_mart.kamis_price (
            ymd            TEXT        NOT NULL,
            item_code      TEXT        NOT NULL,
            item_name      TEXT        NOT NULL,
            market_code    TEXT        NOT NULL,
            market_name    TEXT,
            unit_price     NUMERIC(18,2),
            unit_name      TEXT,
            grade          TEXT,
            observed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_response   JSONB,
            CONSTRAINT pk_kamis_price PRIMARY KEY (ymd, item_code, market_code)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kamis_price_market_ymd "
        "ON agri_mart.kamis_price (market_code, ymd);"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON agri_mart.kamis_price TO app_mart_write; "
        "GRANT SELECT ON agri_mart.kamis_price TO app_rw;"
    )

    # ---- agri 도메인 등록 (없으면) ----
    op.execute(
        """
        INSERT INTO domain.domain_definition
            (domain_code, name, description, schema_yaml, status, version)
        VALUES
            ('agri', '농축산물 가격 데이터',
             '농축산물 가격 수집·표준화 도메인 (KAMIS / 마트 / 로컬푸드 / 영수증 등)',
             '{}'::jsonb, 'PUBLISHED', 1)
        ON CONFLICT DO NOTHING;
        """
    )

    # ---- KAMIS_WHOLESALE_PRICE resource 등록 ----
    op.execute(
        """
        INSERT INTO domain.resource_definition
            (domain_code, resource_code, fact_table, canonical_table,
             standard_code_namespace, status, version)
        VALUES
            ('agri','KAMIS_WHOLESALE_PRICE',
             'agri_mart.kamis_price', NULL,
             NULL, 'PUBLISHED', 1)
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM domain.resource_definition "
        "WHERE domain_code='agri' AND resource_code='KAMIS_WHOLESALE_PRICE';"
    )
    op.execute("DROP TABLE IF EXISTS agri_mart.kamis_price CASCADE;")
    # schema/agri 도메인 자체는 다른 migration 에서 사용될 수 있으므로 유지.
