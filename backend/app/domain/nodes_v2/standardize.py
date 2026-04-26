"""STANDARDIZE v2 노드 — namespace-aware 표준화 (Phase 5.1 Wave 3).

Strategy 자동 결정:
  * agri / AGRI_FOOD     → embedding_3stage (v1 standardization 재사용)
  * pos / PAYMENT_METHOD → alias_only (std_alias)
  * 기타                  → noop (raw 그대로)

config:
  - `namespace`: str (필수) — 표준코드 namespace 이름
  - `target_table`: str (필수) — 표준화 대상 sandbox FQDN
  - `raw_column`: str (필수) — raw 값이 있는 컬럼
  - `std_column`: str (필수) — 결과 std_code 를 채울 컬럼 (NULL 만 채움 — 멱등)
  - `where_clause`: str (선택) — 추가 필터
  - `limit_rows`: int (default 100_000)

가드:
  - target_table schema 는 wf / stg / <domain>_stg / <domain>_mart 만.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output
from app.domain.standardization_registry import (
    resolve_namespace,
    standardize_column,
)

name = "STANDARDIZE"
node_type = "STANDARDIZE"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_SAFE_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _allowed_schemas(domain_code: str) -> frozenset[str]:
    return frozenset(
        {
            "wf",
            "stg",
            f"{domain_code.lower()}_stg",
            f"{domain_code.lower()}_mart",
        }
    )


def _validate_table(table: str, allowed: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"target_table must match schema.table (got {table!r})")
    schema = table.split(".", 1)[0].lower()
    if schema not in allowed:
        raise NodeV2Error(
            f"target_table schema {schema!r} not allowed (allowed: {sorted(allowed)})"
        )
    return table


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    namespace = str(config.get("namespace") or "").strip()
    if not namespace:
        raise NodeV2Error("STANDARDIZE requires `namespace`")
    target_table = str(config.get("target_table") or "").strip()
    raw_column = str(config.get("raw_column") or "").strip()
    std_column = str(config.get("std_column") or "").strip()
    if not target_table or not raw_column or not std_column:
        raise NodeV2Error(
            "STANDARDIZE requires target_table, raw_column, std_column"
        )
    for col in (raw_column, std_column):
        if not _SAFE_IDENT_RE.match(col):
            raise NodeV2Error(f"unsafe column name: {col!r}")

    allowed = _allowed_schemas(context.domain_code)
    _validate_table(target_table, allowed)

    spec = resolve_namespace(
        context.session,
        domain_code=context.domain_code,
        namespace=namespace,
    )
    if spec is None:
        return NodeV2Output(
            status="failed",
            error_message=(
                f"namespace ({context.domain_code}, {namespace}) not registered"
            ),
            payload={"reason": "namespace_not_found"},
        )

    where_clause = str(config.get("where_clause") or "TRUE")
    limit_rows = int(config.get("limit_rows") or 100_000)
    if limit_rows <= 0 or limit_rows > 10_000_000:
        raise NodeV2Error(f"limit_rows out of range: {limit_rows}")

    counts = standardize_column(
        context.session,
        domain_code=context.domain_code,
        namespace=namespace,
        target_table=target_table,
        raw_column=raw_column,
        std_column=std_column,
        where_clause=where_clause,
        limit_rows=limit_rows,
    )
    matched = (
        counts.get("matched_via_alias", 0)
        + counts.get("matched_via_std_code", 0)
        + counts.get("matched", 0)
    )
    return NodeV2Output(
        status="success",
        row_count=matched,
        payload={
            "namespace": namespace,
            "strategy": spec.strategy.value,
            "target_table": target_table,
            "counts": counts,
        },
    )


__all__ = ["name", "node_type", "run"]
