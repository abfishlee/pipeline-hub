"""SQL Studio asset type and Canvas parameterized SQL.

Revision ID: 0057
Revises: 0056
Create Date: 2026-04-28 00:00:00+09:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ASSET_TYPES = (
    "TRANSFORM_SQL",
    "STANDARDIZATION_SQL",
    "QUALITY_CHECK_SQL",
    "DML_SCRIPT",
    "FUNCTION",
    "PROCEDURE",
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE domain.sql_asset
        ADD COLUMN IF NOT EXISTS asset_type TEXT NOT NULL DEFAULT 'TRANSFORM_SQL';
        """
    )
    op.execute(
        f"""
        ALTER TABLE domain.sql_asset
        DROP CONSTRAINT IF EXISTS ck_sql_asset_type;

        ALTER TABLE domain.sql_asset
        ADD CONSTRAINT ck_sql_asset_type
        CHECK (asset_type IN {ASSET_TYPES!r});
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS domain_sql_asset_type_lookup
        ON domain.sql_asset (domain_code, asset_type, asset_code, version DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS domain.domain_sql_asset_type_lookup;")
    op.execute(
        """
        ALTER TABLE domain.sql_asset
        DROP CONSTRAINT IF EXISTS ck_sql_asset_type;

        ALTER TABLE domain.sql_asset
        DROP COLUMN IF EXISTS asset_type;
        """
    )
