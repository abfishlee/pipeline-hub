"""processed_event PK 를 (event_id, consumer_name) 합성으로 변경.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-25 14:00:00+00:00

Phase 2.2.2 이벤트 버스 도입에 맞춰 multi-consumer 시나리오 지원.
0004 에서 `event_id TEXT PRIMARY KEY` 단일 PK 였으나, 같은 event_id 를 여러 consumer
가 각자 처리해야 하는 패턴(outbox 발행 1건 → ocr/transform/etc 다중 소비)에서는 충돌
한다. PK 를 (event_id, consumer_name) 합성으로 변경.

기존 환경 호환:
- 0004 적용 후 운영 데이터가 있어도 row 는 보존되며 PK 만 재생성.
- 현재 까지는 consumer 가 없어 0행이 일반적이지만 안전하게 진행.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE run.processed_event
            DROP CONSTRAINT IF EXISTS processed_event_pkey;
        """
    )
    op.execute(
        """
        ALTER TABLE run.processed_event
            ADD CONSTRAINT processed_event_pkey
            PRIMARY KEY (event_id, consumer_name);
        """
    )


def downgrade() -> None:
    # 합성 PK → 단일 PK 환원. consumer_name 가 다른 중복 event_id 가 있으면 실패하므로
    # 운영 환경에서는 downgrade 전 수동 정리 필요.
    op.execute(
        """
        ALTER TABLE run.processed_event
            DROP CONSTRAINT IF EXISTS processed_event_pkey;
        """
    )
    op.execute(
        """
        ALTER TABLE run.processed_event
            ADD CONSTRAINT processed_event_pkey
            PRIMARY KEY (event_id);
        """
    )
