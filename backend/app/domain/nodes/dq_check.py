"""DQ_CHECK 노드 — 자산 검사. 위반 시 `dq.quality_result` INSERT + NodeOutput failed.

config:
  - `input_table`: schema.table (필수)
  - `assertions`: list[Assertion] (1+개)
    Assertion shape:
      { "kind": "row_count_min", "min": 1 }
      { "kind": "null_pct_max", "column": "name", "max_pct": 5.0 }
      { "kind": "unique_columns", "columns": ["sku"] }
      { "kind": "custom_sql", "sql": "SELECT COUNT(*)::int FROM ... WHERE ...", "expect": 0 }
  - `severity`: 'WARN' | 'ERROR' | 'BLOCK' (기본 'ERROR')

ERROR/BLOCK 위반 시 NodeOutput status='failed'. WARN 은 통과(success) 하지만 DB 에는
기록.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes import NodeContext, NodeError, NodeOutput
from app.integrations.sqlglot_validator import (
    ALLOWED_SCHEMAS,
    SqlValidationError,
    validate,
)
from app.models.dq import QualityResult

name = "DQ_CHECK"

_TABLE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]{0,62})\.([a-zA-Z_][a-zA-Z0-9_]{0,62})$")
_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _quote_table(table: str) -> str:
    m = _TABLE_RE.match(table)
    if m is None:
        raise NodeError(f"invalid input_table: {table!r}")
    if m.group(1).lower() not in ALLOWED_SCHEMAS:
        raise NodeError(f"schema '{m.group(1)}' not allowed")
    return f'"{m.group(1)}"."{m.group(2)}"'


def _quote_col(c: str) -> str:
    if not _COLUMN_RE.match(c):
        raise NodeError(f"invalid column name: {c!r}")
    return f'"{c}"'


def _check_row_count_min(
    session: Any, qualified: str, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any]]:
    minimum = int(params.get("min") or 0)
    actual = int(session.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar_one() or 0)
    return actual >= minimum, {"min": minimum, "actual": actual}


def _check_null_pct_max(
    session: Any, qualified: str, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any]]:
    column = _quote_col(str(params.get("column") or ""))
    max_pct = float(params.get("max_pct") or 0)
    row = session.execute(
        text(
            f"SELECT COUNT(*) AS n, "
            f"  COUNT(*) FILTER (WHERE {column} IS NULL) AS nulls "
            f"FROM {qualified}"
        )
    ).first()
    if row is None:
        return True, {"max_pct": max_pct, "actual_pct": 0.0, "rows": 0}
    n = int(row.n or 0)
    nulls = int(row.nulls or 0)
    actual_pct = (nulls / n * 100.0) if n else 0.0
    return actual_pct <= max_pct, {
        "max_pct": max_pct,
        "actual_pct": round(actual_pct, 4),
        "column": str(params.get("column")),
        "rows": n,
        "nulls": nulls,
    }


def _check_unique_columns(
    session: Any, qualified: str, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any]]:
    columns = [str(c) for c in (params.get("columns") or [])]
    if not columns:
        raise NodeError("unique_columns requires `columns`")
    cols_quoted = ", ".join(_quote_col(c) for c in columns)
    dup = session.execute(
        text(
            f"SELECT COUNT(*) FROM ("
            f"  SELECT {cols_quoted} FROM {qualified} GROUP BY {cols_quoted} HAVING COUNT(*) > 1"
            f") _d"
        )
    ).scalar_one()
    dup_count = int(dup or 0)
    return dup_count == 0, {"columns": columns, "duplicate_groups": dup_count}


def _check_custom_sql(session: Any, params: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    sql = str(params.get("sql") or "").strip().rstrip(";")
    expect = params.get("expect")
    try:
        validate(sql)
    except SqlValidationError as exc:
        raise NodeError(f"custom_sql validation failed: {exc}") from exc
    actual = session.execute(text(sql)).scalar()
    return (actual == expect), {"sql": sql, "expect": expect, "actual": actual}


def run(context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
    input_table = str(config.get("input_table") or "").strip()
    qualified = _quote_table(input_table)
    assertions = list(config.get("assertions") or [])
    if not assertions:
        raise NodeError("DQ_CHECK requires assertions")
    severity = str(config.get("severity") or "ERROR").upper()
    if severity not in ("INFO", "WARN", "ERROR", "BLOCK"):
        raise NodeError(f"invalid severity: {severity!r}")

    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for idx, raw in enumerate(assertions):
        if not isinstance(raw, Mapping):
            raise NodeError(f"assertion[{idx}] must be a dict")
        kind = str(raw.get("kind") or "").lower()
        if kind == "row_count_min":
            passed, details = _check_row_count_min(context.session, qualified, raw)
        elif kind == "null_pct_max":
            passed, details = _check_null_pct_max(context.session, qualified, raw)
        elif kind == "unique_columns":
            passed, details = _check_unique_columns(context.session, qualified, raw)
        elif kind == "custom_sql":
            passed, details = _check_custom_sql(context.session, raw)
        else:
            raise NodeError(f"unknown assertion kind: {kind!r}")

        context.session.add(
            QualityResult(
                pipeline_run_id=context.pipeline_run_id,
                node_run_id=context.node_run_id,
                target_table=input_table,
                check_kind=kind,
                passed=passed,
                severity=severity,
                details_json=details,
            )
        )
        results.append({"kind": kind, "passed": passed, "details": details})
        if not passed:
            failures.append({"kind": kind, "details": details})

    context.session.flush()

    overall_failed = bool(failures) and severity in ("ERROR", "BLOCK")
    return NodeOutput(
        status="failed" if overall_failed else "success",
        row_count=len(results),
        payload={
            "input_table": input_table,
            "results": results,
            "severity": severity,
            "failed_count": len(failures),
        },
        error_message=(
            f"{len(failures)} of {len(results)} assertions failed (severity={severity})"
            if overall_failed
            else None
        ),
    )


__all__ = ["name", "run"]
