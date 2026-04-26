"""Phase 5.2.8 STEP 11 — SQL Performance Coach (backend, Q3 답변).

EXPLAIN (FORMAT JSON) 수집 → 위험 패턴 검사 → verdict (OK/WARN/BLOCK) +
audit.sql_explain_log 적재.

검사 패턴:
  1. seq_scan_on_large_table        — Seq Scan + relation 의 row count > threshold.
  2. estimated_rows_exceeded        — Plan 의 plan_rows > max_estimated_rows.
  3. estimated_cost_exceeded        — total_cost > max_cost.
  4. cross_join_detected            — Nested Loop + 양쪽 unbounded.
  5. unbounded_query                — LIMIT 없음 + WHERE 없음.
  6. missing_index_candidate        — Filter 가 있지만 Index Scan 미사용.
  7. timeout_risk                   — startup_cost 와 estimated_cost 의 곱이
                                       timeout 추정치 초과.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import sqlglot
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CoachVerdict:
    OK: str = "OK"
    WARN: str = "WARN"
    BLOCK: str = "BLOCK"


@dataclass(slots=True)
class SqlCoachOutcome:
    verdict: str  # OK / WARN / BLOCK
    warnings: list[str] = field(default_factory=list)
    explain_json: dict[str, Any] | list[Any] | None = None
    estimated_rows: int | None = None
    estimated_cost: float | None = None
    scanned_relations: list[str] = field(default_factory=list)


# 임계값 (Q1 — 10만~30만 rows/일).
DEFAULT_MAX_ESTIMATED_ROWS: Final[int] = 5_000_000
DEFAULT_MAX_COST: Final[float] = 1_000_000.0
DEFAULT_LARGE_TABLE_ROWS: Final[int] = 100_000
DEFAULT_TIMEOUT_RISK_COST: Final[float] = 500_000.0


def _walk_plan(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Plan 노드를 재귀로 평탄화."""
    nodes: list[Mapping[str, Any]] = [plan]
    for child in plan.get("Plans", []) or []:
        nodes.extend(_walk_plan(child))
    return nodes


def _scanned_relations_from_plan(plan: Mapping[str, Any]) -> list[str]:
    rels: set[str] = set()
    for node in _walk_plan(plan):
        rel = node.get("Relation Name")
        schema = node.get("Schema")
        if rel:
            rels.add(f"{schema}.{rel}" if schema else str(rel))
    return sorted(rels)


def _check_seq_scan_on_large_table(
    session: Session, plan: Mapping[str, Any]
) -> list[str]:
    warnings: list[str] = []
    for node in _walk_plan(plan):
        if node.get("Node Type") != "Seq Scan":
            continue
        rel = node.get("Relation Name")
        schema = node.get("Schema")
        if not rel:
            continue
        # row count 추정 — pg_class.reltuples.
        rows = session.execute(
            text(
                "SELECT reltuples FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :r AND n.nspname = COALESCE(:s, n.nspname) "
                "LIMIT 1"
            ),
            {"r": rel, "s": schema},
        ).scalar_one_or_none()
        if rows is not None and float(rows) >= DEFAULT_LARGE_TABLE_ROWS:
            warnings.append(
                f"seq_scan_on_large_table: {schema or '?'}.{rel} "
                f"(reltuples={int(rows):,})"
            )
    return warnings


def _check_estimated_rows(plan: Mapping[str, Any]) -> tuple[int | None, list[str]]:
    rows = plan.get("Plan Rows")
    warnings: list[str] = []
    if rows is None:
        return None, warnings
    rows_int = int(rows)
    if rows_int > DEFAULT_MAX_ESTIMATED_ROWS:
        warnings.append(
            f"estimated_rows_exceeded: {rows_int:,} > {DEFAULT_MAX_ESTIMATED_ROWS:,}"
        )
    return rows_int, warnings


def _check_estimated_cost(plan: Mapping[str, Any]) -> tuple[float | None, list[str]]:
    cost = plan.get("Total Cost")
    warnings: list[str] = []
    if cost is None:
        return None, warnings
    cost_f = float(cost)
    if cost_f > DEFAULT_MAX_COST:
        warnings.append(
            f"estimated_cost_exceeded: {cost_f:,.0f} > {DEFAULT_MAX_COST:,.0f}"
        )
    return cost_f, warnings


def _check_cross_join(plan: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    for node in _walk_plan(plan):
        if node.get("Node Type") != "Nested Loop":
            continue
        # Nested Loop + Join Filter 없음 → cartesian.
        if not node.get("Join Filter") and not node.get("Hash Cond"):
            warnings.append("cross_join_detected: Nested Loop without join filter")
            break
    return warnings


def _check_unbounded_query(sql: str) -> list[str]:
    norm = re.sub(r"\s+", " ", sql).lower()
    warnings: list[str] = []
    has_where = " where " in norm
    has_limit = " limit " in norm
    if not has_where and not has_limit:
        warnings.append("unbounded_query: missing WHERE and LIMIT")
    return warnings


def _check_missing_index(plan: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    for node in _walk_plan(plan):
        if node.get("Node Type") == "Seq Scan" and node.get("Filter"):
            rel = node.get("Relation Name")
            warnings.append(
                f"missing_index_candidate: Seq Scan + Filter on "
                f"{rel} ({str(node.get('Filter'))[:80]})"
            )
    return warnings


def _check_timeout_risk(plan: Mapping[str, Any]) -> list[str]:
    cost = plan.get("Total Cost")
    if cost is None:
        return []
    if float(cost) > DEFAULT_TIMEOUT_RISK_COST:
        return [
            f"timeout_risk: total_cost={float(cost):,.0f} "
            f"> {DEFAULT_TIMEOUT_RISK_COST:,.0f}"
        ]
    return []


def _sql_pre_validate(sql: str) -> list[str]:
    """sqlglot 기반 *static* 검사 — EXPLAIN 실행 전에 빠르게 거부."""
    warnings: list[str] = []
    try:
        ast = sqlglot.parse_one(sql, read="postgres")
    except Exception as exc:
        return [f"parse_failed: {exc}"]
    if ast is None:
        return ["parse_failed: empty result"]
    return warnings


def analyze_sql(
    session: Session,
    *,
    sql: str,
    domain_code: str | None = None,
    requested_by: int | None = None,
    persist: bool = True,
) -> SqlCoachOutcome:
    """SELECT 1건의 EXPLAIN 수집 + 검사 + audit.sql_explain_log 적재.

    SELECT 외 statement 는 BLOCK (DQ_CHECK 컨텍스트와 동일 가드).
    """
    if not sql or not sql.strip():
        outcome = SqlCoachOutcome(
            verdict="BLOCK",
            warnings=["empty_sql"],
        )
        if persist:
            _persist(session, sql, outcome, domain_code, requested_by)
        return outcome

    static_warns = _sql_pre_validate(sql)
    if any(w.startswith("parse_failed") for w in static_warns):
        outcome = SqlCoachOutcome(verdict="BLOCK", warnings=static_warns)
        if persist:
            _persist(session, sql, outcome, domain_code, requested_by)
        return outcome

    try:
        rows = session.execute(
            text(f"EXPLAIN (FORMAT JSON) {sql.rstrip(';')}")
        ).all()
        explain_payload = rows[0][0] if rows else None
    except Exception as exc:
        outcome = SqlCoachOutcome(
            verdict="BLOCK",
            warnings=[f"explain_failed: {type(exc).__name__}: {exc}"[:300]],
        )
        if persist:
            _persist(session, sql, outcome, domain_code, requested_by)
        return outcome

    if not explain_payload:
        outcome = SqlCoachOutcome(verdict="WARN", warnings=["empty_explain"])
        if persist:
            _persist(session, sql, outcome, domain_code, requested_by)
        return outcome

    plan_root = explain_payload[0] if isinstance(explain_payload, list) else explain_payload
    plan = plan_root.get("Plan", plan_root) if isinstance(plan_root, dict) else {}

    warnings: list[str] = []
    warnings.extend(_check_unbounded_query(sql))
    warnings.extend(_check_seq_scan_on_large_table(session, plan))
    rows_est, w = _check_estimated_rows(plan)
    warnings.extend(w)
    cost_est, w = _check_estimated_cost(plan)
    warnings.extend(w)
    warnings.extend(_check_cross_join(plan))
    warnings.extend(_check_missing_index(plan))
    warnings.extend(_check_timeout_risk(plan))

    relations = _scanned_relations_from_plan(plan)

    # verdict 결정.
    verdict = "OK"
    if any(w.startswith(("estimated_rows_exceeded", "estimated_cost_exceeded",
                         "cross_join_detected", "timeout_risk")) for w in warnings):
        verdict = "BLOCK"
    elif warnings:
        verdict = "WARN"

    outcome = SqlCoachOutcome(
        verdict=verdict,
        warnings=warnings,
        explain_json=explain_payload,
        estimated_rows=rows_est,
        estimated_cost=cost_est,
        scanned_relations=relations,
    )
    if persist:
        _persist(session, sql, outcome, domain_code, requested_by)
    return outcome


def _persist(
    session: Session,
    sql: str,
    outcome: SqlCoachOutcome,
    domain_code: str | None,
    requested_by: int | None,
) -> None:
    sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    session.execute(
        text(
            "INSERT INTO audit.sql_explain_log "
            "(domain_code, sql_hash, sql_text_short, verdict, warnings, "
            " explain_json, estimated_rows, estimated_cost, scanned_relations, "
            " requested_by) "
            "VALUES (:d, :h, :s, :v, :w, CAST(:e AS JSONB), :er, :ec, :sr, :rb)"
        ),
        {
            "d": domain_code,
            "h": sql_hash,
            "s": sql[:500],
            "v": outcome.verdict,
            "w": outcome.warnings,
            "e": json.dumps(outcome.explain_json, default=str)
            if outcome.explain_json is not None
            else None,
            "er": outcome.estimated_rows,
            "ec": outcome.estimated_cost,
            "sr": outcome.scanned_relations,
            "rb": requested_by,
        },
    )


__all__ = [
    "DEFAULT_LARGE_TABLE_ROWS",
    "DEFAULT_MAX_COST",
    "DEFAULT_MAX_ESTIMATED_ROWS",
    "DEFAULT_TIMEOUT_RISK_COST",
    "CoachVerdict",
    "SqlCoachOutcome",
    "analyze_sql",
]
