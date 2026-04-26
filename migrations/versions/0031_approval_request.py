"""Phase 5.2.0 — 가드레일 인프라: ctl.approval_request (DRAFT→REVIEW→APPROVED→PUBLISHED).

Revision ID: 0031
Revises: 0030
Create Date: 2026-04-26 23:50:00+00:00

5.2.1 의 entity 테이블 (source_contract, field_mapping, dq_rule, mart_load_policy,
sql_asset) *모두* 를 동일 상태머신으로 다루기 위한 *generic* approval 이력.

설계:
  - 각 entity 가 자신의 status 컬럼 (DRAFT/REVIEW/APPROVED/PUBLISHED) 을 갖되,
    상태 *전이* 는 본 테이블에 1행 INSERT.
  - APPROVE/REJECT 의 명시적 결재자 + 시각 + 사유 보관.
  - Phase 5 MVP 는 ADMIN 1명 승인. 다중 승인 확장은 본 테이블에 N row INSERT 로
    표현 가능 (스키마 변경 X).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ctl.approval_request (
            request_id          BIGSERIAL PRIMARY KEY,
            entity_type         TEXT NOT NULL,
            entity_id           BIGINT NOT NULL,
            entity_version      INTEGER NOT NULL DEFAULT 1,
            from_status         TEXT NOT NULL,
            to_status           TEXT NOT NULL,
            requester_user_id   BIGINT REFERENCES ctl.app_user(user_id),
            approver_user_id    BIGINT REFERENCES ctl.app_user(user_id),
            reason              TEXT,
            decision            TEXT,
            decided_at          TIMESTAMPTZ,
            requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_approval_request_entity_type CHECK (
                entity_type IN (
                    'source_contract',
                    'field_mapping',
                    'dq_rule',
                    'mart_load_policy',
                    'sql_asset'
                )
            ),
            CONSTRAINT ck_approval_request_from_status CHECK (
                from_status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT ck_approval_request_to_status CHECK (
                to_status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT ck_approval_request_decision CHECK (
                decision IS NULL OR decision IN ('APPROVE','REJECT')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_approval_request_entity_idx "
        "ON ctl.approval_request (entity_type, entity_id, requested_at DESC);"
    )
    op.execute(
        "CREATE INDEX ctl_approval_request_pending_idx "
        "ON ctl.approval_request (entity_type, requested_at DESC) "
        "WHERE decided_at IS NULL;"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON ctl.approval_request TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE ctl.approval_request_request_id_seq TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ctl.approval_request CASCADE;")
