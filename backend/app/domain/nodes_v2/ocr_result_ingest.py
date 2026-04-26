"""OCR_RESULT_INGEST v2 노드 — Phase 7 Wave 1B.

외부 OCR 업체가 push 한 인식 결과를 sandbox table 로 적재.

기존 `OCR_TRANSFORM` 과의 차이:
  - OCR_TRANSFORM: *우리가* OCR provider API 호출 (image → text)
  - OCR_RESULT_INGEST: 외부 OCR 업체가 *결과를 push*. envelope 의 JSON 구조가
    표준 OCR 응답 (text, bbox, confidence) 이라 가정.

표준 OCR push payload (외부 업체에게 강제):
  {
    "ocr_provider_code": "vendor_a_ocr",
    "image_object_key": "...",
    "items": [
      {
        "text": "사과 1봉 5,000원",
        "confidence": 0.92,
        "bbox": [x, y, w, h],
        "candidate_product_name": "사과 1봉",
        "candidate_price": 5000
      },
      ...
    ]
  }

config:
  - `channel_code`: str (필수) — channel_kind=OCR_RESULT
  - `min_confidence`: float (default 0.0) — 이하 row 는 검수 큐로 분리
  - `output_table`: str (선택)
  - `dry_run`: bool
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

logger = logging.getLogger(__name__)

name = "OCR_RESULT_INGEST"
node_type = "OCR_RESULT_INGEST"

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


def _create_output_table(session: Any, output_table: str) -> None:
    schema, name_ = output_table.split(".", 1)
    session.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema}"."{name_}" ('
            f"    envelope_id BIGINT,"
            f"    item_index INTEGER,"
            f"    ocr_provider_code TEXT,"
            f"    image_object_key TEXT,"
            f"    text TEXT,"
            f"    confidence DOUBLE PRECISION,"
            f"    bbox JSONB,"
            f"    candidate_product_name TEXT,"
            f"    candidate_price NUMERIC,"
            f"    needs_review BOOLEAN,"
            f"    raw_item JSONB"
            f")"
        )
    )


def run(
    context: NodeV2Context, config: Mapping[str, Any]
) -> NodeV2Output:
    channel_code = config.get("channel_code")
    if not channel_code:
        raise NodeV2Error("OCR_RESULT_INGEST: channel_code required")
    min_confidence = float(config.get("min_confidence", 0.0))
    if not 0.0 <= min_confidence <= 1.0:
        raise NodeV2Error(f"min_confidence must be 0~1 (got {min_confidence})")
    max_envelopes = int(config.get("max_envelopes", 100))
    output_table_cfg = config.get("output_table")
    dry_run = bool(config.get("dry_run", False))

    output_table = _validate_target(
        output_table_cfg
        or f"wf.tmp_run_{context.pipeline_run_id}_{context.node_key}",
        allowed_schemas=_writable_schemas(context.domain_code),
    )

    session = context.session
    rows = session.execute(
        text(
            "SELECT envelope_id, payload_inline, payload_object_key "
            "FROM audit.inbound_event "
            "WHERE channel_code = :cc AND status = 'RECEIVED' "
            "ORDER BY received_at LIMIT :lim"
        ),
        {"cc": str(channel_code), "lim": max_envelopes},
    ).all()

    items_extracted: list[tuple[int, int, dict[str, Any]]] = []
    review_count = 0
    for r in rows:
        payload = r.payload_inline
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        ocr_provider = payload.get("ocr_provider_code", "")
        image_key = payload.get("image_object_key", "")
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            conf = float(item.get("confidence", 0.0))
            needs_review = conf < min_confidence
            if needs_review:
                review_count += 1
            normalized = {
                "ocr_provider_code": ocr_provider,
                "image_object_key": image_key,
                "text": item.get("text"),
                "confidence": conf,
                "bbox": item.get("bbox"),
                "candidate_product_name": item.get("candidate_product_name"),
                "candidate_price": item.get("candidate_price"),
                "needs_review": needs_review,
                "raw_item": item,
            }
            items_extracted.append((int(r.envelope_id), idx, normalized))

    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=len(items_extracted),
            payload={
                "envelopes_processed": len(rows),
                "output_table": output_table,
                "review_count": review_count,
                "channel_code": channel_code,
                "dry_run": True,
            },
        )

    _create_output_table(session, output_table)
    schema, name_ = output_table.split(".", 1)
    processed_envelope_ids: set[int] = set()
    for envelope_id, item_index, item in items_extracted:
        session.execute(
            text(
                f'INSERT INTO "{schema}"."{name_}" '
                "(envelope_id, item_index, ocr_provider_code, image_object_key, "
                " text, confidence, bbox, candidate_product_name, "
                " candidate_price, needs_review, raw_item) "
                "VALUES (:eid, :idx, :ocrp, :imgk, :txt, :conf, "
                "        CAST(:bbox AS JSONB), :pn, :prc, :nr, "
                "        CAST(:raw AS JSONB))"
            ),
            {
                "eid": envelope_id,
                "idx": item_index,
                "ocrp": item["ocr_provider_code"],
                "imgk": item["image_object_key"],
                "txt": item["text"],
                "conf": item["confidence"],
                "bbox": (
                    json.dumps(item["bbox"]) if item["bbox"] is not None else None
                ),
                "pn": item["candidate_product_name"],
                "prc": item["candidate_price"],
                "nr": item["needs_review"],
                "raw": json.dumps(item["raw_item"], ensure_ascii=False, default=str),
            },
        )
        processed_envelope_ids.add(envelope_id)

    if processed_envelope_ids:
        session.execute(
            text(
                "UPDATE audit.inbound_event SET status='DONE', processed_at=now() "
                "WHERE envelope_id = ANY(:ids)"
            ),
            {"ids": list(processed_envelope_ids)},
        )

    return NodeV2Output(
        status="success",
        row_count=len(items_extracted),
        payload={
            "envelopes_processed": len(processed_envelope_ids),
            "review_count": review_count,
            "output_table": output_table,
            "channel_code": channel_code,
        },
    )


__all__ = ["name", "node_type", "run"]
