"""SQL_ASSET_TRANSFORM node.

The node executes an approved SQL Studio asset. SELECT-like assets are
materialized with CREATE TABLE AS. DML/FUNCTION/PROCEDURE assets are executed as
scripts after approval. Canvas upstream outputs are available as template
parameters such as ``{{input_table}}``.
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
_SCRIPT_TYPES = {"DML_SCRIPT", "FUNCTION", "PROCEDURE"}


def _writable_schemas(domain_code: str) -> frozenset[str]:
    dom = domain_code.lower()
    return frozenset({"wf", "stg", f"{dom}_stg", f"{dom}_mart"})


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
    cols = (
        "asset_id, asset_code, version, asset_type, sql_text, output_table, "
        "status, is_active"
    )
    if version is None:
        sql = (
            f"SELECT {cols} FROM domain.sql_asset "
            "WHERE asset_code = :code AND domain_code = :dom "
            "AND status = ANY(:statuses) "
            "AND is_active = true "
            "ORDER BY version DESC LIMIT 1"
        )
        params: dict[str, Any] = {
            "code": asset_code,
            "dom": domain_code,
            "statuses": list(_PRODUCTION_STATUSES),
        }
    else:
        sql = (
            f"SELECT {cols} FROM domain.sql_asset "
            "WHERE asset_code = :code AND domain_code = :dom AND version = :ver "
            "AND is_active = true"
        )
        params = {"code": asset_code, "dom": domain_code, "ver": int(version)}
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def _pick_upstream_payload(
    context: NodeV2Context, config: Mapping[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    requested = str(config.get("input_from") or "").strip()
    if requested and requested in context.upstream_outputs:
        return requested, dict(context.upstream_outputs[requested])
    if not context.upstream_outputs:
        return None, {}
    key = sorted(context.upstream_outputs.keys())[0]
    return key, dict(context.upstream_outputs[key])


def _table_from_payload(payload: Mapping[str, Any]) -> str | None:
    for key in ("output_table", "target_table", "source_table", "table"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _render_sql(
    sql: str,
    *,
    context: NodeV2Context,
    config: Mapping[str, Any],
    output_table: str | None,
) -> tuple[str, dict[str, Any]]:
    upstream_key, upstream_payload = _pick_upstream_payload(context, config)
    input_table = str(config.get("input_table") or "").strip() or _table_from_payload(
        upstream_payload
    )
    params: dict[str, Any] = {
        "domain_code": context.domain_code,
        "run_id": context.pipeline_run_id,
        "node_key": context.node_key,
        "input_from": upstream_key,
        "input_table": input_table,
        "output_table": output_table,
    }
    rendered = sql
    for key, value in params.items():
        rendered = rendered.replace("{{" + key + "}}", "" if value is None else str(value))
    missing = sorted(set(re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", rendered)))
    if missing:
        raise NodeV2Error(f"unresolved SQL template parameters: {missing}")
    return rendered, params


def _validate_select_sql(sql_body: str, *, context: NodeV2Context, asset_type: str) -> str | None:
    extra = frozenset(
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
                node_kind=NodeKind.DQ_CHECK
                if asset_type == "QUALITY_CHECK_SQL"
                else NodeKind.SQL_ASSET_TRANSFORM,
                domain_code=context.domain_code,
                allowed_extra_schemas=extra,
            ),
        )
    except SqlGuardError as exc:
        return f"sql guard violation: {exc}"
    return None


def _validate_script_sql(sql_body: str, asset_type: str) -> str | None:
    upper = sql_body.strip().upper()
    if asset_type == "FUNCTION":
        if not upper.startswith("CREATE OR REPLACE FUNCTION "):
            return "FUNCTION asset must start with CREATE OR REPLACE FUNCTION"
    elif asset_type == "PROCEDURE":
        if not upper.startswith("CREATE OR REPLACE PROCEDURE "):
            return "PROCEDURE asset must start with CREATE OR REPLACE PROCEDURE"
    elif asset_type == "DML_SCRIPT":
        forbidden = ("DROP ", "TRUNCATE ", "ALTER ", "CREATE EXTENSION", "GRANT ", "REVOKE ")
        if any(token in upper for token in forbidden):
            return "DML_SCRIPT cannot contain DROP/TRUNCATE/ALTER/EXTENSION/GRANT/REVOKE"
        if not upper.startswith(("INSERT ", "UPDATE ", "DELETE ", "WITH ")):
            return "DML_SCRIPT must start with INSERT, UPDATE, DELETE, or WITH"
    return None


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

    asset_type = str(asset.get("asset_type") or "TRANSFORM_SQL")
    raw_sql = str(asset["sql_text"]).strip().rstrip(";")
    output_table = None
    if asset_type not in _SCRIPT_TYPES:
        output_table = str(
            config.get("output_table")
            or asset.get("output_table")
            or _default_output(context.pipeline_run_id, context.node_key, asset_code)
        )
        output_table = _validate_target(
            output_table, allowed_schemas=_writable_schemas(context.domain_code)
        )

    sql_body, template_params = _render_sql(
        raw_sql,
        context=context,
        config=config,
        output_table=output_table,
    )

    validation_error = (
        _validate_script_sql(sql_body, asset_type)
        if asset_type in _SCRIPT_TYPES
        else _validate_select_sql(sql_body, context=context, asset_type=asset_type)
    )
    if validation_error:
        return NodeV2Output(
            status="failed",
            error_message=validation_error,
            payload={"reason": "sql_guard", "asset_type": asset_type},
        )

    if asset_type in _SCRIPT_TYPES:
        if dry_run:
            return NodeV2Output(
                status="success",
                payload={
                    "dry_run": True,
                    "asset_code": asset_code,
                    "asset_version": int(asset["version"]),
                    "asset_type": asset_type,
                    "template_params": template_params,
                },
            )
        result = context.session.execute(text(sql_body))
        row_count = int(result.rowcount or 0)
        return NodeV2Output(
            status="success",
            row_count=row_count,
            payload={
                "asset_code": asset_code,
                "asset_version": int(asset["version"]),
                "asset_type": asset_type,
                "row_count": row_count,
                "template_params": template_params,
            },
        )

    if dry_run or not materialize:
        scalar = context.session.execute(
            text(f"SELECT COUNT(*) FROM ({sql_body}) _q")
        ).scalar_one()
        count = int(scalar or 0)
        return NodeV2Output(
            status="success",
            row_count=count,
            payload={
                "dry_run": dry_run,
                "asset_code": asset_code,
                "asset_version": int(asset["version"]),
                "asset_type": asset_type,
                "output_table": None if not materialize else output_table,
                "materialize": materialize,
                "row_count": count,
                "template_params": template_params,
            },
        )

    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(text(f"CREATE TABLE {output_table} AS {sql_body}"))
    row_count = int(
        context.session.execute(text(f"SELECT COUNT(*) FROM {output_table}")).scalar_one()
        or 0
    )
    return NodeV2Output(
        status="success",
        row_count=row_count,
        payload={
            "asset_code": asset_code,
            "asset_version": int(asset["version"]),
            "asset_status": asset["status"],
            "asset_type": asset_type,
            "output_table": output_table,
            "materialize": True,
            "row_count": row_count,
            "template_params": template_params,
        },
    )


__all__ = ["name", "node_type", "run"]
