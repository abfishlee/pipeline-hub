"""MAP_FIELDS 노드 — field_mapping registry 기반 source col → target col 변환.

config:
  - `contract_id`: int (필수) — 어떤 contract 의 mapping 을 적용할지.
  - `source_table`: str (필수) — 입력 sandbox 테이블 (보통 stg.* 또는 wf.tmp_*).
  - `target_table`: str (선택) — 결과 sandbox FQDN.
        기본 `wf.tmp_run_<pipeline_run_id>_<node_key>`.
  - `limit_rows`: int (선택, 기본 100_000) — 1 회 변환 행 제한.
  - `apply_only_published`: bool (기본 True) — DRAFT/REVIEW mapping 은 무시.

흐름:
  1. domain.field_mapping 에서 contract_id 의 모든 mapping 로드 (status 필터 옵션).
  2. source_table 행을 limit_rows 까지 SELECT.
  3. 각 row 에 대해 mapping 의 `source_path` (json.get_path syntax) + `transform_expr`
     (FunctionRegistry mini-DSL) 평가 → target_column 채움.
  4. target_table 에 INSERT.

가드:
  - source/target 모두 wf|stg|<domain>_stg|<domain>_mart 한정 — sql_guard 가 LOAD_TARGET
    이 아닌 SQL_INLINE_TRANSFORM 컨텍스트로 검증.
  - transform_expr 은 FunctionRegistry allowlist 만 통과.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.functions import FunctionCallError, apply_expression
from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

name = "MAP_FIELDS"
node_type = "MAP_FIELDS"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _validate_fqdn(label: str, fqdn: str, *, allowed_schemas: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(fqdn):
        raise NodeV2Error(f"{label} must match schema.table (got {fqdn!r})")
    schema = fqdn.split(".", 1)[0].lower()
    if schema not in allowed_schemas:
        raise NodeV2Error(
            f"{label} schema {schema!r} not allowed (allowed: {sorted(allowed_schemas)})"
        )
    return fqdn


def _allowed_schemas(domain_code: str) -> frozenset[str]:
    return frozenset(
        {
            "wf",
            "stg",
            f"{domain_code.lower()}_stg",
            f"{domain_code.lower()}_mart",
        }
    )


def _default_target(pipeline_run_id: int, node_key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:32]
    return f"wf.tmp_run_{pipeline_run_id}_{safe}"


def _load_mappings(
    session: Any,
    *,
    contract_id: int,
    apply_only_published: bool,
) -> list[dict[str, Any]]:
    """domain.field_mapping → list of dicts."""
    sql = (
        "SELECT mapping_id, source_path, target_table, target_column, "
        "       transform_expr, data_type, is_required, status, order_no "
        "FROM domain.field_mapping "
        "WHERE contract_id = :cid "
    )
    if apply_only_published:
        sql += "AND status IN ('APPROVED','PUBLISHED') "
    sql += "ORDER BY order_no, mapping_id"
    rows = session.execute(text(sql), {"cid": contract_id}).mappings().all()
    return [dict(r) for r in rows]


def _evaluate_row(row: Mapping[str, Any], mappings: list[dict[str, Any]]) -> dict[str, Any]:
    """1 input row → target column dict. 누락된 필수 필드는 NodeV2Error."""
    out: dict[str, Any] = {}
    for m in mappings:
        col = str(m["target_column"])
        expr = m.get("transform_expr")
        # 우선 source_path 추출.
        source_value = _read_source_path(row, str(m["source_path"]))
        # transform_expr 가 있으면 source_value 가 row 의 일부로 expose.
        if expr:
            try:
                value = apply_expression(
                    str(expr),
                    row={**dict(row), "_value": source_value},
                )
            except FunctionCallError as exc:
                raise NodeV2Error(
                    f"mapping {m['mapping_id']} ({col}): {exc}"
                ) from exc
        else:
            value = source_value
        if value is None and m.get("is_required"):
            raise NodeV2Error(
                f"required field {col} is null (mapping {m['mapping_id']})"
            )
        out[col] = value
    return out


def _read_source_path(row: Mapping[str, Any], path: str) -> Any:
    """`a` (단일 컬럼) 또는 `a.b.c` (JSONB 컬럼 내 path)."""
    if "." not in path:
        return row.get(path)
    head, rest = path.split(".", 1)
    head_val = row.get(head)
    if head_val is None:
        return None
    if isinstance(head_val, str):
        try:
            head_val = json.loads(head_val)
        except json.JSONDecodeError:
            return None
    if not isinstance(head_val, Mapping):
        return None
    cur: Any = head_val
    for part in rest.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _coalesce_target_table(
    mappings: list[dict[str, Any]],
    *,
    config_target: str | None,
    fallback: str,
) -> str:
    if config_target:
        return config_target
    target_set = {m["target_table"] for m in mappings if m.get("target_table")}
    if len(target_set) == 1:
        return str(next(iter(target_set)))
    # 둘 이상 또는 zero — sandbox fallback.
    return fallback


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    contract_id = config.get("contract_id") or context.contract_id
    if not contract_id:
        raise NodeV2Error("MAP_FIELDS requires contract_id")
    source_table = str(config.get("source_table") or "").strip()
    if not source_table:
        raise NodeV2Error("MAP_FIELDS requires source_table")
    apply_only_published = bool(config.get("apply_only_published", True))
    limit_rows = int(config.get("limit_rows") or 100_000)
    if limit_rows <= 0 or limit_rows > 10_000_000:
        raise NodeV2Error(f"limit_rows out of range: {limit_rows}")

    allowed = _allowed_schemas(context.domain_code)
    _validate_fqdn("source_table", source_table, allowed_schemas=allowed)

    mappings = _load_mappings(
        context.session,
        contract_id=int(contract_id),
        apply_only_published=apply_only_published,
    )
    if not mappings:
        return NodeV2Output(
            status="failed",
            error_message=f"no field_mapping for contract_id={contract_id}",
            payload={"reason": "empty_mapping"},
        )

    fallback_target = _default_target(context.pipeline_run_id, context.node_key)
    target_table = _coalesce_target_table(
        mappings, config_target=config.get("target_table"), fallback=fallback_target
    )
    _validate_fqdn("target_table", target_table, allowed_schemas=allowed)

    columns = [m["target_column"] for m in mappings]
    rows = (
        context.session.execute(
            text(f"SELECT * FROM {source_table} LIMIT :lim"),
            {"lim": limit_rows},
        )
        .mappings()
        .all()
    )

    transformed: list[dict[str, Any]] = []
    for r in rows:
        try:
            transformed.append(_evaluate_row(dict(r), mappings))
        except NodeV2Error as exc:
            return NodeV2Output(
                status="failed",
                error_message=str(exc),
                payload={"reason": "mapping_error", "row_count_partial": len(transformed)},
            )

    # CREATE TABLE AS (헤더만 만들고 INSERT) — sandbox 전용.
    context.session.execute(text(f"DROP TABLE IF EXISTS {target_table}"))
    quoted_cols = ", ".join(f'"{c}"' for c in columns)
    context.session.execute(
        text(
            f"CREATE TABLE {target_table} ("
            + ", ".join(f'"{c}" TEXT' for c in columns)
            + ")"
        )
    )

    if transformed:
        placeholders = ", ".join(f":{c}" for c in columns)
        insert_sql = text(
            f"INSERT INTO {target_table} ({quoted_cols}) VALUES ({placeholders})"
        )
        # JSON-coerce dict / list values.
        for row_dict in transformed:
            params = {
                c: (
                    json.dumps(row_dict[c], ensure_ascii=False, default=str)
                    if isinstance(row_dict[c], dict | list)
                    else row_dict[c]
                )
                for c in columns
            }
            context.session.execute(insert_sql, params)

    return NodeV2Output(
        status="success",
        row_count=len(transformed),
        payload={
            "target_table": target_table,
            "columns": columns,
            "row_count": len(transformed),
            "contract_id": int(contract_id),
        },
    )


__all__ = ["name", "node_type", "run"]
