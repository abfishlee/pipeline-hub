"""dq.quality_result — DQ_CHECK 노드 결과 보관 (Phase 3.2.2).

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-25 23:30:00+00:00

DQ_CHECK 노드가 자산(table) 의 어떤 검사를 수행했고 통과/실패했는지 영속화한다.
Phase 3.2.4 의 SQL Studio 승인 플로우와 결합 시 같은 dq schema 의 추가 테이블
(rule, run, severity 등) 이 들어올 수 있다.

설계:
  - check_kind: row_count_min / null_pct_max / unique_columns / custom_sql
  - passed BOOLEAN — 단순 통과 여부. 세부 score 는 details_json 에.
  - run_id / node_run_id 로 pipeline 실행 단위 추적.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dq.quality_result (
            quality_result_id  BIGSERIAL PRIMARY KEY,
            pipeline_run_id    BIGINT,
            node_run_id        BIGINT,
            target_table       TEXT NOT NULL,
            check_kind         TEXT NOT NULL,
            passed             BOOLEAN NOT NULL,
            severity           TEXT NOT NULL DEFAULT 'WARN',
            details_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_dq_severity CHECK (severity IN ('INFO','WARN','ERROR','BLOCK')),
            CONSTRAINT ck_dq_check_kind CHECK (
                check_kind IN ('row_count_min','null_pct_max','unique_columns','custom_sql')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX dq_quality_result_run_idx "
        "ON dq.quality_result (pipeline_run_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX dq_quality_result_failed_idx "
        "ON dq.quality_result (target_table, created_at DESC) WHERE passed = FALSE;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dq.quality_result CASCADE;")
