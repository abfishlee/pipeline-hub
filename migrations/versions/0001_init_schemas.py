"""init schemas + extensions

Revision ID: 0001
Revises:
Create Date: 2026-04-25 09:00:00+00:00

스키마: ctl, raw, stg, mart, run, audit, wf, dq
확장: pgcrypto, pg_trgm, btree_gin

docs/03_DATA_MODEL.md 3.1 정합.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS: tuple[str, ...] = ("ctl", "raw", "stg", "mart", "run", "audit", "wf", "dq")
EXTENSIONS: tuple[str, ...] = ("pgcrypto", "pg_trgm", "btree_gin")


def upgrade() -> None:
    for ext in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')

    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    # 스키마 삭제는 의존 객체와 함께 (CASCADE).
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    # 확장은 보존 (다른 DB 에서도 일반적이므로 강제 제거 안 함).
