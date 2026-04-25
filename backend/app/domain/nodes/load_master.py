"""LOAD_MASTER 노드 — sandbox 결과를 mart 테이블에 UPSERT.

config:
  - `source_table`: schema.table (필수, wf 또는 stg 만 — sandbox 결과)
  - `target_table`: schema.table (필수, mart.* 만)
  - `key_columns`: list[str] — ON CONFLICT 키
  - `update_columns`: list[str] | None — 명시 시 그 컬럼만 UPDATE.
    None 이면 source 와 target 의 공통 non-key 컬럼 자동 추출.

권한 — `INSERT/UPDATE` 가 mart 에 직접 — Phase 3.2.1 의 trigger_run 에서
ADMIN/APPROVER 만 통과하므로 노드 단계에서 추가 검사는 안 함 (이중 검사는
Phase 4 에서 사용자 정의 권한 체계와 결합).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes import NodeContext, NodeError, NodeOutput

name = "LOAD_MASTER"

_TABLE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]{0,62})\.([a-zA-Z_][a-zA-Z0-9_]{0,62})$")
_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")

_SOURCE_SCHEMAS: frozenset[str] = frozenset({"wf", "stg"})
_TARGET_SCHEMAS: frozenset[str] = frozenset({"mart"})


def _quote_table(table: str, *, allow: frozenset[str]) -> tuple[str, str, str]:
    m = _TABLE_RE.match(table)
    if m is None:
        raise NodeError(f"invalid table reference: {table!r}")
    schema, name_only = m.group(1), m.group(2)
    if schema.lower() not in allow:
        raise NodeError(f"schema '{schema}' not in {sorted(allow)}")
    return schema, name_only, f'"{schema}"."{name_only}"'


def _quote_col(c: str) -> str:
    if not _COLUMN_RE.match(c):
        raise NodeError(f"invalid column: {c!r}")
    return f'"{c}"'


def _columns_of(session: Any, *, schema: str, table: str) -> list[str]:
    rows = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    ).all()
    return [str(r.column_name) for r in rows]


def run(context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
    source_raw = str(config.get("source_table") or "").strip()
    target_raw = str(config.get("target_table") or "").strip()
    key_columns_raw = list(config.get("key_columns") or [])
    update_columns_raw = config.get("update_columns")

    if not key_columns_raw:
        raise NodeError("LOAD_MASTER requires `key_columns` (1+)")

    src_schema, src_name, src_qualified = _quote_table(source_raw, allow=_SOURCE_SCHEMAS)
    tgt_schema, tgt_name, tgt_qualified = _quote_table(target_raw, allow=_TARGET_SCHEMAS)

    src_cols = _columns_of(context.session, schema=src_schema, table=src_name)
    tgt_cols = _columns_of(context.session, schema=tgt_schema, table=tgt_name)
    if not src_cols:
        raise NodeError(f"source table {source_raw} has no columns or doesn't exist")
    if not tgt_cols:
        raise NodeError(f"target table {target_raw} has no columns or doesn't exist")

    common = [c for c in src_cols if c in tgt_cols]
    if not common:
        raise NodeError(f"no common columns between {source_raw} and {target_raw}")

    key_columns = [str(c) for c in key_columns_raw]
    for k in key_columns:
        if k not in common:
            raise NodeError(f"key column '{k}' not present in both tables")

    if update_columns_raw is None:
        update_cols = [c for c in common if c not in key_columns]
    else:
        update_cols = [str(c) for c in update_columns_raw]
        for u in update_cols:
            if u not in common:
                raise NodeError(f"update column '{u}' not present in both tables")

    insert_cols = key_columns + [c for c in update_cols if c not in key_columns]
    insert_cols_q = ", ".join(_quote_col(c) for c in insert_cols)
    select_cols_q = ", ".join(_quote_col(c) for c in insert_cols)
    conflict_cols_q = ", ".join(_quote_col(c) for c in key_columns)
    if update_cols:
        update_clause = ", ".join(
            f"{_quote_col(c)} = EXCLUDED.{_quote_col(c)}" for c in update_cols
        )
        upsert = (
            f"INSERT INTO {tgt_qualified} ({insert_cols_q}) "
            f"SELECT {select_cols_q} FROM {src_qualified} "
            f"ON CONFLICT ({conflict_cols_q}) DO UPDATE SET {update_clause}"
        )
    else:
        upsert = (
            f"INSERT INTO {tgt_qualified} ({insert_cols_q}) "
            f"SELECT {select_cols_q} FROM {src_qualified} "
            f"ON CONFLICT ({conflict_cols_q}) DO NOTHING"
        )
    result = context.session.execute(text(upsert))
    row_count = int(getattr(result, "rowcount", 0) or 0)

    return NodeOutput(
        status="success",
        row_count=row_count,
        payload={
            "source_table": source_raw,
            "target_table": target_raw,
            "key_columns": key_columns,
            "update_columns": update_cols,
            "rows_affected": row_count,
        },
    )


__all__ = ["name", "run"]
