"""mart tables — standard_code + retailer/seller/product master + product_mapping
                + price_fact (PARTITIONED) + price_daily_agg + master_entity_history

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-25 11:30:00+00:00

docs/03_DATA_MODEL.md 3.5 정합. 농축산물 가격 서비스의 핵심 마스터/팩트.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- mart.standard_code ---
    op.execute(
        """
        CREATE TABLE mart.standard_code (
            std_code          TEXT PRIMARY KEY,
            category_lv1      TEXT NOT NULL,
            category_lv2      TEXT,
            category_lv3      TEXT,
            item_name_ko      TEXT NOT NULL,
            aliases           TEXT[] NOT NULL DEFAULT '{}',
            default_unit      TEXT,
            source_authority  TEXT,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # 한국어 trigram 유사도 검색 (표준화 매칭 후보 조회)
    op.execute(
        "CREATE INDEX mart_standard_code_item_trgm "
        "ON mart.standard_code USING gin (item_name_ko gin_trgm_ops);"
    )
    # aliases 배열 검색 (alias 매칭)
    op.execute(
        "CREATE INDEX mart_standard_code_aliases_gin "
        "ON mart.standard_code USING gin (aliases);"
    )

    # --- mart.retailer_master ---
    op.execute(
        """
        CREATE TABLE mart.retailer_master (
            retailer_id       BIGSERIAL PRIMARY KEY,
            retailer_code     TEXT NOT NULL UNIQUE,
            retailer_name     TEXT NOT NULL,
            retailer_type     TEXT NOT NULL CHECK (
                retailer_type IN ('MART','SSM','LOCAL','ONLINE','TRAD_MARKET','APP')
            ),
            business_no       TEXT,
            head_office_addr  TEXT,
            meta_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # --- mart.seller_master ---
    op.execute(
        """
        CREATE TABLE mart.seller_master (
            seller_id         BIGSERIAL PRIMARY KEY,
            retailer_id       BIGINT REFERENCES mart.retailer_master(retailer_id),
            seller_code       TEXT NOT NULL,
            seller_name       TEXT NOT NULL,
            channel           TEXT NOT NULL CHECK (channel IN ('OFFLINE','ONLINE')),
            region_sido       TEXT,
            region_sigungu    TEXT,
            address           TEXT,
            geo_point         POINT,
            meta_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (retailer_id, seller_code)
        );
        """
    )

    # --- mart.product_master ---
    op.execute(
        """
        CREATE TABLE mart.product_master (
            product_id        BIGSERIAL PRIMARY KEY,
            std_code          TEXT NOT NULL REFERENCES mart.standard_code(std_code),
            grade             TEXT,
            package_type      TEXT,
            sale_unit_norm    TEXT,
            weight_g          NUMERIC(12,2),
            canonical_name    TEXT NOT NULL,
            first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            confidence_score  NUMERIC(5,2),
            UNIQUE (std_code, grade, package_type, sale_unit_norm, weight_g)
        );
        """
    )

    # --- mart.product_mapping ---
    op.execute(
        """
        CREATE TABLE mart.product_mapping (
            mapping_id        BIGSERIAL PRIMARY KEY,
            retailer_id       BIGINT NOT NULL REFERENCES mart.retailer_master(retailer_id),
            retailer_product_code TEXT,
            raw_product_name  TEXT NOT NULL,
            product_id        BIGINT NOT NULL REFERENCES mart.product_master(product_id),
            match_method      TEXT NOT NULL CHECK (
                match_method IN ('EMBEDDING','RULE','HUMAN','ALIAS')
            ),
            confidence_score  NUMERIC(5,2),
            verified_by       BIGINT REFERENCES ctl.app_user(user_id),
            verified_at       TIMESTAMPTZ,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX mart_product_mapping_lookup "
        "ON mart.product_mapping (retailer_id, retailer_product_code);"
    )
    op.execute(
        "CREATE INDEX mart_product_mapping_name_trgm "
        "ON mart.product_mapping USING gin (raw_product_name gin_trgm_ops);"
    )

    # --- mart.price_fact (PARTITIONED, append-heavy) ---
    op.execute(
        """
        CREATE TABLE mart.price_fact (
            price_id          BIGSERIAL,
            product_id        BIGINT NOT NULL REFERENCES mart.product_master(product_id),
            seller_id         BIGINT NOT NULL REFERENCES mart.seller_master(seller_id),
            observed_at       TIMESTAMPTZ NOT NULL,
            price_krw         NUMERIC(14,2) NOT NULL,
            discount_price_krw NUMERIC(14,2),
            unit_price_per_kg NUMERIC(14,2),
            source_id         BIGINT NOT NULL,
            raw_object_id     BIGINT,
            partition_date    DATE NOT NULL DEFAULT CURRENT_DATE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_price_fact PRIMARY KEY (price_id, partition_date)
        ) PARTITION BY RANGE (partition_date);
        """
    )
    op.execute(
        """
        CREATE TABLE mart.price_fact_2026_04 PARTITION OF mart.price_fact
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
        """
    )
    op.execute(
        "CREATE INDEX mart_price_fact_product_time "
        "ON mart.price_fact (product_id, observed_at DESC);"
    )
    op.execute(
        "CREATE INDEX mart_price_fact_seller_time "
        "ON mart.price_fact (seller_id, observed_at DESC);"
    )
    # BRIN — 시계열 append-heavy 에 효율적 (인덱스 크기 1/100)
    op.execute(
        "CREATE INDEX mart_price_fact_observed_brin "
        "ON mart.price_fact USING BRIN (observed_at);"
    )

    # --- mart.price_daily_agg ---
    op.execute(
        """
        CREATE TABLE mart.price_daily_agg (
            agg_date          DATE NOT NULL,
            std_code          TEXT NOT NULL REFERENCES mart.standard_code(std_code),
            retailer_id       BIGINT,
            region_sido       TEXT,
            min_price_krw     NUMERIC(14,2),
            avg_price_krw     NUMERIC(14,2),
            max_price_krw     NUMERIC(14,2),
            median_price_krw  NUMERIC(14,2),
            obs_count         INTEGER NOT NULL,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_price_daily_agg PRIMARY KEY
                (agg_date, std_code, retailer_id, region_sido)
        );
        """
    )

    # --- mart.master_entity_history ---
    op.execute(
        """
        CREATE TABLE mart.master_entity_history (
            history_id        BIGSERIAL PRIMARY KEY,
            entity_type       TEXT NOT NULL,
            entity_id         BIGINT NOT NULL,
            canonical_json    JSONB NOT NULL,
            valid_from        TIMESTAMPTZ NOT NULL,
            valid_to          TIMESTAMPTZ,
            is_current        BOOLEAN NOT NULL DEFAULT TRUE,
            changed_reason    TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX mart_master_history_current "
        "ON mart.master_entity_history (entity_type, entity_id) "
        "WHERE is_current = TRUE;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mart.master_entity_history CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.price_daily_agg CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.price_fact_2026_04 CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.price_fact CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.product_mapping CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.product_master CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.seller_master CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.retailer_master CASCADE;")
    op.execute("DROP TABLE IF EXISTS mart.standard_code CASCADE;")
