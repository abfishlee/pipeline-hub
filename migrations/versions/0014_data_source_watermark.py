"""ctl.data_source 에 watermark JSONB 컬럼 추가 (DB-to-DB 증분 수집용).

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-25 21:00:00+00:00

Phase 2.2.7 DB-to-DB 커넥터. 외부 DB 의 cursor 컬럼을 추적해 다음 pull 의 시작점으로
사용. 형식:
    {
      "last_cursor": "2026-04-25T10:23:45+00:00" | "1234567" | <기타>,
      "last_run_at": "2026-04-25T10:24:00+00:00",
      "last_count": 0
    }

기존 row 는 `{}` 로 fallback (빈 dict 면 처음부터 fetch).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ctl.data_source
            ADD COLUMN IF NOT EXISTS watermark JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ctl.data_source DROP COLUMN IF EXISTS watermark;")
