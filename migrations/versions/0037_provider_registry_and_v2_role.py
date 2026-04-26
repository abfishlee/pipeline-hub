"""Phase 5.2.1 — provider_registry + DOMAIN_ADMIN role.

Revision ID: 0037
Revises: 0036
Create Date: 2026-04-27 00:25:00+00:00

본 migration 은 두 영역을 합침 (5.2.1 마지막 조각):
  1. provider_definition + source_provider_binding — Phase 5.2.1.1 OCR/Crawler
     Provider Registry 의 *DB 기반*. 5.2.1.1 에서 worker 가 본 테이블을 lookup.
  2. ctl.role 에 DOMAIN_ADMIN 추가 — v2 generic registry 관리자 (Q4 답변).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) provider_definition.
    op.execute(
        """
        CREATE TABLE domain.provider_definition (
            provider_code         TEXT PRIMARY KEY,
            provider_kind         TEXT NOT NULL,
            implementation_type   TEXT NOT NULL,
            config_schema         JSONB NOT NULL DEFAULT '{}'::jsonb,
            description           TEXT,
            is_active             BOOLEAN NOT NULL DEFAULT TRUE,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_provider_kind CHECK (
                provider_kind IN (
                    'OCR','CRAWLER','AI_TRANSFORM','HTTP_TRANSFORM'
                )
            ),
            CONSTRAINT ck_provider_impl CHECK (
                implementation_type IN ('internal_class','external_api')
            ),
            CONSTRAINT ck_provider_code_format CHECK (
                provider_code ~ '^[a-z][a-z0-9_]{1,30}$'
            )
        );
        """
    )

    # 2) source_provider_binding.
    op.execute(
        """
        CREATE TABLE domain.source_provider_binding (
            binding_id        BIGSERIAL PRIMARY KEY,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            provider_code     TEXT NOT NULL REFERENCES domain.provider_definition(provider_code),
            priority          INTEGER NOT NULL DEFAULT 1,
            fallback_order    INTEGER NOT NULL DEFAULT 1,
            config_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_source_provider_priority UNIQUE
                (source_id, provider_code, priority)
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_source_provider_lookup "
        "ON domain.source_provider_binding (source_id, is_active, priority);"
    )

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
              ON domain.provider_definition, domain.source_provider_binding
              TO app_rw;
        GRANT SELECT
              ON domain.provider_definition, domain.source_provider_binding
              TO app_mart_write;
        GRANT USAGE, SELECT
              ON SEQUENCE domain.source_provider_binding_binding_id_seq TO app_rw;
        """
    )

    # 3) DOMAIN_ADMIN role (Q4 답변 — v2 전용 role).
    op.execute(
        """
        INSERT INTO ctl.role (role_code, role_name, description) VALUES
            ('DOMAIN_ADMIN',
             'v2 Domain Admin',
             'Phase 5 v2 generic registry — domain/contract/mapping/load_policy/dq_rule 관리')
        ON CONFLICT (role_code) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ctl.user_role WHERE role_id IN ("
        "  SELECT role_id FROM ctl.role WHERE role_code = 'DOMAIN_ADMIN'"
        ");"
    )
    op.execute("DELETE FROM ctl.role WHERE role_code = 'DOMAIN_ADMIN';")
    op.execute("DROP TABLE IF EXISTS domain.source_provider_binding CASCADE;")
    op.execute("DROP TABLE IF EXISTS domain.provider_definition CASCADE;")
