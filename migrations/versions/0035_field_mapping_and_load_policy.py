"""Phase 5.2.1 — field_mapping + load_policy.

Revision ID: 0035
Revises: 0034
Create Date: 2026-04-27 00:15:00+00:00

field_mapping: source path (JSONPath) → target table.column 매핑 + transform_expr.
load_policy: append-only / upsert / scd2 / current_snapshot 4종 정책.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.field_mapping (
            mapping_id        BIGSERIAL PRIMARY KEY,
            contract_id       BIGINT NOT NULL REFERENCES domain.source_contract(contract_id)
                                ON DELETE CASCADE,
            source_path       TEXT NOT NULL,
            target_table      TEXT NOT NULL,
            target_column     TEXT NOT NULL,
            transform_expr    TEXT,
            data_type         TEXT,
            is_required       BOOLEAN NOT NULL DEFAULT FALSE,
            order_no          INTEGER NOT NULL DEFAULT 0,
            status            TEXT NOT NULL DEFAULT 'DRAFT',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_field_mapping_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT uq_field_mapping_target UNIQUE
                (contract_id, target_table, target_column)
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_field_mapping_contract_idx "
        "ON domain.field_mapping (contract_id, status);"
    )

    op.execute(
        """
        CREATE TABLE domain.load_policy (
            policy_id         BIGSERIAL PRIMARY KEY,
            resource_id       BIGINT NOT NULL REFERENCES domain.resource_definition(resource_id),
            mode              TEXT NOT NULL,
            key_columns       TEXT[] NOT NULL DEFAULT '{}'::text[],
            partition_expr    TEXT,
            scd_options_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
            chunk_size        INTEGER NOT NULL DEFAULT 1000,
            statement_timeout_ms INTEGER NOT NULL DEFAULT 60000,
            status            TEXT NOT NULL DEFAULT 'DRAFT',
            version           INTEGER NOT NULL DEFAULT 1,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_load_policy_mode CHECK (
                mode IN ('append_only','upsert','scd_type_2','current_snapshot')
            ),
            CONSTRAINT ck_load_policy_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT uq_load_policy_resource_version UNIQUE (resource_id, version)
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_load_policy_resource_idx "
        "ON domain.load_policy (resource_id, status);"
    )

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
              ON domain.field_mapping, domain.load_policy
              TO app_rw;
        GRANT SELECT ON domain.field_mapping, domain.load_policy TO app_mart_write;
        GRANT USAGE, SELECT
              ON SEQUENCE domain.field_mapping_mapping_id_seq,
                          domain.load_policy_policy_id_seq
              TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.load_policy CASCADE;")
    op.execute("DROP TABLE IF EXISTS domain.field_mapping CASCADE;")
