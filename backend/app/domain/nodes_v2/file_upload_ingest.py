"""FILE_UPLOAD_INGEST v2 노드 — Phase 7 Wave 1A.

소상공인 / 외부 사용자가 multipart 또는 raw upload 한 파일 (CSV / JSON / Excel)
을 sandbox table 로 적재.

WEBHOOK_INGEST 와의 차이:
  - channel_kind 가 FILE_UPLOAD 인 채널만 대상
  - payload 는 보통 binary (CSV / xlsx) — object storage 만 사용 (inline X)
  - row 분해 = CSV/Excel 파서 (Wave 1B 에서 본격) — 현재는 JSON 만 처리

config:
  - `channel_code`: str (필수)
  - `envelope_id`: int (선택)
  - `max_envelopes`: int (default 50)
  - `output_table`: str (선택)
  - `parse_format`: "auto" | "json" | "csv" (default "auto" — content_type 으로 결정)
  - `dry_run`: bool

가드 + 에러 정책 모두 WEBHOOK_INGEST 와 동일.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

logger = logging.getLogger(__name__)

name = "FILE_UPLOAD_INGEST"
node_type = "FILE_UPLOAD_INGEST"

_SAFE_FQDN_RE = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$"
)


def _writable_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"wf", "stg", f"{domain_code.lower()}_stg"})


def _validate_target(table: str, *, allowed_schemas: frozenset[str]) -> str:
    if not _SAFE_FQDN_RE.match(table):
        raise NodeV2Error(f"output_table must match schema.table (got {table!r})")
    schema = table.split(".", 1)[0]
    if schema.lower() not in allowed_schemas:
        raise NodeV2Error(
            f"output_table schema {schema!r} not allowed (allowed: {sorted(allowed_schemas)})"
        )
    return table


def _detect_format(content_type: str, override: str) -> str:
    if override != "auto":
        return override
    if "json" in content_type:
        return "json"
    if "csv" in content_type:
        return "csv"
    return "json"  # 기본값


def _parse_payload(
    *, fmt: str, payload_bytes: bytes
) -> list[dict[str, Any]]:
    if fmt == "json":
        try:
            text_str = payload_bytes.decode("utf-8")
            obj = json.loads(text_str)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        if isinstance(obj, list):
            return [o if isinstance(o, dict) else {"value": o} for o in obj]
        if isinstance(obj, dict):
            return [obj]
        return []
    if fmt == "csv":
        try:
            text_str = payload_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text_str = payload_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text_str))
        return [dict(row) for row in reader]
    return []


def _load_envelopes(
    session: Any,
    *,
    channel_code: str,
    envelope_id: int | None,
    max_envelopes: int,
) -> list[dict[str, Any]]:
    if envelope_id is not None:
        rows = session.execute(
            text(
                "SELECT envelope_id, content_type, payload_inline, "
                "       payload_object_key, status "
                "FROM audit.inbound_event "
                "WHERE channel_code = :cc AND envelope_id = :eid"
            ),
            {"cc": channel_code, "eid": envelope_id},
        ).all()
    else:
        rows = session.execute(
            text(
                "SELECT envelope_id, content_type, payload_inline, "
                "       payload_object_key, status "
                "FROM audit.inbound_event "
                "WHERE channel_code = :cc AND status = 'RECEIVED' "
                "ORDER BY received_at LIMIT :lim"
            ),
            {"cc": channel_code, "lim": max_envelopes},
        ).all()
    return [
        {
            "envelope_id": int(r.envelope_id),
            "content_type": str(r.content_type),
            "payload_inline": r.payload_inline,
            "payload_object_key": (
                str(r.payload_object_key) if r.payload_object_key else None
            ),
            "status": str(r.status),
        }
        for r in rows
    ]


def _create_output_table(session: Any, output_table: str) -> None:
    schema, name_ = output_table.split(".", 1)
    session.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}"."{name_}" ('
            f"    envelope_id BIGINT,"
            f"    row_index INTEGER,"
            f"    payload JSONB"
            f")"
        )
    )


def run(
    context: NodeV2Context, config: Mapping[str, Any]
) -> NodeV2Output:
    channel_code = config.get("channel_code")
    if not channel_code:
        raise NodeV2Error("FILE_UPLOAD_INGEST: channel_code required")
    envelope_id = config.get("envelope_id")
    max_envelopes = int(config.get("max_envelopes", 50))
    parse_format = config.get("parse_format", "auto")
    if parse_format not in ("auto", "json", "csv"):
        raise NodeV2Error(f"unknown parse_format: {parse_format}")
    output_table_cfg = config.get("output_table")
    dry_run = bool(config.get("dry_run", False))

    output_table = _validate_target(
        output_table_cfg
        or f"wf.tmp_run_{context.pipeline_run_id}_{context.node_key}",
        allowed_schemas=_writable_schemas(context.domain_code),
    )

    session = context.session
    envelopes = _load_envelopes(
        session,
        channel_code=str(channel_code),
        envelope_id=int(envelope_id) if envelope_id is not None else None,
        max_envelopes=max_envelopes,
    )
    if not envelopes:
        return NodeV2Output(
            status="success",
            row_count=0,
            payload={
                "envelopes_processed": 0,
                "output_table": output_table,
                "channel_code": channel_code,
                "note": "no RECEIVED envelopes",
            },
        )

    # 각 envelope payload 파싱 (인라인 JSON 만 — object storage fetch 는 Wave 1B)
    parsed: list[tuple[int, list[dict[str, Any]]]] = []
    for env in envelopes:
        # _detect_format 은 향후 binary payload (object storage) 처리 시 활용.
        _ = _detect_format(env["content_type"], parse_format)
        if env["payload_inline"]:
            inline = env["payload_inline"]
            if isinstance(inline, dict) and "data" in inline and len(inline) == 1:
                inline = inline["data"]
            payload_bytes = json.dumps(inline, ensure_ascii=False).encode("utf-8")
            rows = _parse_payload(fmt="json", payload_bytes=payload_bytes)
        else:
            # object storage fetch — Phase 7 Wave 1B 에서 보강
            logger.warning(
                "file_upload_ingest.object_storage_fetch_pending",
                extra={"envelope_id": env["envelope_id"]},
            )
            rows = []
        parsed.append((env["envelope_id"], rows))

    total_rows = sum(len(rows) for _, rows in parsed)

    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=total_rows,
            payload={
                "envelopes_processed": len(envelopes),
                "output_table": output_table,
                "channel_code": channel_code,
                "sample_rows": [
                    rows[0] for _, rows in parsed[:5] if rows
                ][:5],
                "dry_run": True,
            },
        )

    _create_output_table(session, output_table)
    schema, name_ = output_table.split(".", 1)
    processed: list[int] = []
    for envelope_id_, rows in parsed:
        if not rows:
            continue
        for idx, row in enumerate(rows):
            session.execute(
                text(
                    f'INSERT INTO "{schema}"."{name_}" '
                    "(envelope_id, row_index, payload) "
                    "VALUES (:eid, :idx, CAST(:p AS JSONB))"
                ),
                {
                    "eid": envelope_id_,
                    "idx": idx,
                    "p": json.dumps(row, ensure_ascii=False, default=str),
                },
            )
        processed.append(envelope_id_)

    if processed:
        session.execute(
            text(
                "UPDATE audit.inbound_event SET status='DONE', processed_at=now() "
                "WHERE envelope_id = ANY(:ids)"
            ),
            {"ids": processed},
        )

    return NodeV2Output(
        status="success",
        row_count=total_rows,
        payload={
            "envelopes_processed": len(processed),
            "output_table": output_table,
            "channel_code": channel_code,
        },
    )


__all__ = ["name", "node_type", "run"]
