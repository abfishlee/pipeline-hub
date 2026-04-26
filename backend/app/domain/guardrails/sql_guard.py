"""SQL 위험 구문 차단 + 도메인 인지 ALLOWED_SCHEMAS + 노드 타입 별 read/write 제한.

5.2.0 의 핵심 가드레일. v1 의 `app/integrations/sqlglot_validator.py` 가 SELECT
정책을 검증하는 반면, 본 모듈은 *모든 statement type* (INSERT/UPDATE/CREATE TABLE AS
포함) 을 노드 컨텍스트별로 다르게 허용.

차단 키워드 (Q3 답변):
  DROP / DELETE / TRUNCATE / ALTER / CREATE EXTENSION /
  GRANT / REVOKE / COPY PROGRAM

노드 타입 컨텍스트 (Q3 답변):
  - SQL_INLINE_TRANSFORM / SQL_ASSET_TRANSFORM:
      read-only OR temp/staging write only (mart 직접 INSERT 금지)
  - LOAD_TARGET:
      승인된 mart target 에 대한 INSERT/UPDATE/MERGE 만 (load_policy 가 별도 검증)
  - DQ_CHECK:
      read-only

도메인 인지 ALLOWED_SCHEMAS:
  - v1 (legacy): mart, stg, wf, dq, ctl, raw, audit
  - v2 generic: 위 + `<domain>_mart`, `<domain>_stg`, `<domain>_raw` 등
  - 호출자가 SqlNodeContext.allowed_extra_schemas 로 도메인별 schema 추가 지정.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

import sqlglot
from sqlglot import exp

from app.integrations.sqlglot_validator import (
    DENIED_FUNCTION_NAMES,
    DENIED_FUNCTION_PREFIXES,
    SqlValidationError,
)


class NodeKind(StrEnum):
    SQL_INLINE_TRANSFORM = "SQL_INLINE_TRANSFORM"
    SQL_ASSET_TRANSFORM = "SQL_ASSET_TRANSFORM"
    LOAD_TARGET = "LOAD_TARGET"
    DQ_CHECK = "DQ_CHECK"
    # v1 SQL Studio 도 본 가드를 통과해야 함 — 강화 정책.
    V1_SQL_STUDIO = "V1_SQL_STUDIO"


# v1 legacy schema 셋 — 항상 허용.
V1_LEGACY_SCHEMAS: frozenset[str] = frozenset(
    {"mart", "stg", "wf", "dq", "ctl", "raw", "audit"}
)

# 차단 키워드 (Phase 5.2.0 § Q3 답변).
DENIED_KEYWORDS_RE_STRICT = re.compile(
    r"\b("
    r"DROP\b|"
    r"DELETE\s+FROM|"
    r"TRUNCATE\b|"
    r"ALTER\b|"
    r"CREATE\s+EXTENSION|"
    r"DROP\s+EXTENSION|"
    r"GRANT\b|"
    r"REVOKE\b|"
    r"COPY\s+\([^)]*\)\s+TO\s+PROGRAM|"
    r"COPY\b[^;]*\bPROGRAM\b|"
    r"VACUUM\b|"
    r"CLUSTER\b|"
    r"REINDEX\b|"
    r"LISTEN\b|"
    r"NOTIFY\b|"
    r"UNLISTEN\b|"
    r"DO\s+\$\$"
    r")",
    re.IGNORECASE,
)


class SqlGuardError(SqlValidationError):
    """노드 컨텍스트가 허용하지 않는 SQL 구문 — 422."""


@dataclass(slots=True, frozen=True)
class SqlNodeContext:
    """가드 검증 시점의 노드 컨텍스트."""

    node_kind: NodeKind
    domain_code: str | None = None
    # 현재 도메인의 schema 들 (예: agri 면 빈 set, pos 면 {pos_mart, pos_stg}).
    allowed_extra_schemas: frozenset[str] = field(default_factory=frozenset)
    # LOAD_TARGET 에서 적재 가능한 target 화이트리스트 (load_policy registry 가 결정).
    allowed_load_targets: frozenset[str] = field(default_factory=frozenset)


def _allowed_schemas(ctx: SqlNodeContext) -> frozenset[str]:
    return frozenset(V1_LEGACY_SCHEMAS | ctx.allowed_extra_schemas)


_SELECTABLE_KEYS = ("select", "union", "with", "intersect", "except")
_TEMP_OR_STAGING_PREFIXES = ("stg", "stg_", "tmp_", "temp_", "wf")


def _is_temp_or_staging_target(qualified: str, *, ctx: SqlNodeContext) -> bool:
    """qualified = 'schema.table'. *temp/staging* 으로 간주되는 target 인지 판정."""
    schema = qualified.split(".", 1)[0].lower() if "." in qualified else ""
    if schema == "stg":
        return True
    if schema == "wf" and any(
        qualified.lower().split(".", 1)[1].startswith(p) for p in ("tmp_", "temp_")
    ):
        return True
    # 도메인별 staging schema 도 허용.
    domain_stg = f"{ctx.domain_code}_stg" if ctx.domain_code else None
    return bool(domain_stg and schema == domain_stg.lower())


def _table_target_is_allowed(qualified: str, ctx: SqlNodeContext) -> bool:
    if ctx.node_kind == NodeKind.LOAD_TARGET:
        return qualified.lower() in {t.lower() for t in ctx.allowed_load_targets}
    if ctx.node_kind in (NodeKind.SQL_INLINE_TRANSFORM, NodeKind.SQL_ASSET_TRANSFORM):
        return _is_temp_or_staging_target(qualified, ctx=ctx)
    return False


def _check_keywords_strict(sql: str) -> None:
    match = DENIED_KEYWORDS_RE_STRICT.search(sql)
    if match:
        raise SqlGuardError(f"denied keyword: {match.group(0).strip()}")


def _check_function_name(name: str) -> None:
    name = name.lower()
    if not name:
        return
    if name in DENIED_FUNCTION_NAMES:
        raise SqlGuardError(f"function '{name}' is denied")
    for prefix in DENIED_FUNCTION_PREFIXES:
        if name.startswith(prefix):
            raise SqlGuardError(f"function '{name}' (prefix '{prefix}') is denied")


def _check_functions(ast: exp.Expression) -> None:
    for func in ast.find_all(exp.Func):
        _check_function_name(getattr(func, "name", "") or "")
    for anon in ast.find_all(exp.Anonymous):
        _check_function_name(anon.name or "")


def _check_schemas(
    ast: exp.Expression, *, ctx: SqlNodeContext, cte_names: set[str]
) -> None:
    allowed = _allowed_schemas(ctx)
    for t in ast.find_all(exp.Table):
        schema_obj = t.args.get("db")
        schema = schema_obj.name if schema_obj is not None else None
        if not schema:
            if t.name and t.name.lower() in cte_names:
                continue
            raise SqlGuardError(
                f"unqualified table reference '{t.name}' — must use schema.table "
                f"(allowed: {sorted(allowed)})"
            )
        if schema.lower() not in {s.lower() for s in allowed}:
            raise SqlGuardError(
                f"schema '{schema}' is not allowed for {ctx.node_kind} "
                f"(allowed: {sorted(allowed)})"
            )


def _cte_names(ast: exp.Expression) -> set[str]:
    out: set[str] = set()
    for cte in ast.find_all(exp.CTE):
        alias = cte.alias_or_name
        if alias:
            out.add(alias.lower())
    return out


def _statement_kind(ast: exp.Expression) -> str:
    """반환: 'SELECT' | 'INSERT' | 'UPDATE' | 'MERGE' | 'CREATE_TABLE_AS' | 'DELETE' | 'OTHER'."""
    key = ast.key.lower()
    if key in _SELECTABLE_KEYS:
        return "SELECT"
    if key == "insert":
        return "INSERT"
    if key == "update":
        return "UPDATE"
    if key == "merge":
        return "MERGE"
    if key == "delete":
        return "DELETE"
    if key == "create" and isinstance(ast, exp.Create) and ast.kind and ast.kind.upper() == "TABLE":
        # CREATE TABLE ... AS SELECT
        return "CREATE_TABLE_AS"
    return key.upper()


def _enforce_node_policy(stmt_kind: str, ast: exp.Expression, ctx: SqlNodeContext) -> None:
    """노드 종류별 허용 statement / write target 검증."""
    if ctx.node_kind == NodeKind.DQ_CHECK:
        if stmt_kind != "SELECT":
            raise SqlGuardError(
                f"DQ_CHECK only allows SELECT (got {stmt_kind})"
            )
        return

    if ctx.node_kind == NodeKind.V1_SQL_STUDIO:
        # v1 SQL Studio 는 historical 으로 SELECT only.
        if stmt_kind != "SELECT":
            raise SqlGuardError(
                f"V1_SQL_STUDIO only allows SELECT (got {stmt_kind})"
            )
        return

    if ctx.node_kind in (NodeKind.SQL_INLINE_TRANSFORM, NodeKind.SQL_ASSET_TRANSFORM):
        if stmt_kind == "SELECT":
            return
        if stmt_kind == "DELETE":
            raise SqlGuardError(
                f"{ctx.node_kind} cannot DELETE — use LOAD_TARGET with rollback policy"
            )
        # *write target 만* staging/temp 강제. FROM 의 SELECT source (mart 등) 는 허용.
        write_target = _extract_write_target(ast)
        if write_target and not _is_temp_or_staging_target(write_target, ctx=ctx):
            raise SqlGuardError(
                f"{ctx.node_kind} write target must be staging/temp "
                f"(got {write_target})"
            )
        return

    if ctx.node_kind == NodeKind.LOAD_TARGET:
        if stmt_kind not in ("INSERT", "UPDATE", "MERGE"):
            raise SqlGuardError(
                f"LOAD_TARGET only allows INSERT/UPDATE/MERGE (got {stmt_kind})"
            )
        write_target = _extract_write_target(ast)
        if write_target and not _table_target_is_allowed(write_target, ctx):
            raise SqlGuardError(
                f"LOAD_TARGET cannot write to {write_target} "
                f"(allowed: {sorted(ctx.allowed_load_targets)})"
            )


def _extract_write_target(ast: exp.Expression) -> str | None:
    """INSERT/UPDATE/MERGE/CREATE_TABLE_AS 의 *대상 테이블 1개* 를 'schema.table' 로 반환."""
    target: exp.Expression | None = None
    if isinstance(ast, exp.Insert | exp.Update | exp.Merge | exp.Create):
        target = ast.this
    if isinstance(target, exp.Schema):
        target = target.this
    if not isinstance(target, exp.Table):
        return None
    schema_obj = target.args.get("db")
    schema = schema_obj.name if schema_obj is not None else ""
    return f"{schema}.{target.name}".lstrip(".")


def guard_sql(sql: str, *, ctx: SqlNodeContext) -> exp.Expression:
    """노드 컨텍스트 별 SQL 가드. 위반 시 `SqlGuardError`.

    1. 위험 키워드 (DROP/TRUNCATE/...) 정규식 차단
    2. parse → statement_kind 판정
    3. 노드 정책 적용 (SELECT only / temp+stg write only / mart upsert only)
    4. 함수 블랙리스트
    5. 도메인 인지 ALLOWED_SCHEMAS 검증
    """
    if not sql or not sql.strip():
        raise SqlGuardError("empty SQL")
    if ";" in sql.strip().rstrip(";"):
        raise SqlGuardError("multi-statement SQL is not allowed")

    _check_keywords_strict(sql)

    try:
        ast = sqlglot.parse_one(sql, read="postgres")
    except Exception as exc:
        raise SqlGuardError(f"parse failed: {exc}") from exc
    if ast is None:
        raise SqlGuardError("empty parse result")

    stmt_kind = _statement_kind(ast)
    _enforce_node_policy(stmt_kind, ast, ctx)
    _check_functions(ast)

    cte_names = _cte_names(ast)
    _check_schemas(ast, ctx=ctx, cte_names=cte_names)
    return ast


__all__ = [
    "DENIED_KEYWORDS_RE_STRICT",
    "V1_LEGACY_SCHEMAS",
    "NodeKind",
    "SqlGuardError",
    "SqlNodeContext",
    "guard_sql",
]
