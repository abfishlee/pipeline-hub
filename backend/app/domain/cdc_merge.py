"""Snapshot + CDC 머지 (Phase 4.2.3).

원리:
  - `raw.db_snapshot` 가 mode='SNAPSHOT' 으로 적재될 때 해당 시점의 LSN 을
    `ctl.cdc_subscription.snapshot_lsn` 에 기록.
  - mart 마스터 upsert 시 *snapshot 이후 LSN* 의 CDC 이벤트만 적용 — snapshot 이
    이미 반영한 row 를 CDC 가 다시 덮어쓰지 않도록.
  - business_key 기반 upsert — pk_json 의 컬럼이 mart 마스터의 natural key 와 매핑.

PoC 단계 가정:
  - snapshot_lsn 이 채워져 있지 않으면 모든 CDC 이벤트가 적용 가능 (보수적 fallback).
  - LSN 비교는 PG 의 `pg_lsn` 타입 캐스팅 후 `>`. 본 모듈은 raw 텍스트 비교 대신 PG
    함수를 활용한 helper 만 제공.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.ctl import CdcSubscription
from app.models.raw import DbCdcEvent


@dataclass(slots=True, frozen=True)
class MergeStats:
    candidates: int
    applied: int
    skipped_pre_snapshot: int


def record_snapshot_lsn(session: Session, *, source_id: int, lsn: str) -> None:
    """snapshot 작업이 끝난 시점의 LSN 을 기록 — 이후 CDC 머지 시 기준점."""
    sub = session.execute(
        select(CdcSubscription).where(CdcSubscription.source_id == source_id)
    ).scalar_one_or_none()
    if sub is None:
        return
    sub.snapshot_lsn = lsn


def _lsn_strictly_after(session: Session, *, candidate: str, baseline: str | None) -> bool:
    """candidate LSN > baseline LSN — PG 의 pg_lsn 캐스팅으로 비교.

    baseline 이 None 이면 항상 True (보수적 fallback).
    """
    if baseline is None:
        return True
    row = session.execute(
        text("SELECT (:c)::pg_lsn > (:b)::pg_lsn AS gt"),
        {"c": candidate, "b": baseline},
    ).first()
    return bool(row and row.gt)


def applicable_changes_for_source(
    session: Session,
    *,
    source_id: int,
    schema_name: str | None = None,
    table_name: str | None = None,
    limit: int = 1000,
) -> tuple[list[DbCdcEvent], MergeStats]:
    """source_id 의 적재된 raw.db_cdc_event 중 *snapshot 이후* 의 것만 반환.

    호출자가 받은 리스트를 mart 도메인 upsert 에 직접 전달. PoC 단계라 단순한
    chronological order — 트랜잭션 boundary 는 무시 (production 에서 reorder buffer
    필요).
    """
    sub = session.execute(
        select(CdcSubscription).where(CdcSubscription.source_id == source_id)
    ).scalar_one_or_none()
    snapshot_lsn = sub.snapshot_lsn if sub else None

    q = (
        select(DbCdcEvent)
        .where(DbCdcEvent.source_id == source_id)
        .order_by(DbCdcEvent.event_id)
        .limit(limit)
    )
    if schema_name:
        q = q.where(DbCdcEvent.schema_name == schema_name)
    if table_name:
        q = q.where(DbCdcEvent.table_name == table_name)
    candidates = list(session.execute(q).scalars().all())

    applied: list[DbCdcEvent] = []
    skipped = 0
    for ev in candidates:
        if _lsn_strictly_after(session, candidate=ev.lsn, baseline=snapshot_lsn):
            applied.append(ev)
        else:
            skipped += 1
    return applied, MergeStats(
        candidates=len(candidates), applied=len(applied), skipped_pre_snapshot=skipped
    )


def upsert_from_change(
    session: Session,
    *,
    table_qualified: str,
    business_key_columns: list[str],
    change: DbCdcEvent | Mapping[str, Any],
) -> str:
    """단일 CDC 이벤트를 mart upsert. PoC — INSERT ... ON CONFLICT DO UPDATE SET.

    `change.op == 'D'` 면 DELETE. 'I'/'U' 는 after_json 으로 upsert.
    business_key_columns 는 ON CONFLICT 의 unique constraint 컬럼. 호출자가 mart
    마스터 테이블의 unique key 매핑을 알고 있어야 함.
    """
    if isinstance(change, DbCdcEvent):
        op_code = change.op
        after = dict(change.after_json or {})
        pk = dict(change.pk_json or {})
    else:
        op_code = str(change.get("op") or "")
        after = dict(change.get("after_json") or change.get("after") or {})
        pk = dict(change.get("pk_json") or change.get("pk") or {})

    if op_code == "D":
        if not pk:
            return "skipped_no_pk"
        clauses = " AND ".join(f"{k} = :pk_{k}" for k in pk)
        params = {f"pk_{k}": v for k, v in pk.items()}
        session.execute(text(f"DELETE FROM {table_qualified} WHERE {clauses}"), params)
        return "deleted"

    if not after:
        return "skipped_empty"

    cols = list(after.keys())
    col_list = ", ".join(cols)
    val_list = ", ".join(f":{c}" for c in cols)
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in business_key_columns)
    conflict_cols = ", ".join(business_key_columns)
    sql = (
        f"INSERT INTO {table_qualified} ({col_list}) VALUES ({val_list}) "
        f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
    )
    session.execute(text(sql), after)
    return "upserted"


__all__ = [
    "MergeStats",
    "applicable_changes_for_source",
    "record_snapshot_lsn",
    "upsert_from_change",
]
