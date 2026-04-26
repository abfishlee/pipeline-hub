"""Phase 8 — Synthetic 4 retailer domains + mart schema + service_mart.

Revision ID: 0051
Revises: 0050
Create Date: 2026-04-26 23:30:00+00:00

4 가상 유통사 (이마트/홈플러스/롯데마트/하나로마트) 의 도메인 + 각 mart schema +
서비스 통합 마트 (`service_mart.product_price`).

테이블:
  domain.domain_definition       — 4개 도메인 INSERT
  domain.resource_definition     — 각 유통사의 PRICE / PROMO / STOCK resource
  emart_mart.product_price       — 이마트 가격
  homeplus_mart.product_promo    — 홈플러스 행사
  lottemart_mart.product_canon   — 롯데마트 정규화 결과
  hanaro_mart.agri_product       — 하나로마트 농축수산물
  service_mart.product_price     — 4 유통사 통합 (배달 서비스용)
  service_mart.std_product       — 표준 품목 마스터 (사과 / 양파 등)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. schemas ─────────────────────────────────────────────────────
    for schema in (
        "emart_mart",
        "homeplus_mart",
        "lottemart_mart",
        "hanaro_mart",
        "service_mart",
    ):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
        op.execute(
            f"GRANT USAGE ON SCHEMA {schema} TO app_rw, app_mart_write;"
        )
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {schema} "
            f"TO app_mart_write;"
        )

    # ── 2. service_mart 표준 품목 마스터 ────────────────────────────────
    op.execute(
        """
        CREATE TABLE service_mart.std_product (
            std_product_code  TEXT PRIMARY KEY,
            std_product_name  TEXT NOT NULL,
            category          TEXT,
            unit_kind         TEXT,
            description       TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # ── 3. service_mart 통합 가격 마트 ───────────────────────────────────
    # 4 유통사 데이터를 동일 구조로 적재 (배달 서비스용).
    op.execute(
        """
        CREATE TABLE service_mart.product_price (
            price_id          BIGSERIAL PRIMARY KEY,
            std_product_code  TEXT
                                REFERENCES service_mart.std_product(std_product_code),
            retailer_code     TEXT NOT NULL,
            retailer_product_code TEXT NOT NULL,
            product_name      TEXT NOT NULL,
            display_name      TEXT,
            price_normal      NUMERIC(12, 2),
            price_promo       NUMERIC(12, 2),
            promo_type        TEXT,
            promo_start       TIMESTAMPTZ,
            promo_end         TIMESTAMPTZ,
            stock_qty         INTEGER,
            stock_status      TEXT,
            unit              TEXT,
            origin            TEXT,
            grade             TEXT,
            standardize_confidence NUMERIC(4, 3),
            needs_review      BOOLEAN NOT NULL DEFAULT false,
            collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_envelope_id   BIGINT,
            CONSTRAINT uq_service_price UNIQUE
                (retailer_code, retailer_product_code, collected_at)
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_service_price_std ON service_mart.product_price "
        "(std_product_code, collected_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_service_price_retailer ON service_mart.product_price "
        "(retailer_code, collected_at DESC);"
    )

    # ── 4. retailer-specific marts ──────────────────────────────────────
    op.execute(
        """
        CREATE TABLE emart_mart.product_price (
            id                BIGSERIAL PRIMARY KEY,
            retailer_product_code TEXT NOT NULL,
            product_name      TEXT NOT NULL,
            price             NUMERIC(12, 2),
            discount_price    NUMERIC(12, 2),
            stock_qty         INTEGER,
            collected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_emart_price_collected ON emart_mart.product_price (collected_at DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE homeplus_mart.product_promo (
            id                BIGSERIAL PRIMARY KEY,
            item_id           TEXT NOT NULL,
            item_title        TEXT NOT NULL,
            sale_price        NUMERIC(12, 2),
            promo_type        TEXT,
            promo_start       DATE,
            promo_end         DATE,
            collected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_hp_promo_collected ON homeplus_mart.product_promo (collected_at DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE lottemart_mart.product_canon (
            id                BIGSERIAL PRIMARY KEY,
            goods_no          TEXT NOT NULL,
            display_name      TEXT NOT NULL,
            cleaned_name      TEXT,
            extracted_size    TEXT,
            current_amt       NUMERIC(12, 2),
            unit_text         TEXT,
            standardize_confidence NUMERIC(4, 3),
            collected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_lm_canon_collected ON lottemart_mart.product_canon (collected_at DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE hanaro_mart.agri_product (
            id                BIGSERIAL PRIMARY KEY,
            product_cd        TEXT NOT NULL,
            name              TEXT NOT NULL,
            origin            TEXT,
            grade             TEXT,
            unit              TEXT,
            price             NUMERIC(12, 2),
            price_per_kg      NUMERIC(12, 2),
            collected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_nh_agri_collected ON hanaro_mart.agri_product (collected_at DESC);
        """
    )

    # ── 5. 4 도메인 + resource 등록 ────────────────────────────────────
    op.execute(
        """
        INSERT INTO domain.domain_definition
            (domain_code, name, description, schema_yaml, status, version)
        VALUES
          ('emart',    '이마트',        'Phase 8 가상 채널 — 표준 API형',
           '{}'::jsonb, 'PUBLISHED', 1),
          ('homeplus', '홈플러스',      'Phase 8 가상 채널 — 행사/할인 풍부',
           '{}'::jsonb, 'PUBLISHED', 1),
          ('lottemart','롯데마트',      'Phase 8 가상 채널 — 상품명 정규화 난이도',
           '{}'::jsonb, 'PUBLISHED', 1),
          ('hanaro',   '하나로마트',    'Phase 8 가상 채널 — 농축수산물 산지/등급',
           '{}'::jsonb, 'PUBLISHED', 1)
        ON CONFLICT DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO domain.resource_definition
            (domain_code, resource_code, fact_table, status, version)
        VALUES
          ('emart',    'PRICE',     'emart_mart.product_price',     'PUBLISHED', 1),
          ('homeplus', 'PROMO',     'homeplus_mart.product_promo',  'PUBLISHED', 1),
          ('lottemart','CANON',     'lottemart_mart.product_canon', 'PUBLISHED', 1),
          ('hanaro',   'AGRI',      'hanaro_mart.agri_product',     'PUBLISHED', 1)
        ON CONFLICT DO NOTHING;
        """
    )

    # ── 6. agri_stg / emart_stg / 등 staging schema (sandbox 위치) ───
    for schema in (
        "emart_stg",
        "homeplus_stg",
        "lottemart_stg",
        "hanaro_stg",
    ):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO app_rw;")


def downgrade() -> None:
    op.execute(
        "DELETE FROM domain.resource_definition WHERE domain_code IN "
        "('emart','homeplus','lottemart','hanaro');"
    )
    op.execute(
        "DELETE FROM domain.domain_definition WHERE domain_code IN "
        "('emart','homeplus','lottemart','hanaro');"
    )
    for schema in (
        "emart_stg", "homeplus_stg", "lottemart_stg", "hanaro_stg",
        "emart_mart", "homeplus_mart", "lottemart_mart", "hanaro_mart",
        "service_mart",
    ):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")
