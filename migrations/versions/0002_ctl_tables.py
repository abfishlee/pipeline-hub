"""ctl tables — app_user, role, user_role, data_source, connector, api_key

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25 09:30:00+00:00

docs/03_DATA_MODEL.md 3.2 정합.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- ctl.app_user ---
    op.create_table(
        "app_user",
        sa.Column("user_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("login_id", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("login_id", name="uq_app_user_login_id"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
        schema="ctl",
    )

    # --- ctl.role ---
    op.create_table(
        "role",
        sa.Column("role_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("role_code", sa.Text, nullable=False),
        sa.Column("role_name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.UniqueConstraint("role_code", name="uq_role_role_code"),
        schema="ctl",
    )

    # --- ctl.user_role ---
    op.create_table(
        "user_role",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("role_id", sa.BigInteger, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["ctl.app_user.user_id"],
            ondelete="CASCADE",
            name="fk_user_role_user_id_app_user",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["ctl.role.role_id"],
            ondelete="CASCADE",
            name="fk_user_role_role_id_role",
        ),
        schema="ctl",
    )

    # --- ctl.data_source ---
    op.create_table(
        "data_source",
        sa.Column("source_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_code", sa.Text, nullable=False),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("retailer_id", sa.BigInteger),
        sa.Column("owner_team", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "config_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("schedule_cron", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("source_code", name="uq_data_source_source_code"),
        sa.CheckConstraint(
            "source_type IN ('API','OCR','DB','CRAWLER','CROWD','RECEIPT','APP')",
            name="ck_data_source_source_type",
        ),
        schema="ctl",
    )

    # --- ctl.connector ---
    op.create_table(
        "connector",
        sa.Column("connector_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger, nullable=False),
        sa.Column("connector_kind", sa.Text, nullable=False),
        sa.Column("secret_ref", sa.Text, nullable=False),
        sa.Column(
            "config_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["ctl.data_source.source_id"],
            name="fk_connector_source_id_data_source",
        ),
        sa.CheckConstraint(
            "connector_kind IN ('PG','MYSQL','ORACLE','MSSQL','HTTP','S3')",
            name="ck_connector_connector_kind",
        ),
        schema="ctl",
    )

    # --- ctl.api_key ---
    op.create_table(
        "api_key",
        sa.Column("api_key_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("key_prefix", sa.Text, nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("client_name", sa.Text, nullable=False),
        sa.Column(
            "scope",
            ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "rate_limit_per_min", sa.Integer, nullable=False, server_default=sa.text("60")
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("key_prefix", name="uq_api_key_key_prefix"),
        schema="ctl",
    )


def downgrade() -> None:
    op.drop_table("api_key", schema="ctl")
    op.drop_table("connector", schema="ctl")
    op.drop_table("data_source", schema="ctl")
    op.drop_table("user_role", schema="ctl")
    op.drop_table("role", schema="ctl")
    op.drop_table("app_user", schema="ctl")
