"""Phase 5.2.4 STEP 7 — user × domain 권한 매트릭스 + Mini Publish Checklist.

Revision ID: 0041
Revises: 0040
Create Date: 2026-04-27 03:00:00+00:00

배경 (STEP 7 Q1, Q5 답변):

  Q1. domain switcher 권한 모델 = user × domain 권한 매트릭스.
       → ctl.user_domain_role 테이블 (user_id, domain_code, role)
       → role: VIEWER / EDITOR / APPROVER / ADMIN
  Q5. Mini Publish Checklist (MVP 안전장치).
       → ctl.publish_checklist_run 테이블 — *publish 시점* 의 7항목 체크 결과 보관.

ADMIN(전역) 은 모든 도메인 ADMIN 권한 자동 보유 — domain 미지정 row 가 wildcard.

역할 위계:
  VIEWER < EDITOR < APPROVER < ADMIN
  (상위 역할은 하위 역할 권한 포함)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- user × domain 권한 매트릭스 ----
    op.execute(
        """
        CREATE TABLE ctl.user_domain_role (
            user_id      BIGINT NOT NULL REFERENCES ctl.app_user(user_id) ON DELETE CASCADE,
            domain_code  TEXT NOT NULL REFERENCES domain.domain_definition(domain_code)
                         ON DELETE CASCADE,
            role         TEXT NOT NULL,
            granted_by   BIGINT REFERENCES ctl.app_user(user_id),
            granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_user_domain_role PRIMARY KEY (user_id, domain_code),
            CONSTRAINT ck_user_domain_role_role CHECK (
                role IN ('VIEWER','EDITOR','APPROVER','ADMIN')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_user_domain_role_domain_idx "
        "ON ctl.user_domain_role (domain_code, role);"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ctl.user_domain_role TO app_rw; "
        "GRANT SELECT ON ctl.user_domain_role TO app_mart_write;"
    )

    # ---- Mini Publish Checklist 결과 ----
    op.execute(
        """
        CREATE TABLE ctl.publish_checklist_run (
            checklist_id      BIGSERIAL PRIMARY KEY,
            entity_type       TEXT NOT NULL,
            entity_id         BIGINT NOT NULL,
            entity_version    INTEGER NOT NULL DEFAULT 1,
            domain_code       TEXT REFERENCES domain.domain_definition(domain_code),
            requested_by      BIGINT REFERENCES ctl.app_user(user_id),
            checks_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
            all_passed        BOOLEAN NOT NULL DEFAULT FALSE,
            failed_check_codes TEXT[] NOT NULL DEFAULT '{}',
            requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_pcr_entity_type CHECK (
                entity_type IN ('source_contract','field_mapping','dq_rule',
                                'mart_load_policy','sql_asset','load_policy')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_publish_checklist_entity_idx "
        "ON ctl.publish_checklist_run (entity_type, entity_id, requested_at DESC);"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON ctl.publish_checklist_run TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE "
        "  ctl.publish_checklist_run_checklist_id_seq TO app_rw;"
    )

    # ---- Dry-run 결과 캐시 (선택적; 큰 결과는 즉시 보여주고 보존만) ----
    op.execute(
        """
        CREATE TABLE ctl.dry_run_record (
            dry_run_id        BIGSERIAL PRIMARY KEY,
            requested_by      BIGINT REFERENCES ctl.app_user(user_id),
            kind              TEXT NOT NULL,
            domain_code       TEXT,
            target_summary    JSONB NOT NULL DEFAULT '{}'::jsonb,
            row_counts        JSONB NOT NULL DEFAULT '{}'::jsonb,
            errors            TEXT[] NOT NULL DEFAULT '{}',
            duration_ms       INTEGER NOT NULL DEFAULT 0,
            requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_dry_run_kind CHECK (
                kind IN ('field_mapping','load_target','dq_rule','sql_asset',
                         'mart_designer','custom')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_dry_run_recent_idx "
        "ON ctl.dry_run_record (requested_at DESC);"
    )
    op.execute(
        "GRANT SELECT, INSERT ON ctl.dry_run_record TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE "
        "  ctl.dry_run_record_dry_run_id_seq TO app_rw;"
    )

    # ---- Mart Designer 의 migration 초안 ----
    op.execute(
        """
        CREATE TABLE domain.mart_design_draft (
            draft_id          BIGSERIAL PRIMARY KEY,
            domain_code       TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            target_table      TEXT NOT NULL,
            ddl_text          TEXT NOT NULL,
            diff_summary      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by        BIGINT REFERENCES ctl.app_user(user_id),
            approved_by       BIGINT REFERENCES ctl.app_user(user_id),
            status            TEXT NOT NULL DEFAULT 'DRAFT',
            applied_at        TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_mart_design_draft_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED','ROLLED_BACK')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_mart_design_draft_lookup "
        "ON domain.mart_design_draft (domain_code, target_table, created_at DESC);"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON domain.mart_design_draft TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE "
        "  domain.mart_design_draft_draft_id_seq TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.mart_design_draft CASCADE;")
    op.execute("DROP TABLE IF EXISTS ctl.dry_run_record CASCADE;")
    op.execute("DROP TABLE IF EXISTS ctl.publish_checklist_run CASCADE;")
    op.execute("DROP TABLE IF EXISTS ctl.user_domain_role CASCADE;")
