"""SQL_INLINE_TRANSFORM 노드 — sandbox-only inline SELECT (Q2 답변).

v1 의 `SQL_TRANSFORM` 의 generic 화. 차이:
  - Q2 답변 — INLINE 은 *sandbox-only*. mart/published 테이블에 *직접* 결과를 떨구지
    못함 (write target 은 wf.* / stg.* / <domain>_stg.* 만).
  - v2 sql_guard.NodeKind.SQL_INLINE_TRANSFORM 컨텍스트로 가드. 도메인별 schema 추가.

config:
  - `sql`: SELECT 또는 (CTE 포함) (필수). DELETE/DROP/TRUNCATE 등은 가드가 차단.
  - `output_table`: 결과 sandbox FQDN (선택, 기본 `wf.tmp_run_<pid>_<key>`).
  - `materialize`: bool (기본 True — `CREATE TABLE AS`. False 면 dry-count 만).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.guardrails.sql_guard import (
    NodeKind,
    SqlGuardError,
    SqlNodeContext,
    guard_sql,
)
from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

name = "SQL_INLINE_TRANSFORM"
node_type = "SQL_INLINE_TRANSFORM"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _default_output(pipeline_run_id: int, node_key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:32]
    return f"wf.tmp_run_{pipeline_run_id}_{safe}"


def _validate_output_table(output_table: str, *, allowed_schemas: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(output_table):
        raise NodeV2Error(f"output_table must match schema.table (got {output_table!r})")
    schema = output_table.split(".", 1)[0].lower()
    if schema not in allowed_schemas:
        raise NodeV2Error(
            f"output_table schema {schema!r} not allowed for INLINE "
            f"(allowed: {sorted(allowed_schemas)})"
        )
    return output_table


def _writable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"wf", "stg", f"{domain_code.lower()}_stg"})


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    sql = str(config.get("sql") or "").strip().rstrip(";")
    if not sql:
        raise NodeV2Error("SQL_INLINE_TRANSFORM requires `sql`")

    # 가드 — 도메인 인지 ALLOWED_SCHEMAS + write target = staging/temp only.
    extra: frozenset[str] = frozenset(
        {f"{context.domain_code}_mart", f"{context.domain_code}_stg", f"{context.domain_code}_raw"}
    )
    try:
        guard_sql(
            sql,
            ctx=SqlNodeContext(
                node_kind=NodeKind.SQL_INLINE_TRANSFORM,
                domain_code=context.domain_code,
                allowed_extra_schemas=extra,
            ),
        )
    except SqlGuardError as exc:
        return NodeV2Output(
            status="failed",
            error_message=f"sql guard violation: {exc}",
            payload={"reason": "sql_guard"},
        )

    materialize = bool(config.get("materialize", True))
    writable = _writable_schemas(context.domain_code)
    output_table = str(
        config.get("output_table") or _default_output(context.pipeline_run_id, context.node_key)
    )
    output_table = _validate_output_table(output_table, allowed_schemas=writable)

    if not materialize:
        scalar = context.session.execute(
            text(f"SELECT COUNT(*) FROM ({sql}) _q")
        ).scalar_one()
        count = int(scalar or 0)
        return NodeV2Output(
            status="success",
            row_count=count,
            payload={
                "output_table": None,
                "row_count": count,
                "materialize": False,
            },
        )

    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(text(f"CREATE TABLE {output_table} AS {sql}"))
    row_count = int(
        context.session.execute(text(f"SELECT COUNT(*) FROM {output_table}")).scalar_one() or 0
    )
    return NodeV2Output(
        status="success",
        row_count=row_count,
        payload={
            "output_table": output_table,
            "row_count": row_count,
            "materialize": True,
        },
    )


__all__ = ["name", "node_type", "run"]
