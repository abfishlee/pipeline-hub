"""DB-to-DB 증분 수집 도메인 (Phase 2.2.7).

흐름:
  1. `ctl.data_source` 에서 source_code 조회 → `config_json` 으로 SourceDbConfig 복원
     + `watermark.last_cursor` 읽기.
  2. `SourceDbConnector.fetch_incremental(cursor_value, batch_size)` 호출.
  3. 단일 트랜잭션:
     - `run.ingest_job` 1건 (job_type=SCHEDULED, status=SUCCESS)
     - row 별 `raw.raw_object` (object_type=DB_ROW, payload_json=row,
        content_hash=sha256(canonical), idempotency_key=`<table>:<cursor>`)
     - `raw.content_hash_index` (이미 봤으면 race 충돌 → 해당 row 만 skip)
     - `run.event_outbox` (`ingest.api.received`) per row
     - `ctl.data_source.watermark` 업데이트 (last_cursor / last_run_at / last_count).
  4. metrics 갱신 + outcome 반환.

Worker 가 sync session 으로 호출. 호출자가 commit 책임 (consume_idempotent 가
트랜잭션 닫음).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as DateType
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import metrics
from app.integrations.sourcedb import (
    SourceDbBatch,
    SourceDbConfig,
    SourceDbConnector,
    SourceDbError,
    SqlAlchemySourceDb,
)
from app.models.ctl import DataSource
from app.models.raw import ContentHashIndex, RawObject
from app.models.run import EventOutbox, IngestJob


@dataclass(slots=True, frozen=True)
class DbIncrementalOutcome:
    source_code: str
    pulled_count: int
    inserted_count: int
    deduped_count: int
    last_cursor: Any
    last_run_at: datetime


def _canonical_hash(row: dict[str, Any]) -> str:
    """결정적 SHA-256 — JSON 정렬 후 hex digest."""
    payload = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _coerce_cursor_str(value: Any) -> str:
    """cursor_value 를 idempotency_key / 로그용 문자열로 안전 변환."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _build_config(config_json: dict[str, Any]) -> SourceDbConfig:
    """ctl.data_source.config_json → SourceDbConfig.

    필수 키: driver/host/port/database/table/cursor_column/user.
    """
    required = ("driver", "host", "port", "database", "table", "cursor_column", "user")
    missing = [k for k in required if k not in config_json]
    if missing:
        raise SourceDbError(f"data_source.config_json missing keys: {missing}")
    return SourceDbConfig(
        driver=config_json["driver"],
        host=str(config_json["host"]),
        port=int(config_json["port"]),
        database=str(config_json["database"]),
        schema=config_json.get("schema"),
        table=str(config_json["table"]),
        cursor_column=str(config_json["cursor_column"]),
        user=str(config_json["user"]),
        password=str(config_json.get("password", "")),
        select_columns=tuple(config_json.get("select_columns") or ["*"]),
        extra_where=config_json.get("extra_where"),
    )


def pull_incremental(
    session: Session,
    *,
    source_code: str,
    batch_size: int = 1000,
    connector_factory: Any = None,
) -> DbIncrementalOutcome:
    """1회 incremental fetch + raw_object 적재 + watermark 전진.

    `connector_factory(config) -> SourceDbConnector` 를 주입하면 테스트 stub 사용 가능.
    None 이면 SqlAlchemySourceDb.
    """
    ds = session.execute(
        select(DataSource).where(DataSource.source_code == source_code)
    ).scalar_one_or_none()
    if ds is None:
        raise SourceDbError(f"data_source not found: {source_code}")
    if ds.source_type != "DB":
        raise SourceDbError(f"source {source_code} is not type=DB (got {ds.source_type})")
    if not ds.is_active:
        raise SourceDbError(f"source {source_code} is inactive")

    config = _build_config(ds.config_json or {})
    last_cursor = (ds.watermark or {}).get("last_cursor")
    today: DateType = datetime.now(UTC).date()

    connector: SourceDbConnector
    if connector_factory is not None:
        connector = connector_factory(config)
    else:
        connector = SqlAlchemySourceDb(config)

    try:
        batch: SourceDbBatch = connector.fetch_incremental(
            cursor_value=last_cursor, batch_size=batch_size
        )
    except SourceDbError:
        metrics.db_incremental_pulled_total.labels(source_code=source_code, outcome="error").inc()
        connector.close()
        raise

    pulled = len(batch.rows)
    if pulled == 0:
        metrics.db_incremental_pulled_total.labels(source_code=source_code, outcome="empty").inc()
        ds.watermark = {
            **(ds.watermark or {}),
            "last_run_at": datetime.now(UTC).isoformat(),
            "last_count": 0,
        }
        connector.close()
        return DbIncrementalOutcome(
            source_code=source_code,
            pulled_count=0,
            inserted_count=0,
            deduped_count=0,
            last_cursor=last_cursor,
            last_run_at=datetime.now(UTC),
        )

    # ingest_job 1건 — 파일/이미지 ingest 와 같은 추적성.
    job = IngestJob(
        source_id=ds.source_id,
        job_type="SCHEDULED",
        status="SUCCESS",
        parameters={"batch_size": batch_size, "cursor_start": _coerce_cursor_str(last_cursor)},
        input_count=pulled,
        output_count=0,  # 마지막에 갱신.
        error_count=0,
        started_at=datetime.fromtimestamp(batch.pulled_at_unix, UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()

    inserted = 0
    deduped = 0
    latest_observed: datetime | None = None

    for row in batch.rows:
        chash = _canonical_hash(row)
        cursor_str = _coerce_cursor_str(row.get(config.cursor_column))
        idem_key = f"{config.driver}:{config.database}.{config.table}:{cursor_str}"

        # 트랜잭션 내 중복 방지 — content_hash_index 조회.
        existing = session.execute(
            select(ContentHashIndex).where(ContentHashIndex.content_hash == chash)
        ).scalar_one_or_none()
        if existing is not None:
            deduped += 1
            continue

        raw = RawObject(
            source_id=ds.source_id,
            job_id=job.job_id,
            object_type="DB_ROW",
            payload_json=row,
            content_hash=chash,
            idempotency_key=idem_key,
            partition_date=today,
            status="RECEIVED",
        )
        session.add(raw)
        try:
            session.flush()
        except IntegrityError:
            # content_hash_index 가 아직 없지만 동시 fetch 가 같은 hash 를 적재한 race.
            session.rollback()
            deduped += 1
            continue

        session.add(
            ContentHashIndex(
                content_hash=chash,
                raw_object_id=raw.raw_object_id,
                partition_date=today,
                source_id=ds.source_id,
            )
        )
        session.add(
            EventOutbox(
                aggregate_type="raw_object",
                aggregate_id=f"{raw.raw_object_id}:{today.isoformat()}",
                event_type="ingest.api.received",
                payload_json={
                    "raw_object_id": raw.raw_object_id,
                    "partition_date": today.isoformat(),
                    "source_id": ds.source_id,
                    "source_code": source_code,
                    "kind": "db",
                    "content_hash": chash,
                    "table": f"{config.database}.{config.table}",
                    "cursor_column": config.cursor_column,
                    "cursor_value": cursor_str,
                },
            )
        )
        inserted += 1

        # observed_at — row 의 cursor_column 값이 timestamp 면 lag 계산용.
        cursor_val = row.get(config.cursor_column)
        if isinstance(cursor_val, datetime):
            latest_observed = (
                cursor_val
                if latest_observed is None or cursor_val > latest_observed
                else latest_observed
            )

    # ingest_job 결과 갱신
    job.output_count = inserted
    job.error_count = 0

    # watermark 갱신
    now = datetime.now(UTC)
    new_cursor = batch.max_cursor
    new_cursor_str = _coerce_cursor_str(new_cursor)
    ds.watermark = {
        "last_cursor": new_cursor_str if new_cursor_str else None,
        "last_run_at": now.isoformat(),
        "last_count": inserted,
    }

    metrics.db_incremental_pulled_total.labels(source_code=source_code, outcome="fetched").inc(
        inserted
    )
    if deduped:
        metrics.db_incremental_pulled_total.labels(source_code=source_code, outcome="dedup").inc(
            deduped
        )
    if latest_observed is not None:
        # naive datetime 가능성 — UTC tz 미설정이면 보수적 0 처리.
        if latest_observed.tzinfo is None:
            lag = 0.0
        else:
            lag = max(0.0, (now - latest_observed).total_seconds())
        metrics.db_incremental_lag_seconds.labels(source_code=source_code).set(lag)

    connector.close()
    return DbIncrementalOutcome(
        source_code=source_code,
        pulled_count=pulled,
        inserted_count=inserted,
        deduped_count=deduped,
        last_cursor=new_cursor,
        last_run_at=now,
    )


__all__ = ["DbIncrementalOutcome", "pull_incremental"]
