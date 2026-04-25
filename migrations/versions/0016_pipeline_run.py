"""run.pipeline_run + run.node_run (Phase 3.2.1).

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-25 22:30:00+00:00

Pipeline 실행 이력. `run_date` 기준 RANGE 파티션 (월별, 2026-04 ~ 2026-12 9개월
사전 생성). 운영 시 매월 1일 03:00 Airflow DAG 가 다음 달 파티션 자동 생성 (Phase
2.2.3 후속 시스템 DAG).

`node_run.status` 상태 머신:
    PENDING  → READY  (모든 입력 노드가 SUCCESS 일 때 dispatcher 가 전이)
    READY    → RUNNING(actor 가 시작)
    RUNNING  → SUCCESS / FAILED / SKIPPED
    *        → CANCELLED (사용자 취소 — pipeline 단위)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONTHS: tuple[tuple[int, int], ...] = (
    (2026, 4),
    (2026, 5),
    (2026, 6),
    (2026, 7),
    (2026, 8),
    (2026, 9),
    (2026, 10),
    (2026, 11),
    (2026, 12),
)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def upgrade() -> None:
    # --- run.pipeline_run (PARTITIONED) ---
    op.execute(
        """
        CREATE TABLE run.pipeline_run (
            pipeline_run_id  BIGSERIAL,
            workflow_id      BIGINT NOT NULL REFERENCES wf.workflow_definition(workflow_id),
            run_date         DATE NOT NULL DEFAULT CURRENT_DATE,
            status           TEXT NOT NULL DEFAULT 'PENDING',
            triggered_by     BIGINT REFERENCES ctl.app_user(user_id),
            started_at       TIMESTAMPTZ,
            finished_at      TIMESTAMPTZ,
            error_message    TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_pipeline_run PRIMARY KEY (pipeline_run_id, run_date),
            CONSTRAINT ck_pipeline_run_status CHECK (
                status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED')
            )
        ) PARTITION BY RANGE (run_date);
        """
    )
    for year, month in _MONTHS:
        ny, nm = _next_month(year, month)
        partition = f"pipeline_run_{year}_{month:02d}"
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS run.{partition}
                PARTITION OF run.pipeline_run
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{ny}-{nm:02d}-01');
            """
        )
    op.execute(
        "CREATE INDEX pipeline_run_workflow_idx "
        "ON run.pipeline_run (workflow_id, started_at DESC);"
    )
    op.execute(
        "CREATE INDEX pipeline_run_status_idx "
        "ON run.pipeline_run (status, created_at DESC) WHERE status IN ('PENDING','RUNNING');"
    )
    op.execute(
        "CREATE INDEX pipeline_run_started_brin "
        "ON run.pipeline_run USING BRIN (started_at);"
    )

    # --- run.node_run ---
    # 별도 파티션 안 함 (월별 row 수가 pipeline_run × node 수 — 소규모 가정).
    # 운영에서 큰 부담이면 후속 migration 으로 파티션 도입.
    op.execute(
        """
        CREATE TABLE run.node_run (
            node_run_id        BIGSERIAL PRIMARY KEY,
            pipeline_run_id    BIGINT NOT NULL,
            run_date           DATE NOT NULL,
            node_definition_id BIGINT NOT NULL REFERENCES wf.node_definition(node_id),
            node_key           TEXT NOT NULL,
            node_type          TEXT NOT NULL,
            status             TEXT NOT NULL DEFAULT 'PENDING',
            attempt_no         INTEGER NOT NULL DEFAULT 0,
            started_at         TIMESTAMPTZ,
            finished_at        TIMESTAMPTZ,
            error_message      TEXT,
            output_json        JSONB,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_node_run_pipeline FOREIGN KEY (pipeline_run_id, run_date)
                REFERENCES run.pipeline_run(pipeline_run_id, run_date) ON DELETE CASCADE,
            CONSTRAINT ck_node_run_status CHECK (
                status IN ('PENDING','READY','RUNNING','SUCCESS','FAILED','SKIPPED','CANCELLED')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX node_run_pipeline_idx "
        "ON run.node_run (pipeline_run_id, run_date);"
    )
    op.execute(
        "CREATE INDEX node_run_status_idx "
        "ON run.node_run (status) WHERE status IN ('PENDING','READY','RUNNING');"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run.node_run CASCADE;")
    for year, month in _MONTHS:
        op.execute(f"DROP TABLE IF EXISTS run.pipeline_run_{year}_{month:02d} CASCADE;")
    op.execute("DROP TABLE IF EXISTS run.pipeline_run CASCADE;")
