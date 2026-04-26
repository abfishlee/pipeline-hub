"""Phase 4.2.2 — DQ 게이트: pipeline_run.status ON_HOLD + run.hold_decision + dq.quality_result 확장.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-26 14:00:00+00:00

변경:
  1. run.pipeline_run CHECK 에 'ON_HOLD' 추가.
  2. dq.quality_result 에 status (PASS/FAIL/WARN) + sample_json 컬럼 추가.
  3. run.hold_decision 신설 — 승인자/반려 이력.

ON_HOLD 정책:
  - DQ_CHECK 노드가 severity ERROR/BLOCK 으로 실패하면 pipeline_run = ON_HOLD.
  - 후속 노드는 SKIPPED 가 아닌 PENDING 유지 (승인 시 재실행).
  - APPROVER 가 승인 → pipeline_run.status = RUNNING + 후속 노드 READY 마킹.
  - APPROVER 가 반려 → pipeline_run.status = CANCELLED + stg rollback.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. pipeline_run CHECK 확장 — ON_HOLD 추가.
    op.execute(
        "ALTER TABLE run.pipeline_run "
        "DROP CONSTRAINT IF EXISTS ck_pipeline_run_status;"
    )
    op.execute(
        "ALTER TABLE run.pipeline_run "
        "ADD CONSTRAINT ck_pipeline_run_status "
        "CHECK (status IN ('PENDING','RUNNING','ON_HOLD','SUCCESS','FAILED','CANCELLED'));"
    )

    # 2. dq.quality_result — status + sample_json 추가.
    op.execute(
        """
        ALTER TABLE dq.quality_result
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'PASS',
            ADD COLUMN IF NOT EXISTS sample_json JSONB NOT NULL DEFAULT '[]'::jsonb;
        """
    )
    # 기존 row 마이그 — passed=true → PASS, passed=false + WARN → WARN, 그 외 → FAIL.
    op.execute(
        """
        UPDATE dq.quality_result
           SET status = CASE
                WHEN passed = true THEN 'PASS'
                WHEN severity = 'WARN' THEN 'WARN'
                ELSE 'FAIL'
            END
         WHERE status = 'PASS';  -- 새 컬럼이라 모든 row 가 PASS, 위 CASE 로 재계산.
        """
    )
    op.execute(
        "ALTER TABLE dq.quality_result "
        "ADD CONSTRAINT ck_dq_quality_status "
        "CHECK (status IN ('PASS','WARN','FAIL'));"
    )
    op.execute(
        "CREATE INDEX dq_quality_result_failed_status_idx "
        "ON dq.quality_result (pipeline_run_id, created_at DESC) "
        "WHERE status = 'FAIL';"
    )

    # 3. run.hold_decision — 승인/반려 이력.
    op.execute(
        """
        CREATE TABLE run.hold_decision (
            decision_id      BIGSERIAL PRIMARY KEY,
            pipeline_run_id  BIGINT NOT NULL,
            run_date         DATE NOT NULL,
            decision         TEXT NOT NULL,
            signer_user_id   BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
            reason           TEXT,
            quality_result_ids BIGINT[] NOT NULL DEFAULT '{}'::bigint[],
            occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_hold_decision_decision CHECK (decision IN ('APPROVE','REJECT'))
        );
        """
    )
    op.execute(
        "CREATE INDEX run_hold_decision_run_idx "
        "ON run.hold_decision (pipeline_run_id, occurred_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run.hold_decision CASCADE;")
    op.execute("DROP INDEX IF EXISTS dq.dq_quality_result_failed_status_idx;")
    op.execute("ALTER TABLE dq.quality_result DROP CONSTRAINT IF EXISTS ck_dq_quality_status;")
    op.execute(
        "ALTER TABLE dq.quality_result "
        "DROP COLUMN IF EXISTS sample_json, "
        "DROP COLUMN IF EXISTS status;"
    )
    op.execute(
        "ALTER TABLE run.pipeline_run DROP CONSTRAINT IF EXISTS ck_pipeline_run_status;"
    )
    op.execute(
        "ALTER TABLE run.pipeline_run "
        "ADD CONSTRAINT ck_pipeline_run_status "
        "CHECK (status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED'));"
    )
