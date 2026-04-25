"""run.crowd_task — OCR confidence 미달 시 검수 대기열 (Phase 4 정식 검수 placeholder).

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-25 18:00:00+00:00

Phase 2.2.4 OCR 파이프라인이 confidence < 0.85 인 결과를 만나면 자동으로 정리된 작업
큐에 적재. Phase 4 에서 정식 Crowd 검수 UI 도입 시 컬럼 보강 / 별도 스키마 분리 예정.

스키마는 `run` (workflow / runtime artifacts) — Crowd 정식 모듈은 Phase 4 에서
독자 schema (`crowd.*`) 로 분리할 수 있다. 그 시점엔 별도 migration 으로 이관.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE run.crowd_task (
            crowd_task_id     BIGSERIAL PRIMARY KEY,
            raw_object_id     BIGINT NOT NULL,
            partition_date    DATE NOT NULL,
            ocr_result_id     BIGINT,
            reason            TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'PENDING',
            payload_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
            assigned_to       BIGINT REFERENCES ctl.app_user(user_id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_at       TIMESTAMPTZ,
            reviewed_by       BIGINT REFERENCES ctl.app_user(user_id),
            CONSTRAINT ck_crowd_task_status CHECK (
                status IN ('PENDING','REVIEWING','APPROVED','REJECTED')
            ),
            CONSTRAINT ck_crowd_task_reason CHECK (length(reason) BETWEEN 1 AND 200)
        );
        """
    )
    # 운영자 큐 조회 (PENDING + 오래된 순) 가속
    op.execute(
        "CREATE INDEX crowd_task_pending_idx "
        "ON run.crowd_task (created_at) WHERE status = 'PENDING';"
    )
    # raw 추적 — 같은 raw_object 의 task 조회
    op.execute(
        "CREATE INDEX crowd_task_raw_idx "
        "ON run.crowd_task (raw_object_id, partition_date);"
    )
    # 통계용 시간축 (BRIN — 1년 누적 시 디스크 절약)
    op.execute(
        "CREATE INDEX crowd_task_created_brin "
        "ON run.crowd_task USING BRIN (created_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run.crowd_task CASCADE;")
