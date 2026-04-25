"""DEDUP 노드 — `key_columns` 기준 중복 제거 후 sandbox 테이블 생성.

config:
  - `input_table`: schema.table (필수, wf/stg/mart 만)
  - `key_columns`: list[str] (필수, 1+개)
  - `output_table`: 결과 테이블 (선택, 기본 `wf.tmp_run_<run_id>_<node_key>_dedup`)
  - `keep`: 'first' | 'last' (기본 'first' — ctid 가장 작은 행 보존)

`SELECT DISTINCT ON (...)` 으로 deterministic dedup. 같은 key 그룹 내 어떤 행을
보존할지는 keep + ORDER BY 로 결정.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes import NodeContext, NodeError, NodeOutput
from app.integrations.sqlglot_validator import ALLOWED_SCHEMAS

name = "DEDUP"

_TABLE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]{0,62})\.([a-zA-Z_][a-zA-Z0-9_]{0,62})$")
_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_OUTPUT_TABLE_RE = re.compile(r"^wf\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _validate_table_ref(table: str, *, allow_schemas: frozenset[str] = ALLOWED_SCHEMAS) -> str:
    m = _TABLE_RE.match(table)
    if m is None:
        raise NodeError(f"input_table must be `schema.table` (got {table!r})")
    schema = m.group(1).lower()
    if schema not in allow_schemas:
        raise NodeError(f"schema '{schema}' not in allowlist {sorted(allow_schemas)}")
    return f'"{m.group(1)}"."{m.group(2)}"'


def _validate_columns(cols: list[str]) -> list[str]:
    if not cols:
        raise NodeError("key_columns must be 1+ columns")
    out = []
    for c in cols:
        if not isinstance(c, str) or not _COLUMN_RE.match(c):
            raise NodeError(f"invalid column name: {c!r}")
        out.append(f'"{c}"')
    return out


def run(context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
    input_table_raw = str(config.get("input_table") or "").strip()
    input_table = _validate_table_ref(input_table_raw)
    key_columns = _validate_columns(list(config.get("key_columns") or []))

    keep = str(config.get("keep") or "first").lower()
    if keep not in ("first", "last"):
        raise NodeError(f"keep must be 'first' or 'last' (got {keep!r})")

    safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", context.node_key)[:32]
    default_out = f"wf.tmp_run_{context.pipeline_run_id}_{safe_key}_dedup"
    output_table = str(config.get("output_table") or default_out)
    if not _OUTPUT_TABLE_RE.match(output_table):
        raise NodeError(f"output_table must match {_OUTPUT_TABLE_RE.pattern}")

    order_dir = "ASC" if keep == "first" else "DESC"
    cols_clause = ", ".join(key_columns)
    sql = (
        f"CREATE TABLE {output_table} AS "
        f"SELECT DISTINCT ON ({cols_clause}) * "
        f"FROM {input_table} "
        f"ORDER BY {cols_clause}, ctid {order_dir}"
    )
    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(text(sql))

    count = int(
        context.session.execute(text(f"SELECT COUNT(*) FROM {output_table}")).scalar_one() or 0
    )
    return NodeOutput(
        status="success",
        row_count=count,
        payload={
            "output_table": output_table,
            "input_table": input_table_raw,
            "key_columns": list(config.get("key_columns") or []),
            "keep": keep,
        },
    )


__all__ = ["name", "run"]
