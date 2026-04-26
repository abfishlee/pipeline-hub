"""Phase 6 Wave 1 — wf.node_definition.ck_node_type 에 PUBLIC_API_FETCH 추가.

Revision ID: 0047
Revises: 0046
Create Date: 2026-04-27 10:00:00+00:00

generic Public API 노드를 캔버스에서 박스로 끌어올 수 있게 하기 위해 CHECK 확장.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V1_TYPES = (
    "NOOP",
    "SOURCE_API",
    "SQL_TRANSFORM",
    "DEDUP",
    "DQ_CHECK",
    "LOAD_MASTER",
    "NOTIFY",
)

_V2_TYPES = (
    "MAP_FIELDS",
    "SQL_INLINE_TRANSFORM",
    "SQL_ASSET_TRANSFORM",
    "HTTP_TRANSFORM",
    "FUNCTION_TRANSFORM",
    "LOAD_TARGET",
    "OCR_TRANSFORM",
    "CRAWL_FETCH",
    "STANDARDIZE",
    "SOURCE_DATA",
    "PUBLIC_API_FETCH",  # ← 신규 (Phase 6)
)


def upgrade() -> None:
    op.execute("ALTER TABLE wf.node_definition DROP CONSTRAINT IF EXISTS ck_node_type;")
    quoted = ",".join(f"'{t}'" for t in (*_V1_TYPES, *_V2_TYPES))
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE wf.node_definition DROP CONSTRAINT IF EXISTS ck_node_type;")
    quoted = ",".join(
        f"'{t}'" for t in (*_V1_TYPES, *(t for t in _V2_TYPES if t != "PUBLIC_API_FETCH"))
    )
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )
