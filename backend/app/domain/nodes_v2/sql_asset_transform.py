"""SQL_ASSET_TRANSFORM 노드 — APPROVED/PUBLISHED sql_asset 만 실행 (Q2 답변).

INLINE 과의 차이 (PHASE_5_GENERIC_PLATFORM § 5.2.2):

  | 항목              | INLINE                  | ASSET                       |
  | ----------------- | ----------------------- | --------------------------- |
  | SQL 위치          | 노드 config             | domain.sql_asset row        |
  | 가능한 status     | 항상 실행 가능          | APPROVED/PUBLISHED 만       |
  | 결과 테이블       | wf/stg/<dom>_stg only   | asset.output_table 우선     |
  | 사용자            | 개발/탐색               | production 정기 파이프라인  |

config:
  - `asset_code`: str (필수) — domain.sql_asset.asset_code.
  - `version`: int | None (선택) — 미지정 시 동일 asset_code 의 가장 높은 PUBLISHED 채택.
  - `output_table`: str (선택) — asset.output_table override (sandbox 권장).
  - `materialize`: bool (기본 True).
  - `dry_run`: bool (기본 False) — *언제나* rollback. caller 가 sandbox preview 시.

가드:
  - asset.status ∈ {APPROVED, PUBLISHED} 강제. DRAFT/REVIEW 는 항상 거부.
  - SQL 본문도 sql_guard.SQL_ASSET_TRANSFORM 컨텍스트 통과 필요 (저장 시 한 번 + 실행 시 한 번).
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

name = "SQL_ASSET_TRANSFORM"
node_type = "SQL_ASSET_TRANSFORM"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_PRODUCTION_STATUSES = ("APPROVED", "PUBLISHED")


def _writable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset(
        {
            "wf",
            "stg",
            f"{domain_code.lower()}_stg",
            f"{domain_code.lower()}_mart",
        }
    )


def _validate_target(table: str, *, allowed_schemas: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"output_table must match schema.table (got {table!r})")
    schema = table.split(".", 1)[0].lower()
    if schema not in allowed_schemas:
        raise NodeV2Error(
            f"output_table schema {schema!r} not allowed "
            f"(allowed: {sorted(allowed_schemas)})"
        )
    return table


def _default_output(pipeline_run_id: int, node_key: str, asset_code: str) -> str:
    safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:24]
    safe_asset = re.sub(r"[^a-zA-Z0-9_]", "_", asset_code)[:24]
    return f"wf.tmp_run_{pipeline_run_id}_{safe_key}_{safe_asset}"


def _load_asset(
    session: Any,
    *,
    asset_code: str,
    version: int | None,
    domain_code: str,
) -> dict[str, Any] | None:
    """asset_code (+ version optional) → row. APPROVED/PUBLISHED 만 채택."""
    if version is None:
        sql = (
            "SELECT asset_id, asset_code, version, sql_text, output_table, status "
            "FROM domain.sql_asset "
            "WHERE asset_code = :code AND domain_code = :dom "
            "  AND status = ANY(:statuses) "
            "ORDER BY version DESC LIMIT 1"
        )
        params: dict[str, Any] = {
            "code": asset_code,
            "dom": domain_code,
            "statuses": list(_PRODUCTION_STATUSES),
        }
    else:
        sql = (
            "SELECT asset_id, asset_code, version, sql_text, output_table, status "
            "FROM domain.sql_asset "
            "WHERE asset_code = :code AND domain_code = :dom AND version = :ver"
        )
        params = {"code": asset_code, "dom": domain_code, "ver": int(version)}
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    asset_code = str(config.get("asset_code") or "").strip()
    if not asset_code:
        raise NodeV2Error("SQL_ASSET_TRANSFORM requires asset_code")
    version = config.get("version")
    materialize = bool(config.get("materialize", True))
    dry_run = bool(config.get("dry_run", False))

    asset = _load_asset(
        context.session,
        asset_code=asset_code,
        version=int(version) if version is not None else None,
        domain_code=context.domain_code,
    )
    if asset is None:
        return NodeV2Output(
            status="failed",
            error_message=f"sql_asset {asset_code!r} not found or not approved",
            payload={"reason": "asset_not_found"},
        )
    if asset["status"] not in _PRODUCTION_STATUSES:
        return NodeV2Output(
            status="failed",
            error_message=(
                f"sql_asset {asset_code} v{asset['version']} status={asset['status']} "
                "must be APPROVED or PUBLISHED"
            ),
            payload={"reason": "asset_not_approved"},
        )

    sql_body = str(asset["sql_text"]).strip().rstrip(";")
    extra: frozenset[str] = frozenset(
        {
            f"{context.domain_code}_mart",
            f"{context.domain_code}_stg",
            f"{context.domain_code}_raw",
        }
    )
    try:
        guard_sql(
            sql_body,
            ctx=SqlNodeContext(
                node_kind=NodeKind.SQL_ASSET_TRANSFORM,
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

    writable = _writable_schemas(context.domain_code)
    output_table = str(
        config.get("output_table")
        or asset.get("output_table")
        or _default_output(context.pipeline_run_id, context.node_key, asset_code)
    )
    output_table = _validate_target(output_table, allowed_schemas=writable)

    if dry_run:
        scalar = context.session.execute(
            text(f"SELECT COUNT(*) FROM ({sql_body}) _q")
        ).scalar_one()
        count = int(scalar or 0)
        return NodeV2Output(
            status="success",
            row_count=count,
            payload={
                "dry_run": True,
                "asset_code": asset_code,
                "asset_version": int(asset["version"]),
                "row_count": count,
            },
        )

    if not materialize:
        scalar = context.session.execute(
            text(f"SELECT COUNT(*) FROM ({sql_body}) _q")
        ).scalar_one()
        count = int(scalar or 0)
        return NodeV2Output(
            status="success",
            row_count=count,
            payload={
                "asset_code": asset_code,
                "asset_version": int(asset["version"]),
                "output_table": None,
                "materialize": False,
                "row_count": count,
            },
        )

    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(text(f"CREATE TABLE {output_table} AS {sql_body}"))
    row_count = int(
        context.session.execute(text(f"SELECT COUNT(*) FROM {output_table}")).scalar_one() or 0
    )
    return NodeV2Output(
        status="success",
        row_count=row_count,
        payload={
            "asset_code": asset_code,
            "asset_version": int(asset["version"]),
            "asset_status": asset["status"],
            "output_table": output_table,
            "materialize": True,
            "row_count": row_count,
        },
    )


__all__ = ["name", "node_type", "run"]
