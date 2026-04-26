"""Phase 4.2.5 — Public API 사용량 일별 집계 + 임계 알람.

매일 00:30 가동:
  1. audit.public_api_usage_daily view (자동 갱신, 별도 refresh 불필요).
  2. 전일 집계에서 *키별 호출 100K+ 또는 error rate 10%+* 인 row 발견 시 outbox NOTIFY.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

CALL_HIGH_THRESHOLD = 100_000
ERROR_RATE_THRESHOLD = 0.10  # 10%


def _check_anomalies(**_kwargs: Any) -> dict[str, int]:
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    rows = hook.get_records(
        """
        SELECT api_key_id, endpoint, count, error_count
          FROM audit.public_api_usage_daily
         WHERE day = %s
        """,
        parameters=(yesterday,),
    )
    alerts = 0
    for r in rows:
        api_key_id, endpoint, count, error_count = r[0], r[1], int(r[2]), int(r[3])
        error_rate = (error_count / count) if count > 0 else 0.0
        if count >= CALL_HIGH_THRESHOLD or error_rate >= ERROR_RATE_THRESHOLD:
            payload = {
                "channel": "slack",
                "target": "",
                "level": "WARN",
                "subject": f"Public API 임계 초과 — api_key {api_key_id}",
                "body": (
                    f"day={yesterday} api_key_id={api_key_id} endpoint={endpoint} "
                    f"count={count} error_count={error_count} "
                    f"error_rate={error_rate:.2%}"
                ),
                "api_key_id": api_key_id,
                "endpoint": endpoint,
                "count": count,
                "error_count": error_count,
                "error_rate": error_rate,
                "day": yesterday.isoformat(),
            }
            hook.run(
                """
                INSERT INTO run.event_outbox
                       (aggregate_type, aggregate_id, event_type, payload_json)
                VALUES ('api_key', %s, 'notify.requested', %s::jsonb)
                """,
                parameters=(str(api_key_id), json.dumps(payload)),
            )
            alerts += 1
    return {"checked": len(rows), "alerts": alerts}


with DAG(
    dag_id="public_api_usage_daily",
    description="Phase 4.2.5 — Public API 사용량 임계 모니터링",
    schedule="30 0 * * *",
    start_date=datetime(2026, 4, 26, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["public-api", "phase4"],
    default_args={
        "owner": "datapipeline",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
):
    PythonOperator(
        task_id="check_anomalies",
        python_callable=_check_anomalies,
    )
