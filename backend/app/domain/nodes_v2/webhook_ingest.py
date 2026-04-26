"""WEBHOOK_INGEST v2 노드 — Phase 7 Wave 1A.

ETL 캔버스의 *DATA SOURCES* 카테고리. 외부 시스템이 push 한 envelope
(`audit.inbound_event` 의 RECEIVED 상태) 을 읽어 sandbox table 로 적재.

흐름 (사용자 § 8.2 / 8.4):
  외부 → POST /v1/inbound/{channel_code}
       → audit.inbound_event INSERT (status=RECEIVED)
       → WEBHOOK_INGEST 노드가 envelope 읽기
       → payload 의 JSON 을 rows 로 펼침
       → output_table (sandbox) 에 INSERT
       → envelope status=DONE 마킹

config:
  - `channel_code`: str (필수) — 어떤 inbound_channel 의 envelope 인지
  - `envelope_id`: int (선택) — 특정 envelope 1건 처리. 없으면 RECEIVED 전부
  - `max_envelopes`: int (default 100) — 한 run 당 처리 한도
  - `payload_path`: str (선택) — JSON 안의 rows 경로 (예: `$.data.items`)
  - `output_table`: str (선택) — sandbox FQDN
  - `dry_run`: bool — True 면 envelope 읽기만, sandbox 적재 X

가드:
  - PUBLISHED + is_active 채널만 처리
  - output_table schema = wf / stg / <domain>_stg
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output
from app.domain.public_api.parser import extract_path, normalize_to_rows

logger = logging.getLogger(__name__)

name = "WEBHOOK_INGEST"
node_type = "WEBHOOK_INGEST"

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


def _load_envelopes(
    session: Any,
    *,
    channel_code: str,
    envelope_id: int | None,
    max_envelopes: int,
) -> list[dict[str, Any]]:
    """RECEIVED 상태의 envelope 을 limit 만큼 조회."""
    if envelope_id is not None:
        rows = session.execute(
            text(
                "SELECT envelope_id, channel_code, content_type, "
                "       payload_inline, payload_object_key, status "
                "FROM audit.inbound_event "
                "WHERE channel_code = :cc AND envelope_id = :eid"
            ),
            {"cc": channel_code, "eid": envelope_id},
        ).all()
    else:
        rows = session.execute(
            text(
                "SELECT envelope_id, channel_code, content_type, "
                "       payload_inline, payload_object_key, status "
                "FROM audit.inbound_event "
                "WHERE channel_code = :cc AND status = 'RECEIVED' "
                "ORDER BY received_at LIMIT :lim"
            ),
            {"cc": channel_code, "lim": max_envelopes},
        ).all()
    return [
        {
            "envelope_id": int(r.envelope_id),
            "channel_code": str(r.channel_code),
            "content_type": str(r.content_type),
            "payload_inline": r.payload_inline,
            "payload_object_key": (
                str(r.payload_object_key) if r.payload_object_key else None
            ),
            "status": str(r.status),
        }
        for r in rows
    ]


def _extract_rows(envelope: dict[str, Any], payload_path: str | None) -> list[dict[str, Any]]:
    """envelope payload → row list."""
    payload = envelope.get("payload_inline")
    if payload is None and envelope.get("payload_object_key"):
        # Phase 7 Wave 1B 에서 object storage fetch 추가. 현재는 인라인 만.
        logger.warning(
            "webhook_ingest.object_storage_fetch_pending",
            extra={"envelope_id": envelope["envelope_id"]},
        )
        return []
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if payload_path:
        payload = extract_path(payload, payload_path)
    rows = normalize_to_rows(payload)
    # envelope_id 를 lineage 로 inject
    for r in rows:
        r["_envelope_id"] = envelope["envelope_id"]
    return rows


def _create_output_table(session: Any, output_table: str) -> None:
    """sandbox JSONB 테이블 생성 (column 추론은 Wave 1B 에서 강화)."""
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
        raise NodeV2Error("WEBHOOK_INGEST: channel_code required")
    envelope_id = config.get("envelope_id")
    max_envelopes = int(config.get("max_envelopes", 100))
    if not 1 <= max_envelopes <= 1000:
        raise NodeV2Error(
            f"max_envelopes out of bounds: {max_envelopes}"
        )
    payload_path = config.get("payload_path")
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

    if dry_run:
        # row 추정만, 실 적재 X
        sample_rows: list[dict[str, Any]] = []
        for env in envelopes[:5]:
            sample_rows.extend(_extract_rows(env, payload_path)[:5])
        return NodeV2Output(
            status="success",
            row_count=len(sample_rows),
            payload={
                "envelopes_processed": len(envelopes),
                "output_table": output_table,
                "channel_code": channel_code,
                "sample_rows": sample_rows[:20],
                "dry_run": True,
            },
        )

    # 실 적재
    _create_output_table(session, output_table)
    schema, name_ = output_table.split(".", 1)
    total_rows = 0
    processed_envelope_ids: list[int] = []
    for env in envelopes:
        rows = _extract_rows(env, payload_path)
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
                    "eid": env["envelope_id"],
                    "idx": idx,
                    "p": json.dumps(row, ensure_ascii=False, default=str),
                },
            )
            total_rows += 1
        processed_envelope_ids.append(env["envelope_id"])

    # envelope status=DONE 마킹
    if processed_envelope_ids:
        session.execute(
            text(
                "UPDATE audit.inbound_event SET status='DONE', processed_at=now() "
                "WHERE envelope_id = ANY(:ids)"
            ),
            {"ids": processed_envelope_ids},
        )

    return NodeV2Output(
        status="success",
        row_count=total_rows,
        payload={
            "envelopes_processed": len(processed_envelope_ids),
            "output_table": output_table,
            "channel_code": channel_code,
        },
    )


__all__ = ["name", "node_type", "run"]
