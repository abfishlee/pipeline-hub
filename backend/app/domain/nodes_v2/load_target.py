"""LOAD_TARGET 노드 — load_policy 기반 generic 적재 (v1 LOAD_MASTER 의 generic 화).

config:
  - `source_table`: str (필수) — wf|stg|<dom>_stg 의 sandbox.
  - `policy_id`: int (선택) — domain.load_policy.policy_id 명시.
  - `resource_id`: int (선택) — policy_id 미지정 시 active load_policy 검색 키.
  - `target_table`: str (선택) — policy 가 정의한 default 가 있으면 무시 가능.
  - `dry_run`: bool (기본 False) — 실 적재 0건, 영향 행 수만 추정.
  - `update_columns`: list[str] | None — 명시 시 그 컬럼만 update_clause 에 사용.

지원 mode (load_policy.mode):
  * append_only        — INSERT INTO target SELECT ... (dup 허용).
  * upsert             — INSERT ... ON CONFLICT (key_columns) DO UPDATE.
  * scd_type_2         — placeholder. Phase 6 STEP 7 구현. 현재 NodeV2Output(failed).
  * current_snapshot   — placeholder. (Phase 6.)

가드 (Q2):
  * write target = approved load_policy 가 명시한 target. 임의 INSERT 차단.
  * sql_guard.LOAD_TARGET 컨텍스트로 *생성한 INSERT 문* 검증.
  * source_table 은 sandbox/staging 만 허용. mart 직접 SELECT 는 SQL_ASSET 사용.

권한:
  * Phase 5 MVP — 노드 실행 자체가 *APPROVED policy* 만 통과하므로 추가 권한 검사 없음.
    Phase 6 에서 RLS / domain.app_user 결합.
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

name = "LOAD_TARGET"
node_type = "LOAD_TARGET"

_TABLE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]{0,62})\.([a-zA-Z_][a-zA-Z0-9_]{0,62})$")
_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _source_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"wf", "stg", f"{domain_code.lower()}_stg"})


def _target_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"mart", f"{domain_code.lower()}_mart"})


def _quote_table(table: str, *, allow: frozenset[str]) -> tuple[str, str, str]:
    m = _TABLE_RE.match(table)
    if m is None:
        raise NodeV2Error(f"invalid table reference: {table!r}")
    schema, name_only = m.group(1), m.group(2)
    if schema.lower() not in allow:
        raise NodeV2Error(f"schema {schema!r} not in {sorted(allow)}")
    return schema, name_only, f'"{schema}"."{name_only}"'


def _quote_col(c: str) -> str:
    if not _COLUMN_RE.match(c):
        raise NodeV2Error(f"invalid column: {c!r}")
    return f'"{c}"'


def _columns_of(session: Any, *, schema: str, table: str) -> list[str]:
    rows = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            "ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    ).all()
    return [str(r.column_name) for r in rows]


def _load_policy_row(
    session: Any, *, policy_id: int | None, resource_id: int | None
) -> dict[str, Any] | None:
    if policy_id is not None:
        sql = (
            "SELECT policy_id, resource_id, mode, key_columns, partition_expr, "
            "       scd_options_json, chunk_size, statement_timeout_ms, status, version "
            "FROM domain.load_policy WHERE policy_id = :pid"
        )
        row = session.execute(text(sql), {"pid": policy_id}).mappings().first()
        return dict(row) if row else None
    if resource_id is not None:
        sql = (
            "SELECT policy_id, resource_id, mode, key_columns, partition_expr, "
            "       scd_options_json, chunk_size, statement_timeout_ms, status, version "
            "FROM domain.load_policy "
            "WHERE resource_id = :rid AND status IN ('APPROVED','PUBLISHED') "
            "ORDER BY version DESC LIMIT 1"
        )
        row = session.execute(text(sql), {"rid": resource_id}).mappings().first()
        return dict(row) if row else None
    return None


def _resource_target_table(session: Any, resource_id: int) -> str | None:
    """resource_definition.fact_table 또는 canonical_table 을 적재 대상으로."""
    row = session.execute(
        text(
            "SELECT fact_table, canonical_table FROM domain.resource_definition "
            "WHERE resource_id = :rid"
        ),
        {"rid": resource_id},
    ).first()
    if row is None:
        return None
    target: str | None = row.fact_table or row.canonical_table
    return target


def _build_upsert(
    *,
    src_qualified: str,
    tgt_qualified: str,
    insert_cols: list[str],
    key_columns: list[str],
    update_cols: list[str],
) -> str:
    insert_cols_q = ", ".join(_quote_col(c) for c in insert_cols)
    select_cols_q = ", ".join(_quote_col(c) for c in insert_cols)
    conflict_cols_q = ", ".join(_quote_col(c) for c in key_columns)
    if update_cols:
        update_clause = ", ".join(
            f"{_quote_col(c)} = EXCLUDED.{_quote_col(c)}" for c in update_cols
        )
        return (
            f"INSERT INTO {tgt_qualified} ({insert_cols_q}) "
            f"SELECT {select_cols_q} FROM {src_qualified} "
            f"ON CONFLICT ({conflict_cols_q}) DO UPDATE SET {update_clause}"
        )
    return (
        f"INSERT INTO {tgt_qualified} ({insert_cols_q}) "
        f"SELECT {select_cols_q} FROM {src_qualified} "
        f"ON CONFLICT ({conflict_cols_q}) DO NOTHING"
    )


def _build_append(
    *, src_qualified: str, tgt_qualified: str, insert_cols: list[str]
) -> str:
    insert_cols_q = ", ".join(_quote_col(c) for c in insert_cols)
    select_cols_q = ", ".join(_quote_col(c) for c in insert_cols)
    return (
        f"INSERT INTO {tgt_qualified} ({insert_cols_q}) "
        f"SELECT {select_cols_q} FROM {src_qualified}"
    )


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    source_raw = str(config.get("source_table") or "").strip()
    if not source_raw:
        raise NodeV2Error("LOAD_TARGET requires source_table")
    policy_id = config.get("policy_id")
    resource_id = config.get("resource_id")
    if policy_id is None and resource_id is None:
        raise NodeV2Error("LOAD_TARGET requires policy_id or resource_id")
    dry_run = bool(config.get("dry_run", False))

    policy = _load_policy_row(
        context.session,
        policy_id=int(policy_id) if policy_id is not None else None,
        resource_id=int(resource_id) if resource_id is not None else None,
    )
    if policy is None:
        return NodeV2Output(
            status="failed",
            error_message="load_policy not found",
            payload={"reason": "policy_not_found"},
        )
    if policy["status"] not in ("APPROVED", "PUBLISHED"):
        return NodeV2Output(
            status="failed",
            error_message=(
                f"load_policy {policy['policy_id']} status={policy['status']} "
                "must be APPROVED/PUBLISHED"
            ),
            payload={"reason": "policy_not_approved"},
        )

    mode = str(policy["mode"])
    key_columns = [str(c) for c in (policy.get("key_columns") or [])]

    target_raw = str(
        config.get("target_table")
        or (
            _resource_target_table(context.session, int(policy["resource_id"])) or ""
        )
    ).strip()
    if not target_raw:
        return NodeV2Output(
            status="failed",
            error_message="target_table not derivable from policy/resource",
            payload={"reason": "no_target"},
        )

    src_schema, src_name, src_qualified = _quote_table(
        source_raw, allow=_source_schemas(context.domain_code)
    )
    tgt_schema, tgt_name, tgt_qualified = _quote_table(
        target_raw, allow=_target_schemas(context.domain_code)
    )

    src_cols = _columns_of(context.session, schema=src_schema, table=src_name)
    tgt_cols = _columns_of(context.session, schema=tgt_schema, table=tgt_name)
    if not src_cols:
        raise NodeV2Error(f"source table {source_raw} has no columns or missing")
    if not tgt_cols:
        raise NodeV2Error(f"target table {target_raw} has no columns or missing")

    common = [c for c in src_cols if c in tgt_cols]
    if not common:
        raise NodeV2Error(f"no common columns between {source_raw} and {target_raw}")

    if mode in ("upsert", "scd_type_2", "current_snapshot"):
        if not key_columns:
            return NodeV2Output(
                status="failed",
                error_message=f"mode={mode} requires policy.key_columns",
                payload={"reason": "missing_key"},
            )
        for k in key_columns:
            if k not in common:
                return NodeV2Output(
                    status="failed",
                    error_message=f"key_column {k!r} missing from source/target",
                    payload={"reason": "missing_key_column"},
                )

    if mode == "append_only":
        sql = _build_append(
            src_qualified=src_qualified, tgt_qualified=tgt_qualified, insert_cols=common
        )
    elif mode == "upsert":
        update_cols_cfg = config.get("update_columns")
        if update_cols_cfg is None:
            update_cols = [c for c in common if c not in key_columns]
        else:
            update_cols = [str(c) for c in update_cols_cfg]
            for u in update_cols:
                if u not in common:
                    return NodeV2Output(
                        status="failed",
                        error_message=f"update column {u!r} not in common",
                        payload={"reason": "missing_update_col"},
                    )
        insert_cols = key_columns + [c for c in update_cols if c not in key_columns]
        sql = _build_upsert(
            src_qualified=src_qualified,
            tgt_qualified=tgt_qualified,
            insert_cols=insert_cols,
            key_columns=key_columns,
            update_cols=update_cols,
        )
    else:  # scd_type_2 / current_snapshot
        return NodeV2Output(
            status="failed",
            error_message=f"mode={mode} is not implemented yet (Phase 6)",
            payload={"reason": "mode_not_implemented", "mode": mode},
        )

    # 가드: 생성된 INSERT 문도 sql_guard 통과 강제 — write target whitelist.
    extra: frozenset[str] = frozenset(
        {f"{context.domain_code}_mart", f"{context.domain_code}_stg", "mart", "stg", "wf"}
    )
    try:
        guard_sql(
            sql,
            ctx=SqlNodeContext(
                node_kind=NodeKind.LOAD_TARGET,
                domain_code=context.domain_code,
                allowed_extra_schemas=extra,
                allowed_load_targets=frozenset({target_raw.lower()}),
            ),
        )
    except SqlGuardError as exc:
        return NodeV2Output(
            status="failed",
            error_message=f"sql guard violation: {exc}",
            payload={"reason": "sql_guard"},
        )

    if dry_run:
        # SELECT 부분만 COUNT.
        select_only = (
            f"SELECT {', '.join(_quote_col(c) for c in common)} FROM {src_qualified}"
        )
        scalar = context.session.execute(
            text(f"SELECT COUNT(*) FROM ({select_only}) _q")
        ).scalar_one()
        return NodeV2Output(
            status="success",
            row_count=int(scalar or 0),
            payload={
                "dry_run": True,
                "policy_id": int(policy["policy_id"]),
                "mode": mode,
                "estimated_rows": int(scalar or 0),
                "target_table": target_raw,
            },
        )

    # statement_timeout 적용 (정책 정의값).
    timeout_ms = int(policy.get("statement_timeout_ms") or 60000)
    context.session.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
    result = context.session.execute(text(sql))
    rows_affected = int(getattr(result, "rowcount", 0) or 0)

    return NodeV2Output(
        status="success",
        row_count=rows_affected,
        payload={
            "policy_id": int(policy["policy_id"]),
            "mode": mode,
            "source_table": source_raw,
            "target_table": target_raw,
            "rows_affected": rows_affected,
        },
    )


__all__ = ["name", "node_type", "run"]
