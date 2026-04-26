"""DB_INCREMENTAL_FETCH v2 노드 — Phase 7 Wave 1A.

기존 `app.domain.db_incremental.pull_incremental` 을 ETL Canvas 노드로 노출.
ctl.data_source 에 등록된 source_type='DB' source 의 watermark 기반 incremental
fetch.

config:
  - `source_code`: str (필수) — `ctl.data_source.source_code`
  - `batch_size`: int (default 1000)
  - `output_table`: str (선택) — sandbox FQDN. 미지정 시 wf.tmp_run_*
  - `dry_run`: bool — True 면 watermark 만 확인 (실 fetch X)

가드:
  - source_type=DB 만 허용
  - is_active=true 만 허용
  - dry_run 시 connector 호출 없음 (caller 가 dry-run 보장 시)

Wave 1A 한계:
  - pull_incremental 은 raw_object 에 저장. 본 노드는 그 결과 raw_object_id 들을
    reference 하는 sandbox view 만 생성. row 분해는 후속 MAP_FIELDS 노드 책임.
  - 향후 schema 추론 + 직접 sandbox 적재는 Phase 7 Wave 1B 또는 Wave 4.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select, text

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

logger = logging.getLogger(__name__)

name = "DB_INCREMENTAL_FETCH"
node_type = "DB_INCREMENTAL_FETCH"

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
            f"    raw_object_id BIGINT,"
            f"    canonical_hash TEXT,"
            f"    cursor_value TEXT,"
            f"    payload JSONB"
            f")"
        )
    )


def run(
    context: NodeV2Context, config: Mapping[str, Any]
) -> NodeV2Output:
    source_code = config.get("source_code")
    if not source_code:
        raise NodeV2Error("DB_INCREMENTAL_FETCH: source_code required")
    batch_size = int(config.get("batch_size", 1000))
    if not 1 <= batch_size <= 100_000:
        raise NodeV2Error(f"batch_size out of bounds: {batch_size}")
    output_table_cfg = config.get("output_table")
    dry_run = bool(config.get("dry_run", False))

    output_table = _validate_target(
        output_table_cfg
        or f"wf.tmp_run_{context.pipeline_run_id}_{context.node_key}",
        allowed_schemas=_writable_schemas(context.domain_code),
    )

    session = context.session

    # ── source 메타 검증 (dry_run 도 메타 검증은 함) ───────────────────
    from app.models.ctl import DataSource

    ds = session.execute(
        select(DataSource).where(DataSource.source_code == source_code)
    ).scalar_one_or_none()
    if ds is None:
        raise NodeV2Error(f"data_source not found: {source_code}")
    if ds.source_type != "DB":
        raise NodeV2Error(
            f"source {source_code} is type={ds.source_type!r}, "
            "DB_INCREMENTAL_FETCH requires type=DB"
        )
    if not ds.is_active:
        raise NodeV2Error(f"source {source_code} is inactive")

    last_cursor = (ds.watermark or {}).get("last_cursor")

    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=0,
            payload={
                "source_code": source_code,
                "output_table": output_table,
                "last_cursor": last_cursor,
                "batch_size": batch_size,
                "dry_run": True,
                "note": "DB connector not invoked",
            },
        )

    # ── 실 fetch (raw_object 적재 + watermark 전진) ───────────────────
    from app.domain.db_incremental import pull_incremental

    outcome = pull_incremental(
        session,
        source_code=str(source_code),
        batch_size=batch_size,
    )

    # 새로 적재된 raw_object 들을 sandbox view 로 노출 (MAP_FIELDS 가 받음).
    # outcome.last_run_at 이후 source_id 의 raw_object 가 본 run 의 산출물.
    _create_output_table(session, output_table)
    schema, name_ = output_table.split(".", 1)
    if outcome.inserted_count > 0:
        session.execute(
            text(
                f'INSERT INTO "{schema}"."{name_}" '
                "(raw_object_id, canonical_hash, cursor_value, payload) "
                "SELECT raw_object_id, canonical_hash, "
                "       source_meta->>'cursor_value', payload "
                "FROM raw.raw_object "
                "WHERE source_id = :sid AND fetched_at >= :since "
                "ORDER BY raw_object_id"
            ),
            {"sid": ds.source_id, "since": outcome.last_run_at},
        )

    return NodeV2Output(
        status="success",
        row_count=outcome.inserted_count,
        payload={
            "source_code": source_code,
            "output_table": output_table,
            "pulled_count": outcome.pulled_count,
            "inserted_count": outcome.inserted_count,
            "deduped_count": outcome.deduped_count,
            "last_cursor": str(outcome.last_cursor) if outcome.last_cursor else None,
        },
    )


__all__ = ["name", "node_type", "run"]
