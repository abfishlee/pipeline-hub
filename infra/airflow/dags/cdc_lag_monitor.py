"""Phase 4.2.3 — CDC slot lag 모니터링 + dispatch_cdc_batch enqueue.

매 5분 가동:
  1. ctl.cdc_subscription 의 enabled=true 행 조회.
  2. 각 subscription 마다 backend 에 직접 PG 접속해
     `pg_replication_slots.confirmed_flush_lsn` 기준 lag_bytes 계산 → 메타 갱신.
  3. lag 임계 초과 시 outbox NOTIFY 발행 (notify_worker 가 Slack 발송).
  4. backend 의 dispatch_cdc_batch actor 를 enqueue — slot stream 1배치 polling.

설계 메모:
  - Airflow 의 PostgresHook 으로 backend 와 동일한 PG 에 접속. backend 의 sync 도메인
    함수 (`update_lag_metric`) 와 같은 로직을 SQL 로 직접 구현 — Airflow 컨테이너에
    backend 코드 import 의존성 회피.
  - dispatch_cdc_batch enqueue 는 backend 의 internal endpoint 호출 또는 Redis 에
    직접 push. 본 DAG 은 *측정 + 알람만* 담당하고 worker 는 별도 컨테이너에서 폴링
    (단순화).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

log = logging.getLogger(__name__)

LAG_THRESHOLD_BYTES_DEFAULT = 10 * 1024 * 1024  # 10 MB


def _list_active_subscriptions() -> list[dict[str, Any]]:
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    rows = hook.get_records(
        """
        SELECT subscription_id, source_id, slot_name, last_lag_bytes
          FROM ctl.cdc_subscription
         WHERE enabled = TRUE
        """
    )
    return [
        {
            "subscription_id": r[0],
            "source_id": r[1],
            "slot_name": r[2],
            "last_lag_bytes": r[3],
        }
        for r in rows
    ]


def _measure_and_alert(threshold_bytes: int = LAG_THRESHOLD_BYTES_DEFAULT) -> dict[str, Any]:
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    subs = _list_active_subscriptions()
    measured = 0
    alerted = 0
    now = datetime.now(UTC)
    for sub in subs:
        slot_name = sub["slot_name"]
        row = hook.get_first(
            """
            SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)
              FROM pg_replication_slots
             WHERE slot_name = %s
            """,
            parameters=(slot_name,),
        )
        lag: int | None = None
        if row is not None and row[0] is not None:
            lag = int(row[0])
        hook.run(
            """
            UPDATE ctl.cdc_subscription
               SET last_lag_bytes = %s,
                   last_polled_at = %s,
                   updated_at = now()
             WHERE subscription_id = %s
            """,
            parameters=(lag, now, sub["subscription_id"]),
        )
        measured += 1
        if lag is not None and lag > threshold_bytes:
            alerted += 1
            payload = {
                "channel": "slack",
                "target": "",
                "level": "WARN",
                "subject": f"CDC lag 초과 — slot {slot_name}",
                "body": (
                    f"slot={slot_name} lag={lag}B threshold={threshold_bytes}B "
                    f"(source_id={sub['source_id']})"
                ),
                "subscription_id": sub["subscription_id"],
                "source_id": sub["source_id"],
                "lag_bytes": lag,
                "threshold_bytes": threshold_bytes,
            }
            hook.run(
                """
                INSERT INTO run.event_outbox
                       (aggregate_type, aggregate_id, event_type, payload_json)
                VALUES ('cdc_subscription', %s, 'notify.requested', %s::jsonb)
                """,
                parameters=(str(sub["subscription_id"]), json.dumps(payload)),
            )
    return {"measured": measured, "alerted": alerted}


def _entry(**_kwargs: Any) -> dict[str, Any]:
    summary = _measure_and_alert()
    log.info("cdc_lag_monitor.summary measured=%s alerted=%s", summary["measured"], summary["alerted"])
    return summary


with DAG(
    dag_id="cdc_lag_monitor",
    description="Phase 4.2.3 — CDC slot lag 측정 + 임계 초과 시 Slack notify outbox",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 4, 26, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["cdc", "phase4"],
    default_args={
        "owner": "datapipeline",
        "retries": 2,
        "retry_delay": timedelta(seconds=30),
    },
):
    PythonOperator(
        task_id="measure_and_alert",
        python_callable=_entry,
    )
