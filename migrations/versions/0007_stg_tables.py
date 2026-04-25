"""stg tables — standard_record + price_observation

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-25 12:00:00+00:00

docs/03_DATA_MODEL.md 3.4 정합. 모든 채널이 공통 스키마로 평탄화되는 단계.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- stg.standard_record (채널 무관 공통) ---
    op.execute(
        """
        CREATE TABLE stg.standard_record (
            record_id         BIGSERIAL PRIMARY KEY,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            raw_object_id     BIGINT,
            raw_partition     DATE,
            entity_type       TEXT NOT NULL,
            business_key      TEXT,
            record_json       JSONB NOT NULL,
            observed_at       TIMESTAMPTZ,
            valid_from        TIMESTAMPTZ,
            valid_to          TIMESTAMPTZ,
            quality_score     NUMERIC(5,2),
            load_batch_id     BIGINT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX stg_standard_record_entity_bk "
        "ON stg.standard_record (entity_type, business_key);"
    )
    op.execute(
        "CREATE INDEX stg_standard_record_source "
        "ON stg.standard_record (source_id, created_at DESC);"
    )

    # --- stg.price_observation (가격 전용 컬럼화) ---
    op.execute(
        """
        CREATE TABLE stg.price_observation (
            obs_id            BIGSERIAL PRIMARY KEY,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            raw_object_id     BIGINT,
            raw_partition     DATE,
            retailer_code     TEXT,
            seller_name       TEXT,
            store_name        TEXT,
            product_name_raw  TEXT NOT NULL,
            std_code          TEXT REFERENCES mart.standard_code(std_code),
            std_confidence    NUMERIC(5,2),
            grade             TEXT,
            package_type      TEXT,
            sale_unit         TEXT,
            weight_g          NUMERIC(12,2),
            brix              NUMERIC(5,2),
            price_krw         NUMERIC(14,2) NOT NULL,
            discount_price_krw NUMERIC(14,2),
            currency          TEXT NOT NULL DEFAULT 'KRW',
            observed_at       TIMESTAMPTZ NOT NULL,
            standardized_at   TIMESTAMPTZ,
            load_batch_id     BIGINT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX stg_price_obs_std_observed "
        "ON stg.price_observation (std_code, observed_at DESC);"
    )
    op.execute(
        "CREATE INDEX stg_price_obs_retailer_observed "
        "ON stg.price_observation (retailer_code, observed_at DESC);"
    )
    # 미표준화 row 만 인덱싱 (표준화 worker 가 폴링)
    op.execute(
        "CREATE INDEX stg_price_obs_unstandardized "
        "ON stg.price_observation (source_id, created_at) "
        "WHERE std_code IS NULL;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stg.price_observation CASCADE;")
    op.execute("DROP TABLE IF EXISTS stg.standard_record CASCADE;")
