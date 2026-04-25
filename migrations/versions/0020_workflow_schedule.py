"""wf.workflow_definition: schedule_cron + schedule_enabled (Phase 3.2.7).

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-26 11:00:00+00:00

배치 스케줄 관리 — 사용자가 워크플로 단위로 cron 표현식을 등록하면 외부 스케줄러
(Phase 4 Airflow / Phase 3 한정 manual cron)가 그 시간에 자동 실행한다. Phase 3.2.7
범위에서는:

  - 스키마 + UI 편집 (cron 검증) + Backfill 시작점.
  - 실제 cron 트리거는 Phase 4 Airflow 통합과 함께 — 이 sub-phase 는 메타 + UI 만.

설계:
  - schedule_cron TEXT NULL — 빈 값이면 자동 실행 안 함.
  - schedule_enabled BOOL DEFAULT FALSE — cron 이 있어도 운영자가 켜야 active.
  - PUBLISHED 워크플로 1개만 같은 name 안에서 active 가 의미 있어 별도 UNIQUE 는 두지 않음.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE wf.workflow_definition
            ADD COLUMN schedule_cron    TEXT,
            ADD COLUMN schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )
    op.execute(
        "CREATE INDEX wf_workflow_schedule_active_idx "
        "ON wf.workflow_definition (schedule_enabled, status) "
        "WHERE schedule_enabled = TRUE AND status = 'PUBLISHED';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS wf.wf_workflow_schedule_active_idx;")
    op.execute(
        "ALTER TABLE wf.workflow_definition "
        "DROP COLUMN IF EXISTS schedule_enabled, "
        "DROP COLUMN IF EXISTS schedule_cron;"
    )
