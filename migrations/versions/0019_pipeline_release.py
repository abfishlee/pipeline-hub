"""wf.pipeline_release — DRAFT → PUBLISHED 배포 이력 (Phase 3.2.6).

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-26 09:00:00+00:00

설계:
  - PUBLISHED 전환은 같은 `workflow_definition.name` 안에서 새 PUBLISHED row 를 만들어
    `version_no` (workflow_definition.version 컬럼) 를 자동 증가시킨다. 이때 nodes/edges
    그래프를 그대로 복제해서 향후 원본 DRAFT 가 변경돼도 PUBLISHED 는 동결된다.
  - 본 테이블은 그 배포 사실 + 변경 요약 + 스냅샷을 영속화 — 운영자/리뷰어가 어느 시점에
    무엇을 prod 로 띄웠는지 회고 가능.
  - source_workflow_id : 배포 직전 사용자가 편집했던 DRAFT (참고용, 이후 삭제될 수 있음)
  - released_workflow_id: 새로 만들어진 PUBLISHED 워크플로 (상시 보존)
  - change_summary: `{added: [...node_key], removed: [...], changed: [...]}` 형식
  - nodes_snapshot / edges_snapshot: 배포 시점의 전체 그래프 (자세한 diff 재계산 가능)

`workflow_definition.name + version` 은 이미 UNIQUE — 같은 name 안에서 release 의
version 도 자연스럽게 시간순 정렬된다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE wf.pipeline_release (
            release_id            BIGSERIAL PRIMARY KEY,
            workflow_name         TEXT NOT NULL,
            version_no            INTEGER NOT NULL,
            source_workflow_id    BIGINT REFERENCES wf.workflow_definition(workflow_id)
                                    ON DELETE SET NULL,
            released_workflow_id  BIGINT NOT NULL REFERENCES wf.workflow_definition(workflow_id)
                                    ON DELETE CASCADE,
            released_by           BIGINT REFERENCES ctl.app_user(user_id),
            released_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            change_summary        JSONB NOT NULL DEFAULT '{}'::jsonb,
            nodes_snapshot        JSONB NOT NULL DEFAULT '[]'::jsonb,
            edges_snapshot        JSONB NOT NULL DEFAULT '[]'::jsonb,
            CONSTRAINT uq_pipeline_release_name_version UNIQUE (workflow_name, version_no)
        );
        """
    )
    op.execute(
        "CREATE INDEX wf_pipeline_release_name_idx "
        "ON wf.pipeline_release (workflow_name, released_at DESC);"
    )
    op.execute(
        "CREATE INDEX wf_pipeline_release_released_workflow_idx "
        "ON wf.pipeline_release (released_workflow_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wf.pipeline_release CASCADE;")
