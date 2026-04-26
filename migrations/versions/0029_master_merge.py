"""Phase 4.2.8 — Multi-source 머지: mart.master_merge_op 신설 + Crowd PRODUCT_MATCHING.

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-26 23:00:00+00:00

설계:
  - 기존 `mart.master_entity_history` 는 *행 단위 SCD2* — 한 entity 의 시간축 변경 이력.
  - 본 마이그는 *N→1 머지 작업 1건* 을 별도 테이블 `mart.master_merge_op` 으로 분리:
    - source_product_ids JSONB 배열, target_product_id, merge_at, merged_by, reason
    - is_unmerged BOOL — un-merge 시 행 추가하지 않고 본 행에 마킹 + un-merge 이력 행
      별도 추가
  - product_mapping 의 product_id 가 머지 후 target 으로 갱신 — retailer_product_code
    는 모두 보존.
  - Crowd `PRODUCT_MATCHING` 작업 종류 추가 (run.crowd_task.reason 컬럼은 free-form
    이라 별도 enum 추가 X — 표준 reason 문자열 'PRODUCT_MATCHING' 사용).

본 마이그는 master_entity_history 변경 없음. mart.master_merge_op 신설만.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE mart.master_merge_op (
            merge_op_id          BIGSERIAL PRIMARY KEY,
            source_product_ids   JSONB NOT NULL,
            target_product_id    BIGINT NOT NULL REFERENCES mart.product_master(product_id),
            merged_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            merged_by            BIGINT REFERENCES ctl.app_user(user_id),
            reason               TEXT,
            is_unmerged          BOOLEAN NOT NULL DEFAULT FALSE,
            unmerged_at          TIMESTAMPTZ,
            unmerged_by          BIGINT REFERENCES ctl.app_user(user_id),
            mapping_count        INTEGER,
            CONSTRAINT ck_master_merge_op_sources CHECK (
                jsonb_typeof(source_product_ids) = 'array'
                AND jsonb_array_length(source_product_ids) >= 1
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX mart_master_merge_op_target_idx "
        "ON mart.master_merge_op (target_product_id, merged_at DESC);"
    )
    op.execute(
        "CREATE INDEX mart_master_merge_op_unmerged_idx "
        "ON mart.master_merge_op (is_unmerged, merged_at DESC) "
        "WHERE is_unmerged = false;"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON mart.master_merge_op TO app_rw, app_mart_write;"
        " GRANT USAGE, SELECT ON SEQUENCE mart.master_merge_op_merge_op_id_seq "
        " TO app_rw, app_mart_write;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mart.master_merge_op CASCADE;")
