"""wf schema: workflow_definition + node_definition + edge_definition.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-25 22:00:00+00:00

Phase 3.2.1 Pipeline Runtime 의 메타정의. 사용자가 Visual ETL Designer 로 그린
DAG 를 영속화한다. 실행 이력은 0016 (`run.pipeline_run` / `run.node_run`).

설계 메모:
  - workflow_definition.status — DRAFT(편집 가능) / PUBLISHED(편집 잠금, 실행 가능)
    / ARCHIVED(비활성).
  - PUBLISHED 는 새 row 로 version 증가. 같은 (name, version) 은 UNIQUE.
  - node_key 는 workflow 내부 식별자 (사용자가 짓는 영문 slug). FK 는 BIGINT id 로
    걸지만 운영 / lineage 추적에는 node_key 가 더 직관적.
  - edge.condition_expr 는 JSON (Phase 3.2.2 에서 평가 — 본 commit 에서는 보관만).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- wf.workflow_definition ---
    op.execute(
        """
        CREATE TABLE wf.workflow_definition (
            workflow_id   BIGSERIAL PRIMARY KEY,
            name          TEXT NOT NULL,
            version       INTEGER NOT NULL DEFAULT 1,
            description   TEXT,
            status        TEXT NOT NULL DEFAULT 'DRAFT',
            created_by    BIGINT REFERENCES ctl.app_user(user_id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at  TIMESTAMPTZ,
            CONSTRAINT uq_workflow_name_version UNIQUE (name, version),
            CONSTRAINT ck_workflow_status CHECK (status IN ('DRAFT','PUBLISHED','ARCHIVED'))
        );
        """
    )
    op.execute(
        "CREATE INDEX wf_workflow_status_idx ON wf.workflow_definition (status, updated_at DESC);"
    )

    # --- wf.node_definition ---
    op.execute(
        """
        CREATE TABLE wf.node_definition (
            node_id       BIGSERIAL PRIMARY KEY,
            workflow_id   BIGINT NOT NULL REFERENCES wf.workflow_definition(workflow_id) ON DELETE CASCADE,
            node_key      TEXT NOT NULL,
            node_type     TEXT NOT NULL,
            config_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
            position_x    INTEGER NOT NULL DEFAULT 0,
            position_y    INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_node_workflow_key UNIQUE (workflow_id, node_key),
            CONSTRAINT ck_node_type CHECK (node_type IN (
                'NOOP','SOURCE_API','SQL_TRANSFORM','DEDUP','DQ_CHECK','LOAD_MASTER','NOTIFY'
            ))
        );
        """
    )
    op.execute("CREATE INDEX wf_node_workflow_idx ON wf.node_definition (workflow_id);")

    # --- wf.edge_definition ---
    op.execute(
        """
        CREATE TABLE wf.edge_definition (
            edge_id        BIGSERIAL PRIMARY KEY,
            workflow_id    BIGINT NOT NULL REFERENCES wf.workflow_definition(workflow_id) ON DELETE CASCADE,
            from_node_id   BIGINT NOT NULL REFERENCES wf.node_definition(node_id) ON DELETE CASCADE,
            to_node_id     BIGINT NOT NULL REFERENCES wf.node_definition(node_id) ON DELETE CASCADE,
            condition_expr JSONB,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_edge_workflow_pair UNIQUE (workflow_id, from_node_id, to_node_id),
            CONSTRAINT ck_edge_no_self_loop CHECK (from_node_id <> to_node_id)
        );
        """
    )
    op.execute("CREATE INDEX wf_edge_workflow_idx ON wf.edge_definition (workflow_id);")
    op.execute("CREATE INDEX wf_edge_to_node_idx ON wf.edge_definition (to_node_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wf.edge_definition CASCADE;")
    op.execute("DROP TABLE IF EXISTS wf.node_definition CASCADE;")
    op.execute("DROP TABLE IF EXISTS wf.workflow_definition CASCADE;")
