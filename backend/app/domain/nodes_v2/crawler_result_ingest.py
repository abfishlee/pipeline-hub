"""CRAWLER_RESULT_INGEST v2 노드 — Phase 7 Wave 1B.

외부 크롤링 업체가 push 한 수집 결과를 sandbox table 로 적재.

기존 `CRAWL_FETCH` 와의 차이:
  - CRAWL_FETCH: 우리가 크롤링 작업을 *실행*
  - CRAWLER_RESULT_INGEST: 외부 업체의 결과 push 만 받음

표준 push payload:
  {
    "crawler_provider_code": "vendor_a_crawler",
    "source_site": "coupang.com",
    "crawled_at": "2026-04-26T10:30:00Z",
    "items": [
      {
        "product_name": "...",
        "price": 5000,
        "url": "...",
        "image_url": "...",
        "metadata": {...}
      }
    ]
  }
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

name = "CRAWLER_RESULT_INGEST"
node_type = "CRAWLER_RESULT_INGEST"

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
            f"    crawler_provider_code TEXT,"
            f"    source_site TEXT,"
            f"    crawled_at TIMESTAMPTZ,"
            f"    product_name TEXT,"
            f"    price NUMERIC,"
            f"    url TEXT,"
            f"    image_url TEXT,"
            f"    raw_item JSONB"
            f")"
        )
    )


def run(
    context: NodeV2Context, config: Mapping[str, Any]
) -> NodeV2Output:
    channel_code = config.get("channel_code")
    if not channel_code:
        raise NodeV2Error("CRAWLER_RESULT_INGEST: channel_code required")
    max_envelopes = int(config.get("max_envelopes", 100))
    output_table_cfg = config.get("output_table")
    dry_run = bool(config.get("dry_run", False))

    output_table = _validate_target(
        output_table_cfg
        or f"wf.tmp_run_{context.pipeline_run_id}_{context.node_key}",
        allowed_schemas=_writable_schemas(context.domain_code),
    )

    session = context.session
    envelopes = session.execute(
        text(
            "SELECT envelope_id, payload_inline "
            "FROM audit.inbound_event "
            "WHERE channel_code = :cc AND status = 'RECEIVED' "
            "ORDER BY received_at LIMIT :lim"
        ),
        {"cc": str(channel_code), "lim": max_envelopes},
    ).all()

    items_extracted: list[tuple[int, int, dict[str, Any]]] = []
    for env in envelopes:
        payload = env.payload_inline
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        provider = payload.get("crawler_provider_code", "")
        site = payload.get("source_site", "")
        crawled_at = payload.get("crawled_at")
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            normalized = {
                "crawler_provider_code": provider,
                "source_site": site,
                "crawled_at": crawled_at,
                "product_name": item.get("product_name"),
                "price": item.get("price"),
                "url": item.get("url"),
                "image_url": item.get("image_url"),
                "raw_item": item,
            }
            items_extracted.append((int(env.envelope_id), idx, normalized))

    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=len(items_extracted),
            payload={
                "envelopes_processed": len(envelopes),
                "output_table": output_table,
                "channel_code": channel_code,
                "dry_run": True,
            },
        )

    _create_output_table(session, output_table)
    schema, name_ = output_table.split(".", 1)
    processed_ids: set[int] = set()
    for env_id, idx, item in items_extracted:
        session.execute(
            text(
                f'INSERT INTO "{schema}"."{name_}" '
                "(envelope_id, item_index, crawler_provider_code, source_site, "
                " crawled_at, product_name, price, url, image_url, raw_item) "
                "VALUES (:eid, :idx, :prov, :site, "
                "        CAST(:cat AS TIMESTAMPTZ), :pn, :prc, :url, :iurl, "
                "        CAST(:raw AS JSONB))"
            ),
            {
                "eid": env_id,
                "idx": idx,
                "prov": item["crawler_provider_code"],
                "site": item["source_site"],
                "cat": item["crawled_at"],
                "pn": item["product_name"],
                "prc": item["price"],
                "url": item["url"],
                "iurl": item["image_url"],
                "raw": json.dumps(item["raw_item"], ensure_ascii=False, default=str),
            },
        )
        processed_ids.add(env_id)

    if processed_ids:
        session.execute(
            text(
                "UPDATE audit.inbound_event SET status='DONE', processed_at=now() "
                "WHERE envelope_id = ANY(:ids)"
            ),
            {"ids": list(processed_ids)},
        )

    return NodeV2Output(
        status="success",
        row_count=len(items_extracted),
        payload={
            "envelopes_processed": len(processed_ids),
            "output_table": output_table,
            "channel_code": channel_code,
        },
    )


__all__ = ["name", "node_type", "run"]
