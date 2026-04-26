"""HTTP_TRANSFORM 노드 — secret_ref 통일 외부 정제 API 호출 (Q3 답변).

흐름:
  1. source_id + provider_kind='HTTP_TRANSFORM' 의 active binding 조회 (priority).
  2. provider.secret_ref → resolve_secret(env / Settings) — 평문은 DB 에 저장 안 됨.
  3. binding.config_json + provider.config_schema 머지 → endpoint/timeout/headers.
  4. input rows (source_table 또는 inline rows) 를 chunk_size 만큼 POST.
  5. response 의 매핑 필드를 sandbox 결과 테이블에 INSERT.

config:
  - `source_table`: str — 입력 sandbox FQDN (선택; rows 와 둘 중 하나 필수).
  - `rows`: list[dict] — 인라인 입력 (선택).
  - `request_template`: dict (선택) — body 베이스. `${col}` 토큰이 row 의 컬럼으로 치환.
  - `response_path`: str (선택) — JSONPath-lite. 응답 root 가 list 가 아니면 본 path
    의 값을 결과로 사용.
  - `output_table`: str (선택) — 결과 저장 sandbox FQDN.
  - `chunk_size`: int (기본 50). 1 ≤ x ≤ 1000.
  - `timeout_sec`: int (기본 15).

가드:
  - HTTP 호출은 caller 가 *외부 사이드 이펙트* 를 인지하고 dry_run=False 시점에만
    실제 호출. dry_run=True 시 *입력 row 수만 반환* (외부 호출 0건).
  - Phase 5 MVP — circuit breaker 미적용 (Q3 의 "통일" 은 *secret_ref* 부분).
    breaker 통합은 STEP 4 follow-up.

예시 config:
  {
    "source_table": "agri_stg.cleaned_2026_04",
    "request_template": {
      "raw_text": "${address}",
      "options": {"normalize": true}
    },
    "response_path": "result.normalized",
    "output_table": "wf.tmp_run_42_addr",
    "chunk_size": 25
  }
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.functions.registry import _json_get_path
from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output
from app.domain.providers.factory import list_active_bindings, resolve_secret

logger = logging.getLogger(__name__)

name = "HTTP_TRANSFORM"
node_type = "HTTP_TRANSFORM"

_TEMPLATE_TOKEN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_SAFE_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _writable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"wf", "stg", f"{domain_code.lower()}_stg"})


def _readable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset(
        {
            "wf",
            "stg",
            f"{domain_code.lower()}_stg",
            f"{domain_code.lower()}_mart",
            f"{domain_code.lower()}_raw",
        }
    )


def _validate_table(label: str, table: str, *, allowed: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"{label} must match schema.table (got {table!r})")
    schema = table.split(".", 1)[0].lower()
    if schema not in allowed:
        raise NodeV2Error(f"{label} schema {schema!r} not allowed (allowed: {sorted(allowed)})")
    return table


def _render_template(tmpl: Any, row: Mapping[str, Any]) -> Any:
    """템플릿 dict/list/str 의 `${col}` 토큰을 row 의 컬럼으로 재귀 치환.
    토큰이 단독으로 등장하면 *원본 타입* 보존, 부분 치환이면 str 강제.
    """
    if isinstance(tmpl, str):
        m_full = _TEMPLATE_TOKEN.fullmatch(tmpl)
        if m_full is not None:
            return row.get(m_full.group(1))
        return _TEMPLATE_TOKEN.sub(lambda m: str(row.get(m.group(1), "")), tmpl)
    if isinstance(tmpl, list):
        return [_render_template(item, row) for item in tmpl]
    if isinstance(tmpl, Mapping):
        return {k: _render_template(v, row) for k, v in tmpl.items()}
    return tmpl


def _ensure_secret(secret_ref: str | None, *, secret_value: str | None) -> str | None:
    """factory 가 이미 resolve_secret 했으면 그대로, 아니면 직접 resolve."""
    if secret_value is not None:
        return secret_value
    if secret_ref:
        return resolve_secret(secret_ref)
    return None


async def _call_http(
    *,
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_sec: int,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """1 회 POST. response 가 JSON 이 아니면 None 반환."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        resp = await client.post(endpoint, json=payload, headers=headers)
        try:
            return resp.status_code, resp.json()
        except (json.JSONDecodeError, ValueError):
            return resp.status_code, None


def _extract_response(
    response: dict[str, Any] | list[Any] | None, response_path: str | None
) -> Any:
    """response_path 가 있으면 추출, 없으면 root 그대로."""
    if response is None:
        return None
    if not response_path:
        return response
    if isinstance(response, list):
        return response
    return _json_get_path(response, response_path)


def _read_input_rows(
    session: Any,
    *,
    source_table: str | None,
    inline_rows: list[dict[str, Any]] | None,
    limit: int,
) -> list[dict[str, Any]]:
    if inline_rows is not None:
        return [dict(r) for r in inline_rows][:limit]
    if not source_table:
        return []
    rows = (
        session.execute(text(f"SELECT * FROM {source_table} LIMIT :lim"), {"lim": limit})
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    if context.source_id is None and not config.get("provider_code"):
        raise NodeV2Error(
            "HTTP_TRANSFORM requires context.source_id (binding 조회) "
            "or explicit provider_code"
        )

    source_table = config.get("source_table")
    inline_rows = config.get("rows")
    if not source_table and inline_rows is None:
        raise NodeV2Error("HTTP_TRANSFORM requires source_table or rows")

    chunk_size = int(config.get("chunk_size") or 50)
    if chunk_size < 1 or chunk_size > 1000:
        raise NodeV2Error(f"chunk_size out of range: {chunk_size}")
    timeout_sec = int(config.get("timeout_sec") or 15)
    if timeout_sec < 1 or timeout_sec > 300:
        raise NodeV2Error(f"timeout_sec out of range: {timeout_sec}")
    dry_run = bool(config.get("dry_run", False))
    response_path = config.get("response_path")
    request_template = config.get("request_template") or {}

    # --- 1. binding 조회 + secret 해결 ---
    if context.source_id is not None:
        bindings = list_active_bindings(
            context.session, source_id=context.source_id, provider_kind="HTTP_TRANSFORM"
        )
        if not bindings:
            return NodeV2Output(
                status="failed",
                error_message=(
                    f"no active HTTP_TRANSFORM binding for source_id={context.source_id}"
                ),
                payload={"reason": "no_binding"},
            )
        binding = bindings[0]
        endpoint = str(binding.config.get("endpoint") or "")
        secret_value = _ensure_secret(binding.secret_ref, secret_value=None)
        provider_code = binding.provider_code
    else:
        endpoint = str(config.get("endpoint") or "")
        secret_value = _ensure_secret(str(config.get("secret_ref") or ""), secret_value=None)
        provider_code = str(config["provider_code"])

    if not endpoint:
        return NodeV2Output(
            status="failed",
            error_message="endpoint not configured",
            payload={"reason": "no_endpoint"},
        )

    # --- 2. input rows ---
    readable = _readable_schemas(context.domain_code)
    if source_table:
        _validate_table("source_table", str(source_table), allowed=readable)
    rows = _read_input_rows(
        context.session,
        source_table=str(source_table) if source_table else None,
        inline_rows=list(inline_rows) if inline_rows else None,
        limit=10_000,
    )
    if not rows:
        return NodeV2Output(
            status="success",
            row_count=0,
            payload={"reason": "empty_input", "endpoint": endpoint},
        )

    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=len(rows),
            payload={
                "dry_run": True,
                "input_rows": len(rows),
                "endpoint": endpoint,
                "provider_code": provider_code,
                "estimated_calls": (len(rows) + chunk_size - 1) // chunk_size,
            },
        )

    # --- 3. output table ---
    writable = _writable_schemas(context.domain_code)
    output_table = str(
        config.get("output_table")
        or f"wf.tmp_run_{context.pipeline_run_id}_"
        f"{re.sub(r'[^a-zA-Z0-9_]', '_', context.node_key)[:32]}"
    )
    output_table = _validate_table("output_table", output_table, allowed=writable)
    context.session.execute(text(f"DROP TABLE IF EXISTS {output_table}"))
    context.session.execute(
        text(
            f"CREATE TABLE {output_table} ("
            f"  _row_idx INTEGER PRIMARY KEY, "
            f"  request_json JSONB, "
            f"  response_json JSONB, "
            f"  status_code INTEGER, "
            f"  is_success BOOLEAN"
            f")"
        )
    )

    # --- 4. 호출 + INSERT ---
    headers = {"Content-Type": "application/json"}
    if secret_value:
        headers["Authorization"] = f"Bearer {secret_value}"

    import asyncio

    async def _process_all() -> tuple[int, int]:
        success = 0
        failure = 0
        insert_sql = text(
            f"INSERT INTO {output_table} "
            "(_row_idx, request_json, response_json, status_code, is_success) "
            "VALUES (:idx, CAST(:req AS JSONB), CAST(:resp AS JSONB), :sc, :ok)"
        )
        for idx, row in enumerate(rows):
            req_payload = _render_template(request_template, row)
            try:
                status_code, raw_response = await _call_http(
                    endpoint=endpoint,
                    headers=headers,
                    payload=req_payload if isinstance(req_payload, dict) else {"value": req_payload},
                    timeout_sec=timeout_sec,
                )
            except Exception as exc:
                logger.warning("http_transform call failed: %s", exc)
                context.session.execute(
                    insert_sql,
                    {
                        "idx": idx,
                        "req": json.dumps(req_payload, default=str),
                        "resp": json.dumps({"error": str(exc)[:500]}),
                        "sc": 0,
                        "ok": False,
                    },
                )
                failure += 1
                continue
            extracted = _extract_response(raw_response, response_path)
            ok = 200 <= status_code < 300
            context.session.execute(
                insert_sql,
                {
                    "idx": idx,
                    "req": json.dumps(req_payload, default=str),
                    "resp": json.dumps(extracted, default=str),
                    "sc": status_code,
                    "ok": ok,
                },
            )
            if ok:
                success += 1
            else:
                failure += 1
        return success, failure

    success, failure = asyncio.run(_process_all())
    return NodeV2Output(
        status="success",
        row_count=success + failure,
        payload={
            "endpoint": endpoint,
            "provider_code": provider_code,
            "output_table": output_table,
            "success_count": success,
            "failure_count": failure,
        },
    )


__all__ = ["name", "node_type", "run"]
