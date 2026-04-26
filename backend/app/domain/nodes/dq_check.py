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

ERROR/BLOCK 위반 시 NodeOutput status='failed' + payload['dq_hold']=True 로
pipeline_runtime 에 ON_HOLD 신호 전달. WARN 은 통과(success) 하지만 DB 에는 기록.

Phase 4.2.2 추가:
  - 실패 시 최대 10 행 샘플을 `dq.quality_result.sample_json` 으로 저장 (운영자가
    승인/반려 모달에서 검토).
  - `quality_result.status` = PASS/WARN/FAIL.
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

_SAMPLE_LIMIT = 10


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


def _rows_to_jsonable(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            mapping = dict(r._mapping)
        except AttributeError:
            mapping = dict(r) if isinstance(r, Mapping) else {"value": r}
        norm: dict[str, Any] = {}
        for k, v in mapping.items():
            if v is None or isinstance(v, str | int | float | bool):
                norm[k] = v
            else:
                norm[k] = str(v)
        out.append(norm)
    return out


def _check_row_count_min(
    session: Any, qualified: str, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    minimum = int(params.get("min") or 0)
    actual = int(session.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar_one() or 0)
    return actual >= minimum, {"min": minimum, "actual": actual}, []


def _check_null_pct_max(
    session: Any, qualified: str, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    column_name = str(params.get("column") or "")
    column = _quote_col(column_name)
    max_pct = float(params.get("max_pct") or 0)
    row = session.execute(
        text(
            f"SELECT COUNT(*) AS n, "
            f"  COUNT(*) FILTER (WHERE {column} IS NULL) AS nulls "
            f"FROM {qualified}"
        )
    ).first()
    if row is None:
        return True, {"max_pct": max_pct, "actual_pct": 0.0, "rows": 0}, []
    n = int(row.n or 0)
    nulls = int(row.nulls or 0)
    actual_pct = (nulls / n * 100.0) if n else 0.0
    passed = actual_pct <= max_pct
    details: dict[str, Any] = {
        "max_pct": max_pct,
        "actual_pct": round(actual_pct, 4),
        "column": column_name,
        "rows": n,
        "nulls": nulls,
    }
    samples: list[dict[str, Any]] = []
    if not passed:
        sample_rows = session.execute(
            text(f"SELECT * FROM {qualified} WHERE {column} IS NULL LIMIT :limit"),
            {"limit": _SAMPLE_LIMIT},
        ).fetchall()
        samples = _rows_to_jsonable(sample_rows)
    return passed, details, samples


def _check_unique_columns(
    session: Any, qualified: str, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
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
    passed = dup_count == 0
    samples: list[dict[str, Any]] = []
    if not passed:
        sample_rows = session.execute(
            text(
                f"SELECT {cols_quoted}, COUNT(*) AS dup_count FROM {qualified} "
                f"GROUP BY {cols_quoted} HAVING COUNT(*) > 1 LIMIT :limit"
            ),
            {"limit": _SAMPLE_LIMIT},
        ).fetchall()
        samples = _rows_to_jsonable(sample_rows)
    return passed, {"columns": columns, "duplicate_groups": dup_count}, samples


def _check_custom_sql(
    session: Any, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    sql = str(params.get("sql") or "").strip().rstrip(";")
    expect = params.get("expect")
    try:
        validate(sql)
    except SqlValidationError as exc:
        raise NodeError(f"custom_sql validation failed: {exc}") from exc
    actual = session.execute(text(sql)).scalar()
    return (actual == expect), {"sql": sql, "expect": expect, "actual": actual}, []


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
    quality_result_ids: list[int] = []

    for idx, raw in enumerate(assertions):
        if not isinstance(raw, Mapping):
            raise NodeError(f"assertion[{idx}] must be a dict")
        kind = str(raw.get("kind") or "").lower()
        if kind == "row_count_min":
            passed, details, samples = _check_row_count_min(context.session, qualified, raw)
        elif kind == "null_pct_max":
            passed, details, samples = _check_null_pct_max(context.session, qualified, raw)
        elif kind == "unique_columns":
            passed, details, samples = _check_unique_columns(context.session, qualified, raw)
        elif kind == "custom_sql":
            passed, details, samples = _check_custom_sql(context.session, raw)
        else:
            raise NodeError(f"unknown assertion kind: {kind!r}")

        # Phase 4.2.2 — status (PASS/WARN/FAIL) 결정.
        if passed:
            status_code = "PASS"
        elif severity == "WARN":
            status_code = "WARN"
        else:
            status_code = "FAIL"

        qr = QualityResult(
            pipeline_run_id=context.pipeline_run_id,
            node_run_id=context.node_run_id,
            target_table=input_table,
            check_kind=kind,
            passed=passed,
            severity=severity,
            status=status_code,
            details_json=details,
            sample_json=samples,
        )
        context.session.add(qr)
        context.session.flush()
        quality_result_ids.append(qr.quality_result_id)
        results.append({"kind": kind, "passed": passed, "details": details})
        if not passed:
            failures.append({"kind": kind, "details": details})

    overall_failed = bool(failures) and severity in ("ERROR", "BLOCK")
    payload: dict[str, Any] = {
        "input_table": input_table,
        "results": results,
        "severity": severity,
        "failed_count": len(failures),
        "quality_result_ids": quality_result_ids,
    }
    if overall_failed:
        # pipeline_runtime 가 이 플래그를 보고 ON_HOLD 전이 + cascade SKIPPED 차단.
        payload["dq_hold"] = True
    return NodeOutput(
        status="failed" if overall_failed else "success",
        row_count=len(results),
        payload=payload,
        error_message=(
            f"{len(failures)} of {len(results)} assertions failed (severity={severity})"
            if overall_failed
            else None
        ),
    )


__all__ = ["name", "run"]
