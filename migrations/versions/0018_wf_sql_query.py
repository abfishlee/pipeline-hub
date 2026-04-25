"""wf.sql_query + wf.sql_query_version — SQL Studio 승인 플로우 (Phase 3.2.5).

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-25 23:55:00+00:00

설계:
  - sql_query: 사용자 관리하는 SQL 자산의 메타 (이름/오너/현재 versionFK).
  - sql_query_version: 실제 SQL 본문 + 라이프사이클 (DRAFT→PENDING→APPROVED/REJECTED).
    parent_version_id 로 이력을 추적 (chain 형태).
  - 승인된 버전만 SQL_TRANSFORM 노드 config_json.sql 으로 재사용 가능 (Phase 3.2.5 후속
    UI 통합).

`audit.sql_execution_log` 는 0005 에서 이미 존재 — 본 마이그레이션은 sql_query_version_id
컬럼 + FK 만 ADD COLUMN 으로 확장 (PREVIEW/EXPLAIN 시 어느 버전을 실행했는지 추적).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- wf.sql_query ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE wf.sql_query (
            sql_query_id        BIGSERIAL PRIMARY KEY,
            name                TEXT NOT NULL,
            description         TEXT,
            owner_user_id       BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
            current_version_id  BIGINT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sql_query_name UNIQUE (name)
        );
        """
    )
    op.execute(
        "CREATE INDEX wf_sql_query_owner_idx ON wf.sql_query (owner_user_id, updated_at DESC);"
    )

    # --- wf.sql_query_version ------------------------------------------
    op.execute(
        """
        CREATE TABLE wf.sql_query_version (
            sql_query_version_id   BIGSERIAL PRIMARY KEY,
            sql_query_id           BIGINT NOT NULL REFERENCES wf.sql_query(sql_query_id)
                                        ON DELETE CASCADE,
            version_no             INTEGER NOT NULL,
            sql_text               TEXT NOT NULL,
            referenced_tables      JSONB NOT NULL DEFAULT '[]'::jsonb,
            status                 TEXT NOT NULL DEFAULT 'DRAFT',
            parent_version_id      BIGINT REFERENCES wf.sql_query_version(sql_query_version_id),
            submitted_by           BIGINT REFERENCES ctl.app_user(user_id),
            submitted_at           TIMESTAMPTZ,
            reviewed_by            BIGINT REFERENCES ctl.app_user(user_id),
            reviewed_at            TIMESTAMPTZ,
            review_comment         TEXT,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sql_query_version_no UNIQUE (sql_query_id, version_no),
            CONSTRAINT ck_sql_query_version_status CHECK (
                status IN ('DRAFT','PENDING','APPROVED','REJECTED','SUPERSEDED')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX wf_sql_query_version_status_idx "
        "ON wf.sql_query_version (status, sql_query_id);"
    )
    # 본문 sql_query 의 current_version_id 가 sql_query_version 을 가리키도록 FK 후행 추가.
    op.execute(
        """
        ALTER TABLE wf.sql_query
            ADD CONSTRAINT fk_sql_query_current_version
            FOREIGN KEY (current_version_id)
            REFERENCES wf.sql_query_version(sql_query_version_id)
            ON DELETE SET NULL;
        """
    )

    # --- audit.sql_execution_log: 어떤 버전을 실행했는지 추적 + kind 확장 -----
    op.execute(
        """
        ALTER TABLE audit.sql_execution_log
            ADD COLUMN sql_query_version_id BIGINT
                REFERENCES wf.sql_query_version(sql_query_version_id);
        """
    )
    op.execute(
        "CREATE INDEX audit_sql_log_version_idx "
        "ON audit.sql_execution_log (sql_query_version_id, started_at DESC) "
        "WHERE sql_query_version_id IS NOT NULL;"
    )
    # 0005 의 execution_kind CHECK 는 (PREVIEW,SANDBOX,APPROVED,SCHEDULED) 만 허용.
    # SQL Studio 가 VALIDATE/EXPLAIN 도 audit 에 남기도록 확장.
    op.execute(
        "ALTER TABLE audit.sql_execution_log "
        "DROP CONSTRAINT IF EXISTS ck_sql_execution_log_kind;"
    )
    op.execute(
        "ALTER TABLE audit.sql_execution_log "
        "ADD CONSTRAINT ck_sql_execution_log_kind "
        "CHECK (execution_kind IN "
        "('VALIDATE','PREVIEW','EXPLAIN','SANDBOX','APPROVED','SCHEDULED'));"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE audit.sql_execution_log "
        "DROP CONSTRAINT IF EXISTS ck_sql_execution_log_kind;"
    )
    op.execute(
        "ALTER TABLE audit.sql_execution_log "
        "ADD CONSTRAINT ck_sql_execution_log_kind "
        "CHECK (execution_kind IN ('PREVIEW','SANDBOX','APPROVED','SCHEDULED'));"
    )
    op.execute("DROP INDEX IF EXISTS audit.audit_sql_log_version_idx;")
    op.execute("ALTER TABLE audit.sql_execution_log DROP COLUMN IF EXISTS sql_query_version_id;")
    op.execute(
        "ALTER TABLE wf.sql_query DROP CONSTRAINT IF EXISTS fk_sql_query_current_version;"
    )
    op.execute("DROP TABLE IF EXISTS wf.sql_query_version CASCADE;")
    op.execute("DROP TABLE IF EXISTS wf.sql_query CASCADE;")
