"""Phase 5.2.2 — wf.node_definition.node_type CHECK 확장 (v2 generic 노드 카탈로그).

Revision ID: 0040
Revises: 0039
Create Date: 2026-04-27 02:30:00+00:00

배경:
  * 0015 의 ck_node_type 은 v1 7종 (NOOP/SOURCE_API/SQL_TRANSFORM/DEDUP/DQ_CHECK/
    LOAD_MASTER/NOTIFY) 만 허용.
  * Phase 5.2.2 STEP 5 에서 v2 generic 6종 추가:
      MAP_FIELDS / SQL_INLINE_TRANSFORM / SQL_ASSET_TRANSFORM / HTTP_TRANSFORM /
      FUNCTION_TRANSFORM / LOAD_TARGET
  * v2 placeholder (STEP 6+):
      OCR_TRANSFORM / CRAWL_FETCH / STANDARDIZE / SOURCE_DATA

CHECK 자체를 *완전히 제거* 하지 않고 *확장* — DB 가 미상 type 을 거부하도록 유지.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
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
    # placeholders (STEP 6+).
    "OCR_TRANSFORM",
    "CRAWL_FETCH",
    "STANDARDIZE",
    "SOURCE_DATA",
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
    quoted = ",".join(f"'{t}'" for t in _V1_TYPES)
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )
