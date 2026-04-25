"""raw_object idempotency partial index (for /v1/ingest/* dedup lookup)

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-25 13:00:00+00:00

Phase 1.2.7 수집 API 에서 Idempotency-Key 헤더 기반 dedup 조회를 가속한다.
파티션 부모에 생성하면 모든 child 에 자동 적용.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX raw_object_idempotency_idx
            ON raw.raw_object (source_id, idempotency_key, partition_date)
            WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS raw.raw_object_idempotency_idx;")
