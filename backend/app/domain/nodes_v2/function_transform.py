"""FUNCTION_TRANSFORM 노드 — allowlist 함수만 행 단위 적용 (Q4 답변).

MAP_FIELDS 와 차이:
  * MAP_FIELDS = field_mapping registry 기반 (DB 등록 mapping).
  * FUNCTION_TRANSFORM = 노드 config 의 inline expressions. registry 미경유.

config:
  - `source_table`: str (필수) — 입력 sandbox.
  - `output_table`: str (선택) — 결과 sandbox FQDN.
  - `expressions`: dict[str, str] (필수) — `target_col → mini-DSL expression`.
        e.g. {"price_clean": "number.parse_decimal($price)",
              "addr_sido":  "address.extract_sido($address)"}
  - `pass_through`: list[str] (선택) — source 컬럼을 그대로 복사.
  - `limit_rows`: int (기본 100_000).
  - `on_function_error`: 'skip_row' | 'fail_node' (기본 'fail_node').
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.functions import FunctionCallError, apply_expression
from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

name = "FUNCTION_TRANSFORM"
node_type = "FUNCTION_TRANSFORM"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _readable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset(
        {
            "wf",
            "stg",
            f"{domain_code.lower()}_stg",
            f"{domain_code.lower()}_mart",
            f"{domain_code.lower()}_raw",
        }
    )


def _writable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"wf", "stg", f"{domain_code.lower()}_stg"})


def _validate_table(label: str, table: str, allowed: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"{label} must match schema.table (got {table!r})")
    schema = table.split(".", 1)[0].lower()
    if schema not in allowed:
        raise NodeV2Error(f"{label} schema {schema!r} not allowed (allowed: {sorted(allowed)})")
    return table


def _default_output(pipeline_run_id: int, node_key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:32]
    return f"wf.tmp_run_{pipeline_run_id}_{safe}"


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    source_table = str(config.get("source_table") or "").strip()
    if not source_table:
        raise NodeV2Error("FUNCTION_TRANSFORM requires source_table")
    expressions = config.get("expressions") or {}
    if not isinstance(expressions, Mapping) or not expressions:
        raise NodeV2Error("FUNCTION_TRANSFORM requires non-empty `expressions` dict")
    pass_through = list(config.get("pass_through") or [])
    limit_rows = int(config.get("limit_rows") or 100_000)
    if limit_rows <= 0 or limit_rows > 10_000_000:
        raise NodeV2Error(f"limit_rows out of range: {limit_rows}")
    on_function_error = str(config.get("on_function_error") or "fail_node")
    if on_function_error not in ("skip_row", "fail_node"):
        raise NodeV2Error(f"invalid on_function_error: {on_function_error!r}")

    readable = _readable_schemas(context.domain_code)
    writable = _writable_schemas(context.domain_code)
    _validate_table("source_table", source_table, readable)
    output_table = str(
        config.get("output_table") or _default_output(context.pipeline_run_id, context.node_key)
    )
    _validate_table("output_table", output_table, writable)

    rows = (
        context.session.execute(
            text(f"SELECT * FROM {source_table} LIMIT :lim"), {"lim": limit_rows}
        )
        .mappings()
        .all()
    )

    target_cols = list(pass_through) + list(expressions.keys())
    # 중복 제거 — pass_through 와 expressions 동일 키가 있으면 expression 우선.
    seen: set[str] = set()
    target_cols_dedup: list[str] = []
    for c in target_cols:
        if c in seen:
            continue
        seen.add(c)
        target_cols_dedup.append(c)

    transformed: list[dict[str, Any]] = []
    skipped = 0
    for r in rows:
        try:
            out_row: dict[str, Any] = {col: r.get(col) for col in pass_through}
            for col, expr in expressions.items():
                out_row[col] = apply_expression(str(expr), row=dict(r))
            transformed.append(out_row)
        except FunctionCallError as exc:
            if on_function_error == "fail_node":
                return NodeV2Output(
                    status="failed",
                    error_message=str(exc),
                    payload={
                        "reason": "function_error",
                        "row_count_partial": len(transformed),
                    },
                )
            skipped += 1

    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    quoted = ", ".join(f'"{c}"' for c in target_cols_dedup)
    context.session.execute(
        text(
            f"CREATE TABLE {output_table} ("
            + ", ".join(f'"{c}" TEXT' for c in target_cols_dedup)
            + ")"
        )
    )
    if transformed:
        placeholders = ", ".join(f":{c}" for c in target_cols_dedup)
        insert_sql = text(
            f"INSERT INTO {output_table} ({quoted}) VALUES ({placeholders})"
        )
        for row_dict in transformed:
            params = {
                c: (
                    json.dumps(row_dict.get(c), ensure_ascii=False, default=str)
                    if isinstance(row_dict.get(c), dict | list)
                    else (
                        str(row_dict.get(c))
                        if row_dict.get(c) is not None
                        else None
                    )
                )
                for c in target_cols_dedup
            }
            context.session.execute(insert_sql, params)

    return NodeV2Output(
        status="success",
        row_count=len(transformed),
        payload={
            "output_table": output_table,
            "columns": target_cols_dedup,
            "row_count": len(transformed),
            "skipped_rows": skipped,
        },
    )


__all__ = ["name", "node_type", "run"]
