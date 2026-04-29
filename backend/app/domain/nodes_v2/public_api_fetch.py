"""PUBLIC_API_FETCH v2 노드 — Phase 6 Wave 1.

ETL 캔버스의 *DATA SOURCES* 카테고리. 등록된 `domain.public_api_connector` 1건을
실행하고 결과 rows 를 sandbox table 에 적재.

config:
  - `connector_id`: int (필수) — 어떤 등록된 connector 호출할지
  - `runtime_params`: dict (선택) — {ymd}, {page} 등 템플릿 변수 override
  - `max_pages`: int (default 10, 최대 100)
  - `output_table`: str (선택) — sandbox FQDN. 기본 `wf.tmp_run_<rid>_<key>`
  - `dry_run`: bool — True 면 *외부 호출 X*, connector spec 만 검증

흐름:
  1. domain.public_api_connector 에서 spec load
  2. dry_run=True 면 spec 만 반환
  3. dry_run=False 면 generic engine 호출 (HTTP + parse + extract)
  4. rows 를 sandbox 테이블 (output_table) 에 INSERT
  5. domain.public_api_run 에 1건 기록 (run_kind='scheduled' 또는 'dry_run')

가드:
  - PUBLISHED 가 아닌 connector 호출은 *경고 + 실행 허용* (test 시나리오 위함)
  - output_table schema 는 wf / stg / <domain>_stg 만
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output
from app.domain.public_api import (
    call_connector,
    load_spec_from_db,
)

logger = logging.getLogger(__name__)

name = "PUBLIC_API_FETCH"
node_type = "PUBLIC_API_FETCH"

_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _writable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"wf", "stg", f"{domain_code.lower()}_stg"})


def _validate_table(label: str, table: str, allowed: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"{label} must match schema.table (got {table!r})")
    schema = table.split(".", 1)[0].lower()
    if schema not in allowed:
        raise NodeV2Error(
            f"{label} schema {schema!r} not allowed (allowed: {sorted(allowed)})"
        )
    return table


def _default_output(pipeline_run_id: int, node_key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_key)[:32]
    return f"wf.tmp_run_{pipeline_run_id}_{safe}_pubapi"


def _safe_columns(rows: list[dict[str, Any]]) -> list[str]:
    """rows 의 union of keys — column 후보. 안전 식별자만."""
    cols: list[str] = []
    seen: set[str] = set()
    for r in rows[:100]:  # 100 행만 sampling.
        for k in r:
            if k in seen:
                continue
            if not _SAFE_FQDN_RE.match(f"x.{k}"):
                continue  # invalid column name 은 skip.
            seen.add(k)
            cols.append(k)
    return cols


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    connector_id = config.get("connector_id")
    if not connector_id:
        raise NodeV2Error("PUBLIC_API_FETCH requires connector_id")

    runtime_params = dict(config.get("runtime_params") or {})
    max_pages = int(config.get("max_pages") or 10)
    if max_pages < 1 or max_pages > 100:
        raise NodeV2Error(f"max_pages out of range: {max_pages}")
    dry_run = bool(config.get("dry_run", False))

    spec = load_spec_from_db(context.session, connector_id=int(connector_id))
    if spec is None:
        return NodeV2Output(
            status="failed",
            error_message=f"connector {connector_id} not found",
            payload={"reason": "connector_not_found"},
        )

    # PUBLISHED 검증은 *경고만* — node 단계에선 test/dry_run 도 허용.
    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=0,
            payload={
                "dry_run": True,
                "connector_id": int(connector_id),
                "connector_name": spec.name,
                "connector_status": spec.status,
                "endpoint": spec.endpoint_url,
                "max_pages": max_pages,
            },
        )

    # 실 호출.
    result = call_connector(
        spec, runtime_params=runtime_params, max_pages=max_pages
    )
    if result.error_message:
        # 실패 — domain.public_api_run 에 1건 기록.
        _record_run(
            context,
            connector_id=int(connector_id),
            run_kind="scheduled",
            runtime_params=runtime_params,
            request_summary=result.request_summary,
            row_count=0,
            duration_ms=result.duration_ms,
            error_message=result.error_message,
            sample_rows=[],
        )
        return NodeV2Output(
            status="failed",
            error_message=result.error_message,
            payload={
                "reason": "api_error",
                "connector_id": int(connector_id),
                "request_summary": result.request_summary,
            },
        )

    # rows 를 sandbox 테이블에 INSERT.
    output_table = str(
        config.get("output_table")
        or _default_output(context.pipeline_run_id, context.node_key)
    )
    output_table = _validate_table(
        "output_table", output_table, _writable_schemas(context.domain_code)
    )

    columns = _safe_columns(result.rows)
    if not result.rows:
        # rows 가 0 건이거나 모두 unsafe column. row_count 0 으로 success.
        _record_run(
            context,
            connector_id=int(connector_id),
            run_kind="scheduled",
            runtime_params=runtime_params,
            request_summary=result.request_summary,
            row_count=0,
            duration_ms=result.duration_ms,
            sample_rows=[],
        )
        return NodeV2Output(
            status="success",
            row_count=0,
            payload={
                "connector_id": int(connector_id),
                "endpoint": spec.endpoint_url,
                "output_table": output_table,
                "row_count": 0,
                "note": "no rows",
            },
        )

    # CREATE TABLE + INSERT.
    quoted_cols = ", ".join(['"payload"'] + [f'"{c}"' for c in columns])
    create_sql = (
        f"CREATE TABLE {output_table} (payload JSONB"
        + (", " + ", ".join(f'"{c}" TEXT' for c in columns) if columns else "")
        + ")"
    )
    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(text(create_sql))

    placeholders = ", ".join([":payload"] + [f":{c}" for c in columns])
    insert_sql = text(f"INSERT INTO {output_table} ({quoted_cols}) VALUES ({placeholders})")
    inserted = 0
    for row in result.rows:
        params: dict[str, Any] = {
            "payload": json.dumps(row, ensure_ascii=False, default=str)
        }
        for c in columns:
            v = row.get(c)
            if isinstance(v, dict | list):
                params[c] = json.dumps(v, ensure_ascii=False, default=str)
            elif v is None:
                params[c] = None
            else:
                params[c] = str(v)
        context.session.execute(insert_sql, params)
        inserted += 1

    # 실행 이력.
    _record_run(
        context,
        connector_id=int(connector_id),
        run_kind="scheduled",
        runtime_params=runtime_params,
        request_summary=result.request_summary,
        row_count=inserted,
        duration_ms=result.duration_ms,
        sample_rows=result.rows[:5],
    )

    return NodeV2Output(
        status="success",
        row_count=inserted,
        payload={
            "connector_id": int(connector_id),
            "endpoint": spec.endpoint_url,
            "output_table": output_table,
            "columns": columns,
            "row_count": inserted,
            "page_count": result.request_summary.get("page_count", 1),
            "duration_ms": result.duration_ms,
        },
    )


def _record_run(
    context: NodeV2Context,
    *,
    connector_id: int,
    run_kind: str,
    runtime_params: Mapping[str, Any],
    request_summary: Mapping[str, Any],
    row_count: int,
    duration_ms: int,
    sample_rows: list[dict[str, Any]] | None = None,
    error_message: str | None = None,
) -> None:
    context.session.execute(
        text(
            "INSERT INTO domain.public_api_run "
            "(connector_id, run_kind, runtime_params, request_summary, "
            " http_status, row_count, duration_ms, error_message, sample_rows, "
            " triggered_by, completed_at) "
            "VALUES (:cid, :kind, CAST(:rp AS JSONB), CAST(:rs AS JSONB), "
            "        :hs, :rc, :dur, :err, CAST(:samp AS JSONB), :uid, now())"
        ),
        {
            "cid": connector_id,
            "kind": run_kind,
            "rp": json.dumps(dict(runtime_params), default=str),
            "rs": json.dumps(dict(request_summary), default=str),
            "hs": request_summary.get("last_http_status"),
            "rc": row_count,
            "dur": duration_ms,
            "err": error_message,
            "samp": json.dumps(sample_rows or [], default=str, ensure_ascii=False),
            "uid": context.user_id,
        },
    )


__all__ = ["name", "node_type", "run"]
