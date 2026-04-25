"""sqlglot 기반 SQL 정적 분석 (Phase 3.2.2 SQL_TRANSFORM, Phase 3.2.4 SQL Studio).

검증 정책:
  - **statement type**: SELECT 만 허용 (사용자가 짠 SQL 은 결과를 보는 용도).
    INSERT/UPDATE/DELETE/DDL 은 거부 — sandbox 적재는 시스템이 `CREATE TABLE AS`
    로 감싸 별도 호출.
  - **참조 schema 화이트리스트**: `mart`, `stg`, `wf` 만 허용. `pg_catalog`,
    `information_schema`, 사용자 임의 schema 차단.
  - **함수 블랙리스트**: `pg_read_*`, `lo_*`, `dblink*`, `COPY`, `pg_sleep`,
    `current_setting`, `set_config`, `pg_*` 일반.
  - **AST 깊이 제한**: 100 (DoS 방지).

`validate(sql)` → (ast, set[참조 테이블]) 또는 `SqlValidationError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import sqlglot
from sqlglot import exp

ALLOWED_SCHEMAS: frozenset[str] = frozenset({"mart", "stg", "wf"})
DENIED_FUNCTION_PREFIXES: tuple[str, ...] = (
    "pg_read_",
    "pg_ls_",
    "pg_stat_file",
    "pg_sleep",
    "lo_",
    "dblink",
    "current_setting",
    "set_config",
)
DENIED_FUNCTION_NAMES: frozenset[str] = frozenset(
    name.lower()
    for name in (
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "txid_status",
        "pg_advisory_lock",
        "pg_advisory_unlock",
    )
)
DENIED_KEYWORDS_RE = re.compile(
    r"\b(COPY|VACUUM|ANALYZE|CLUSTER|REINDEX|TRUNCATE|GRANT|REVOKE|"
    r"ALTER\s+SYSTEM|CREATE\s+EXTENSION|DROP\s+EXTENSION|DO\s+\$\$|"
    r"LISTEN|NOTIFY|UNLISTEN)\b",
    re.IGNORECASE,
)
MAX_AST_DEPTH = 100


class SqlValidationError(Exception):
    """SQL 정책 위반 — sandbox 실행 차단."""


def _ast_depth(node: exp.Expression, current: int = 0) -> int:
    if current >= MAX_AST_DEPTH:
        return current
    deepest = current
    for child in node.iter_expressions():
        deepest = max(deepest, _ast_depth(child, current + 1))
    return deepest


def _table_refs(ast: exp.Expression) -> list[exp.Table]:
    return list(ast.find_all(exp.Table))


def _check_schemas(tables: Iterable[exp.Table]) -> None:
    for t in tables:
        schema_obj = t.args.get("db")
        schema = schema_obj.name if schema_obj is not None else None
        if not schema:
            raise SqlValidationError(
                f"unqualified table reference '{t.name}' — must use schema.table "
                f"(allowed: {sorted(ALLOWED_SCHEMAS)})"
            )
        if schema.lower() not in ALLOWED_SCHEMAS:
            raise SqlValidationError(
                f"schema '{schema}' is not allowed " f"(allowed: {sorted(ALLOWED_SCHEMAS)})"
            )


def _check_function_name(name: str) -> None:
    name = name.lower()
    if not name:
        return
    if name in DENIED_FUNCTION_NAMES:
        raise SqlValidationError(f"function '{name}' is denied")
    for prefix in DENIED_FUNCTION_PREFIXES:
        if name.startswith(prefix):
            raise SqlValidationError(f"function '{name}' (prefix '{prefix}') is denied")


def _check_functions(ast: exp.Expression) -> None:
    for func in ast.find_all(exp.Func):
        _check_function_name(getattr(func, "name", "") or "")
    # Anonymous (custom) function 도 cover.
    for anon in ast.find_all(exp.Anonymous):
        _check_function_name(anon.name or "")


def _check_keywords(sql: str) -> None:
    match = DENIED_KEYWORDS_RE.search(sql)
    if match:
        raise SqlValidationError(f"denied keyword: {match.group(0)}")


def validate(sql: str) -> tuple[exp.Expression, set[str]]:
    """SELECT 만 허용. 위반 시 `SqlValidationError`."""
    if not sql or not sql.strip():
        raise SqlValidationError("empty SQL")
    if ";" in sql.strip().rstrip(";"):
        raise SqlValidationError("multi-statement SQL is not allowed")

    _check_keywords(sql)

    try:
        ast = sqlglot.parse_one(sql, read="postgres")
    except Exception as exc:
        raise SqlValidationError(f"parse failed: {exc}") from exc
    if ast is None:
        raise SqlValidationError("empty parse result")

    # SELECT-only 정책 — sqlglot 의 expression key 로 판정 (CTE 는 'with', UNION 는 'union').
    if ast.key not in ("select", "union", "with", "intersect", "except"):
        raise SqlValidationError(f"only SELECT statements are allowed (got {ast.key.upper()})")

    if _ast_depth(ast) >= MAX_AST_DEPTH:
        raise SqlValidationError(f"AST depth exceeds {MAX_AST_DEPTH} — too complex")

    tables = _table_refs(ast)
    if not tables:
        raise SqlValidationError("no FROM clause / table reference")
    _check_schemas(tables)
    _check_functions(ast)

    referenced: set[str] = set()
    for t in tables:
        db_obj = t.args.get("db")
        schema = (db_obj.name if db_obj is not None else "") or ""
        referenced.add(f"{schema}.{t.name}".lstrip("."))
    return ast, referenced


__all__ = ["ALLOWED_SCHEMAS", "SqlValidationError", "validate"]
