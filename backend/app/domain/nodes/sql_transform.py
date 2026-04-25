"""SQL_TRANSFORM 노드 — sqlglot 검증 통과한 SELECT 를 sandbox 테이블로 적재.

config:
  - `sql`: SELECT 문 (필수). `mart`/`stg`/`wf` schema 만 참조 가능.
  - `output_table`: 결과 테이블 이름 (선택, 기본
    `wf.tmp_run_<pipeline_run_id>_<node_key>`).
  - `materialize`: bool (기본 True — `CREATE TABLE AS`. False 면 검증만 하고
    행 수만 보고).

성공 시 NodeOutput.payload 에 sandbox table FQDN + row_count.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes import NodeContext, NodeError, NodeOutput
from app.integrations.sqlglot_validator import SqlValidationError, validate

name = "SQL_TRANSFORM"

# Sandbox 테이블 이름 안전 검증 — 영숫자/언더스코어 + schema 'wf' 강제.
_OUTPUT_TABLE_RE = re.compile(r"^wf\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _default_output_table(pipeline_run_id: int, node_key: str) -> str:
    safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:32]
    return f"wf.tmp_run_{pipeline_run_id}_{safe_key}"


def _validate_output_table(output_table: str) -> str:
    if not _OUTPUT_TABLE_RE.match(output_table):
        raise NodeError(
            f"output_table must match {_OUTPUT_TABLE_RE.pattern} (got {output_table!r})"
        )
    return output_table


def run(context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
    sql = str(config.get("sql") or "").strip().rstrip(";")
    if not sql:
        raise NodeError("SQL_TRANSFORM requires `sql`")

    try:
        validate(sql)
    except SqlValidationError as exc:
        return NodeOutput(
            status="failed",
            error_message=f"sql validation failed: {exc}",
            payload={"reason": "sql_policy_violation"},
        )

    materialize = bool(config.get("materialize", True))
    output_table = str(
        config.get("output_table")
        or _default_output_table(context.pipeline_run_id, context.node_key)
    )
    output_table = _validate_output_table(output_table)

    if not materialize:
        # 검증 + 행 수만 — 실 데이터 없는 dry-run.
        result = context.session.execute(text(f"SELECT COUNT(*) FROM ({sql}) _q"))
        count = int(result.scalar_one() or 0)
        return NodeOutput(
            status="success",
            row_count=count,
            payload={"output_table": None, "row_count": count, "materialize": False},
        )

    # CREATE 전에 기존 sandbox 테이블 정리.
    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(text(f"CREATE TABLE {output_table} AS {sql}"))

    count_result = context.session.execute(text(f"SELECT COUNT(*) FROM {output_table}"))
    row_count = int(count_result.scalar_one() or 0)

    return NodeOutput(
        status="success",
        row_count=row_count,
        payload={
            "output_table": output_table,
            "row_count": row_count,
            "materialize": True,
        },
    )


__all__ = ["name", "run"]
