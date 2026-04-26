"""wal2json (format-version=2) 메시지 → `raw.db_cdc_event` 변환 + slot stream 소비.

설계:
  - 파서 (`parse_wal2json_change`) 는 *순수 함수* — psycopg / replication slot 의존성 없이
    JSON 1건을 받아 `CdcChange` dataclass 리스트로 반환. 단위 테스트 용이.
  - 라이브 모드 (`stream_slot`) 는 `psycopg.connect(replication='database')` 로
    logical replication 시작. 환경 미가동 시 stream_slot 자체가 호출되지 않으므로
    파서/배치 INSERT 함수만으로도 회귀 테스트가 가능하다.

format-version=2 출력 예 (insert):
  {
    "action": "I",
    "schema": "public",
    "table": "products",
    "columns": [{"name":"id","type":"integer","value":1},
                {"name":"name","type":"text","value":"apple"}],
    "identity": [{"name":"id","type":"integer","value":1}]
  }
update / delete 도 동일한 모양 + before-image (`identity`) + after-image (`columns`).

본 모듈은 Phase 4.2.3 PoC — production 사용 전에 reorder buffer + transactional
boundary (BEGIN/COMMIT 레벨) 처리 보강 필요. ADR-0013 § 6 회수 조건 참조.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ctl import CdcSubscription
from app.models.raw import DbCdcEvent
from app.models.run import EventOutbox

ALLOWED_OPS: frozenset[str] = frozenset(("I", "U", "D"))


@dataclass(slots=True, frozen=True)
class CdcChange:
    """파서 출력 — 1개 row-level change."""

    op: str  # 'I' / 'U' / 'D'
    schema_name: str
    table_name: str
    pk: dict[str, Any]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    lsn: str


def _columns_to_dict(cols: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if cols is None:
        return out
    for c in cols:
        name = str(c.get("name") or "")
        if name:
            out[name] = c.get("value")
    return out


def parse_wal2json_change(message: str | Mapping[str, Any], *, lsn: str) -> CdcChange | None:
    """wal2json (format-version=2) 1개 change 메시지를 `CdcChange` 로 변환.

    BEGIN/COMMIT 같은 트랜잭션 boundary 메시지나 'M' 같은 metadata 는 None 반환.
    """
    if isinstance(message, str):
        try:
            payload: Mapping[str, Any] = json.loads(message)
        except json.JSONDecodeError:
            return None
    else:
        payload = message
    action = str(payload.get("action") or "").upper()
    if action == "C":
        # COMMIT — 트랜잭션 경계.
        return None
    if action == "B":
        # BEGIN — 트랜잭션 경계.
        return None
    if action not in ALLOWED_OPS:
        return None
    schema_name = str(payload.get("schema") or "")
    table_name = str(payload.get("table") or "")
    if not schema_name or not table_name:
        return None
    identity = payload.get("identity")
    columns = payload.get("columns")
    pk = _columns_to_dict(identity) if identity else _columns_to_dict(columns)
    after = _columns_to_dict(columns) if action in ("I", "U") else None
    before = _columns_to_dict(identity) if action in ("U", "D") else None
    return CdcChange(
        op=action,
        schema_name=schema_name,
        table_name=table_name,
        pk=pk,
        before=before,
        after=after,
        lsn=lsn,
    )


def parse_wal2json_batch(messages: Iterable[tuple[str, str | Mapping[str, Any]]]) -> list[CdcChange]:
    """배치 파서. `messages` = iterable of (lsn, message) 튜플."""
    out: list[CdcChange] = []
    for lsn, msg in messages:
        change = parse_wal2json_change(msg, lsn=lsn)
        if change is not None:
            out.append(change)
    return out


def persist_cdc_changes(
    session: Session,
    *,
    source_id: int,
    changes: Iterable[CdcChange],
    enqueue_outbox: bool = True,
) -> int:
    """change 배치를 raw.db_cdc_event INSERT + outbox `cdc.event` 발행.

    `(source_id, lsn)` UNIQUE 라 같은 LSN 재처리 시 ON CONFLICT DO NOTHING. 반환값은
    *실제로 새로 INSERT 된* row 수.
    """
    inserted = 0
    last_lsn: str | None = None
    for ch in changes:
        last_lsn = ch.lsn
        stmt = (
            pg_insert(DbCdcEvent)
            .values(
                source_id=source_id,
                schema_name=ch.schema_name,
                table_name=ch.table_name,
                op=ch.op,
                pk_json=ch.pk,
                before_json=ch.before,
                after_json=ch.after,
                lsn=ch.lsn,
            )
            .on_conflict_do_nothing(index_elements=["source_id", "lsn"])
            .returning(DbCdcEvent.event_id)
        )
        result = session.execute(stmt)
        new_event_id = result.scalar_one_or_none()
        if new_event_id is None:
            continue  # 중복 — skip outbox.
        inserted += 1
        if enqueue_outbox:
            session.add(
                EventOutbox(
                    aggregate_type="db_cdc_event",
                    aggregate_id=str(new_event_id),
                    event_type="cdc.event",
                    payload_json={
                        "source_id": source_id,
                        "schema_name": ch.schema_name,
                        "table_name": ch.table_name,
                        "op": ch.op,
                        "pk": ch.pk,
                        "lsn": ch.lsn,
                    },
                )
            )

    # subscription.last_committed_lsn 갱신.
    if last_lsn is not None:
        sub = session.execute(
            select(CdcSubscription).where(CdcSubscription.source_id == source_id)
        ).scalar_one_or_none()
        if sub is not None:
            sub.last_committed_lsn = last_lsn
            sub.last_polled_at = datetime.now(UTC)
    return inserted


def get_replication_lag_bytes(session: Session, *, slot_name: str) -> int | None:
    """pg_replication_slots 의 `pg_current_wal_lsn() - confirmed_flush_lsn` (bytes).

    slot 이 존재하지 않으면 None.
    """
    row = session.execute(
        text(
            "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn) AS lag "
            "FROM pg_replication_slots WHERE slot_name = :s"
        ),
        {"s": slot_name},
    ).first()
    if row is None or row.lag is None:
        return None
    return int(row.lag)


def update_lag_metric(
    session: Session,
    *,
    source_id: int,
    threshold_bytes: int = 10 * 1024 * 1024,
) -> int | None:
    """slot lag 측정 + ctl.cdc_subscription 갱신 + 임계 초과 시 outbox NOTIFY.

    반환값은 측정된 lag_bytes (None 이면 slot 미가동).
    """
    sub = session.execute(
        select(CdcSubscription).where(CdcSubscription.source_id == source_id)
    ).scalar_one_or_none()
    if sub is None:
        return None
    lag = get_replication_lag_bytes(session, slot_name=sub.slot_name)
    sub.last_lag_bytes = lag
    sub.last_polled_at = datetime.now(UTC)
    if lag is not None and lag > threshold_bytes:
        session.add(
            EventOutbox(
                aggregate_type="cdc_subscription",
                aggregate_id=str(sub.subscription_id),
                event_type="notify.requested",
                payload_json={
                    "channel": "slack",
                    "target": "",
                    "level": "WARN",
                    "subject": f"CDC lag 초과 — slot {sub.slot_name}",
                    "body": (
                        f"slot={sub.slot_name} lag={lag}B threshold={threshold_bytes}B "
                        f"(source_id={source_id})"
                    ),
                    "subscription_id": sub.subscription_id,
                    "source_id": source_id,
                    "lag_bytes": lag,
                    "threshold_bytes": threshold_bytes,
                },
            )
        )
    return lag


def stream_slot(  # pragma: no cover — 라이브 환경 의존, 회귀 테스트 회피.
    *,
    dsn: str,
    slot_name: str,
    publication_name: str | None = None,
    poll_timeout_sec: float = 10.0,
) -> Iterator[tuple[str, str]]:
    """logical replication slot 에서 (lsn, raw_message) 를 무한 반복 yield.

    psycopg 3 의 replication API 를 사용. 실제 데몬은 worker actor 가 호출.
    """
    import psycopg  # local import — 테스트 환경에서 dialect 차이 회피.

    options: dict[str, str] = {"format-version": "2"}
    if publication_name:
        options["add-tables"] = f"{publication_name}.*"

    with psycopg.connect(dsn, autocommit=True) as conn:
        cur: Any = conn.cursor()
        opts_sql = ", ".join(f"'{k}' '{v}'" for k, v in options.items())
        cur.execute(f"START_REPLICATION SLOT {slot_name} LOGICAL 0/0 ({opts_sql})")
        while True:
            msg = cur.read_message(timeout=poll_timeout_sec)
            if msg is None:
                continue
            yield (str(msg.data_start), msg.payload.decode("utf-8"))


__all__ = [
    "ALLOWED_OPS",
    "CdcChange",
    "get_replication_lag_bytes",
    "parse_wal2json_batch",
    "parse_wal2json_change",
    "persist_cdc_changes",
    "stream_slot",
    "update_lag_metric",
]
