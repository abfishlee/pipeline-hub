"""Phase 5.2.1 — domain_definition / resource_definition / standard_code_namespace.

Revision ID: 0033
Revises: 0032
Create Date: 2026-04-27 00:05:00+00:00

3 테이블:
  - domain.domain_definition: 도메인 1개의 메타 (yaml 사본 + status)
  - domain.resource_definition: 도메인 N개의 resource (master/fact 테이블 매핑)
  - domain.standard_code_namespace: 도메인별 std_code 체계
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.domain_definition (
            domain_code     TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT,
            schema_yaml     JSONB NOT NULL DEFAULT '{}'::jsonb,
            status          TEXT NOT NULL DEFAULT 'DRAFT',
            version         INTEGER NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_domain_definition_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT ck_domain_code_format CHECK (
                domain_code ~ '^[a-z][a-z0-9_]{1,30}$'
            )
        );
        """
    )

    op.execute(
        """
        CREATE TABLE domain.resource_definition (
            resource_id              BIGSERIAL PRIMARY KEY,
            domain_code              TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            resource_code            TEXT NOT NULL,
            canonical_table          TEXT,
            fact_table               TEXT,
            standard_code_namespace  TEXT,
            embedding_model          TEXT,
            embedding_table          TEXT,
            embedding_dim            INTEGER,
            status                   TEXT NOT NULL DEFAULT 'DRAFT',
            version                  INTEGER NOT NULL DEFAULT 1,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_resource_definition_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT uq_resource_definition_code UNIQUE (domain_code, resource_code, version)
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_resource_definition_domain_idx "
        "ON domain.resource_definition (domain_code, status);"
    )

    op.execute(
        """
        CREATE TABLE domain.standard_code_namespace (
            namespace_id      BIGSERIAL PRIMARY KEY,
            domain_code       TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            name              TEXT NOT NULL,
            description       TEXT,
            std_code_table    TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_standard_code_namespace UNIQUE (domain_code, name)
        );
        """
    )

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
              ON domain.domain_definition,
                 domain.resource_definition,
                 domain.standard_code_namespace
              TO app_rw;
        GRANT SELECT
              ON domain.domain_definition,
                 domain.resource_definition,
                 domain.standard_code_namespace
              TO app_mart_write;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA domain TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.standard_code_namespace CASCADE;")
    op.execute("DROP TABLE IF EXISTS domain.resource_definition CASCADE;")
    op.execute("DROP TABLE IF EXISTS domain.domain_definition CASCADE;")
