"""SOURCE_API 노드 — `raw.raw_object` 에서 최근 row N 건을 읽어 downstream 으로 전달.

config:
  - `source_code`: ctl.data_source.source_code (필수)
  - `limit`: 1~10000 (기본 100)
  - `since_partition_date`: ISO `YYYY-MM-DD` (선택)
  - `include_payload`: bool (기본 True — 큰 payload 는 false 로 메타만)

upstream 이 없는 entry 노드 용도. 다른 노드의 upstream_outputs 입력은 사용하지
않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as DateType
from typing import Any

from sqlalchemy import select

from app.domain.nodes import NodeContext, NodeError, NodeOutput
from app.models.ctl import DataSource
from app.models.raw import RawObject

name = "SOURCE_API"


def _parse_date(value: Any) -> DateType | None:
    if value is None:
        return None
    if isinstance(value, DateType):
        return value
    try:
        return DateType.fromisoformat(str(value))
    except ValueError as exc:
        raise NodeError(f"invalid since_partition_date: {value!r} ({exc})") from exc


def run(context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
    source_code = str(config.get("source_code") or "").strip()
    if not source_code:
        raise NodeError("SOURCE_API requires `source_code`")

    limit = int(config.get("limit") or 100)
    if limit <= 0 or limit > 10_000:
        raise NodeError(f"limit must be 1~10000 (got {limit})")
    since = _parse_date(config.get("since_partition_date"))
    include_payload = bool(config.get("include_payload", True))

    src = context.session.execute(
        select(DataSource).where(DataSource.source_code == source_code)
    ).scalar_one_or_none()
    if src is None:
        raise NodeError(f"source_code not found: {source_code}")

    stmt = (
        select(RawObject)
        .where(RawObject.source_id == src.source_id)
        .order_by(RawObject.received_at.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(RawObject.partition_date >= since)

    rows: list[dict[str, Any]] = []
    for row in context.session.execute(stmt).scalars().all():
        item: dict[str, Any] = {
            "raw_object_id": row.raw_object_id,
            "partition_date": row.partition_date.isoformat(),
            "object_type": row.object_type,
            "content_hash": row.content_hash,
            "received_at": row.received_at.isoformat() if row.received_at else None,
        }
        if include_payload and row.payload_json is not None:
            item["payload_json"] = row.payload_json
        rows.append(item)

    return NodeOutput(
        status="success",
        row_count=len(rows),
        payload={
            "source_code": source_code,
            "rows": rows,
        },
    )


__all__ = ["name", "run"]
