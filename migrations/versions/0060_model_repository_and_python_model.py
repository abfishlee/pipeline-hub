"""Model repository metadata and Python model support.

Revision ID: 0060
Revises: 0059
Create Date: 2026-04-29 15:30:00+09:00
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ASSET_TYPES = (
    "TRANSFORM_SQL",
    "STANDARDIZATION_SQL",
    "QUALITY_CHECK_SQL",
    "DML_SCRIPT",
    "FUNCTION",
    "PROCEDURE",
    "PYTHON_SCRIPT",
)

MODEL_CATEGORIES = ("TRANSFORM", "DQ", "STANDARDIZATION", "ENRICHMENT", "LOAD", "OTHER")


PYTHON_EXAMPLE = r'''
rows = read_rows(limit=200)
result_rows = []

for row in rows:
    payload = row.get("payload") or {}
    # API Pull rows carry the original source row as JSONB payload. If the input
    # is already flat, payload may be empty and the row itself is used.
    if isinstance(payload, str):
        payload = {}
    src = payload or row

    price_text = str(src.get("regular_price") or src.get("regularPrice") or src.get("정상가") or "")
    digits = re.sub(r"[^0-9.]", "", price_text)
    regular_price = digits if digits else None

    result_rows.append({
        "store_name": src.get("store_name") or src.get("storeName") or src.get("점포명"),
        "item_name": src.get("item") or src.get("itemName") or src.get("품목"),
        "product_name": src.get("product_name") or src.get("productName") or src.get("상품명"),
        "regular_price": regular_price,
        "source_node": node_key,
    })
'''


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE domain.sql_asset
        ADD COLUMN IF NOT EXISTS model_category TEXT NOT NULL DEFAULT 'TRANSFORM';

        ALTER TABLE domain.sql_asset
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
        """
    )
    op.execute(
        f"""
        ALTER TABLE domain.sql_asset
        DROP CONSTRAINT IF EXISTS ck_sql_asset_type;

        ALTER TABLE domain.sql_asset
        ADD CONSTRAINT ck_sql_asset_type
        CHECK (asset_type IN {ASSET_TYPES!r});

        ALTER TABLE domain.sql_asset
        DROP CONSTRAINT IF EXISTS ck_sql_asset_model_category;

        ALTER TABLE domain.sql_asset
        ADD CONSTRAINT ck_sql_asset_model_category
        CHECK (model_category IN {MODEL_CATEGORIES!r});
        """
    )
    op.execute(
        """
        UPDATE domain.sql_asset
           SET model_category = CASE
             WHEN asset_type = 'STANDARDIZATION_SQL' THEN 'STANDARDIZATION'
             WHEN asset_type = 'QUALITY_CHECK_SQL' THEN 'DQ'
             WHEN asset_type = 'DML_SCRIPT' THEN 'LOAD'
             WHEN asset_type IN ('FUNCTION','PROCEDURE') THEN 'OTHER'
             ELSE 'TRANSFORM'
           END
         WHERE model_category IS NULL OR model_category = 'TRANSFORM';
        """
    )
    bind = op.get_bind()
    exists = bind.execute(
        text(
            "SELECT 1 FROM domain.sql_asset "
            "WHERE asset_code = 'python_price_cleanup_example' AND version = 1"
        )
    ).first()
    if exists is None:
        bind.execute(
            text(
                """
                INSERT INTO domain.sql_asset
                  (asset_code, domain_code, version, asset_type, model_category,
                   sql_text, checksum, output_table, description, status, is_active)
                VALUES
                  (:code, 'agri_price', 1, 'PYTHON_SCRIPT', 'TRANSFORM',
                   :body, :checksum, 'agri_price_stg.python_price_cleanup_example',
                   :description, 'PUBLISHED', true)
                """
            ),
            {
                "code": "python_price_cleanup_example",
                "body": PYTHON_EXAMPLE.strip(),
                "checksum": _checksum(PYTHON_EXAMPLE.strip()),
                "description": (
                    "Canvas Python Model example: read upstream rows, normalize "
                    "price text, and write a flat staging table."
                ),
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM domain.sql_asset "
        "WHERE asset_code = 'python_price_cleanup_example' AND version = 1"
    )
    op.execute(
        """
        ALTER TABLE domain.sql_asset
        DROP CONSTRAINT IF EXISTS ck_sql_asset_model_category;

        ALTER TABLE domain.sql_asset
        DROP CONSTRAINT IF EXISTS ck_sql_asset_type;

        ALTER TABLE domain.sql_asset
        ADD CONSTRAINT ck_sql_asset_type
        CHECK (asset_type IN (
          'TRANSFORM_SQL','STANDARDIZATION_SQL','QUALITY_CHECK_SQL',
          'DML_SCRIPT','FUNCTION','PROCEDURE'
        ));

        ALTER TABLE domain.sql_asset
        DROP COLUMN IF EXISTS is_active;

        ALTER TABLE domain.sql_asset
        DROP COLUMN IF EXISTS model_category;
        """
    )
