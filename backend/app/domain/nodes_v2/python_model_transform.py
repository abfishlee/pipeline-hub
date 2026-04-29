"""PYTHON_MODEL_TRANSFORM node.

Runs a small Canvas-authored Python model in the worker process. This is meant
for logic that is awkward in SQL: parsing OCR text, fuzzy matching, external
normalization, or row-by-row enrichment. Large joins, aggregations, and mart
loads should stay in SQL/DB nodes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

name = "PYTHON_MODEL_TRANSFORM"
node_type = "PYTHON_MODEL_TRANSFORM"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_PRODUCTION_STATUSES = ("APPROVED", "PUBLISHED")


def _default_output(pipeline_run_id: int, node_key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:32]
    return f"wf.tmp_run_{pipeline_run_id}_{safe}"


def _writable_schemas(domain_code: str) -> frozenset[str]:
    dom = domain_code.lower()
    return frozenset({"wf", "stg", f"{dom}_stg"})


def _validate_table(table: str, *, allowed_schemas: frozenset[str] | None = None) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"table must match schema.table (got {table!r})")
    if allowed_schemas is not None:
        schema = table.split(".", 1)[0].lower()
        if schema not in allowed_schemas:
            raise NodeV2Error(
                f"output_table schema {schema!r} not allowed "
                f"(allowed: {sorted(allowed_schemas)})"
            )
    return table


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


def _load_python_asset(
    session: Any,
    *,
    asset_code: str,
    version: int | None,
    domain_code: str,
) -> dict[str, Any] | None:
    cols = "asset_id, asset_code, version, asset_type, sql_text, status, is_active"
    if version is None:
        sql = (
            f"SELECT {cols} FROM domain.sql_asset "
            "WHERE asset_code = :code AND domain_code = :dom "
            "AND asset_type = 'PYTHON_SCRIPT' "
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
            "AND asset_type = 'PYTHON_SCRIPT' "
            "AND is_active = true"
        )
        params = {"code": asset_code, "dom": domain_code, "ver": int(version)}
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def _render_template(value: str, params: Mapping[str, Any]) -> str:
    rendered = value
    for key, param in params.items():
        rendered = rendered.replace("{{" + key + "}}", "" if param is None else str(param))
    missing = sorted(set(re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", rendered)))
    if missing:
        raise NodeV2Error(f"unresolved Python model template parameters: {missing}")
    return rendered


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _read_rows(context: NodeV2Context, table: str, limit: int = 1000) -> list[dict[str, Any]]:
    table = _validate_table(table)
    limit = max(1, min(int(limit), 100_000))
    rows = context.session.execute(text(f"SELECT * FROM {table} LIMIT :limit"), {"limit": limit})
    return [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows.mappings().all()]


def _write_rows(context: NodeV2Context, table: str, rows: list[dict[str, Any]]) -> int:
    table = _validate_table(table, allowed_schemas=_writable_schemas(context.domain_code))
    context.session.execute(text(f"DROP TABLE IF EXISTS {table}"))
    if not rows:
        context.session.execute(text(f"CREATE TABLE {table} (_empty boolean)"))
        return 0

    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            if not _SAFE_NAME_RE.match(str(key)):
                raise NodeV2Error(f"result column {key!r} is not a safe SQL identifier")
            if key not in columns:
                columns.append(str(key))

    ddl_cols = ", ".join(f"{c} TEXT" for c in columns)
    context.session.execute(text(f"CREATE TABLE {table} ({ddl_cols})"))
    insert_cols = ", ".join(columns)
    bind_cols = ", ".join(f":{c}" for c in columns)
    insert_sql = text(f"INSERT INTO {table} ({insert_cols}) VALUES ({bind_cols})")
    payload = [{c: None if row.get(c) is None else str(row.get(c)) for c in columns} for row in rows]
    context.session.execute(insert_sql, payload)
    return len(rows)


def _validate_python_code(code: str) -> None:
    lowered = code.lower()
    forbidden = (
        "import os",
        "import subprocess",
        "__import__",
        "open(",
        "eval(",
        "exec(",
        "compile(",
        "socket",
    )
    if any(token in lowered for token in forbidden):
        raise NodeV2Error(
            "Python model cannot use os/subprocess/import hooks/open/eval/exec/socket"
        )


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    upstream_key, upstream_payload = _pick_upstream_payload(context, config)
    input_table = str(config.get("input_table") or "").strip() or _table_from_payload(
        upstream_payload
    )
    output_table = str(
        config.get("output_table") or _default_output(context.pipeline_run_id, context.node_key)
    )
    output_table = _validate_table(
        output_table, allowed_schemas=_writable_schemas(context.domain_code)
    )

    asset_code = str(config.get("asset_code") or "").strip()
    version = config.get("version")
    asset: dict[str, Any] | None = None
    if asset_code:
        asset = _load_python_asset(
            context.session,
            asset_code=asset_code,
            version=int(version) if version is not None else None,
            domain_code=context.domain_code,
        )
        if asset is None:
            return NodeV2Output(
                status="failed",
                error_message=f"python model {asset_code!r} not found, inactive, or not approved",
                payload={"reason": "asset_not_found"},
            )
        code = str(asset["sql_text"])
    else:
        code = str(config.get("code") or "")

    code = code.strip()
    if not code:
        raise NodeV2Error("PYTHON_MODEL_TRANSFORM requires code or asset_code")
    _validate_python_code(code)

    params = {
        "domain_code": context.domain_code,
        "run_id": context.pipeline_run_id,
        "node_key": context.node_key,
        "input_from": upstream_key,
        "input_table": input_table,
        "output_table": output_table,
    }
    code = _render_template(code, params)

    result_rows: list[dict[str, Any]] = []

    def read_rows(table: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        target = table or input_table
        if not target:
            raise NodeV2Error("read_rows requires a table or upstream input_table")
        return _read_rows(context, str(target), limit)

    def write_rows(rows: list[dict[str, Any]], table: str | None = None) -> int:
        return _write_rows(context, str(table or output_table), rows)

    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
    }
    globals_dict: dict[str, Any] = {"__builtins__": safe_builtins, "re": re, "Decimal": Decimal}
    locals_dict: dict[str, Any] = {
        "input_table": input_table,
        "output_table": output_table,
        "domain_code": context.domain_code,
        "run_id": context.pipeline_run_id,
        "node_key": context.node_key,
        "read_rows": read_rows,
        "write_rows": write_rows,
        "result_rows": result_rows,
    }
    try:
        exec(code, globals_dict, locals_dict)
    except Exception as exc:
        return NodeV2Output(
            status="failed",
            error_message=f"Python model failed: {type(exc).__name__}: {exc}",
            payload={"reason": "python_exception"},
        )

    rows = locals_dict.get("result_rows")
    row_count = 0
    if isinstance(rows, list) and rows:
        if not all(isinstance(r, dict) for r in rows):
            raise NodeV2Error("result_rows must be a list of dict objects")
        row_count = _write_rows(context, output_table, rows)
    else:
        exists = context.session.execute(
            text(
                "SELECT to_regclass(:table_name) IS NOT NULL"
            ),
            {"table_name": output_table},
        ).scalar_one()
        if exists:
            row_count = int(
                context.session.execute(text(f"SELECT COUNT(*) FROM {output_table}")).scalar_one()
                or 0
            )

    return NodeV2Output(
        status="success",
        row_count=row_count,
        payload={
            "output_table": output_table,
            "row_count": row_count,
            "asset_code": asset_code or None,
            "asset_version": int(asset["version"]) if asset else None,
            "template_params": params,
        },
    )


__all__ = ["name", "node_type", "run"]
