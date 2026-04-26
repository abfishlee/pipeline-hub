"""Phase 4.2.8 — 매일 03:00 KST mart.product_master 자동 머지.

cron 3 * * * (KST). PostgresHook 으로 PG 직접 접속 → run_daily_auto_merge 와 *동등한*
SQL 을 직접 실행하지 않고, backend internal endpoint 호출. (DAG 가 backend 도메인
로직 직접 import 하지 않는 패턴 — Phase 4.0.4 와 동일.)

본 DAG 는 stub — 운영 시 backend 의 `/v1/admin/master-merge/run` (ADMIN 인증) 호출.
PoC 단계는 통계 출력만.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook


def _list_candidate_std_codes() -> list[str]:
    """std_code 별로 product_master row 가 2+ 인 코드 목록 — 후보 신호."""
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    rows = hook.get_records(
        """
        SELECT std_code, COUNT(*) AS cnt
          FROM mart.product_master
         GROUP BY std_code
        HAVING COUNT(*) >= 2
        """
    )
    return [r[0] for r in rows]


def _emit_summary(**_kwargs: Any) -> dict[str, int]:
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    codes = _list_candidate_std_codes()
    if codes:
        payload = {
            "channel": "slack",
            "target": "",
            "level": "INFO",
            "subject": f"제품 머지 후보 std_code {len(codes)}개",
            "body": (
                f"candidates_std_codes={len(codes)} "
                f"backend `/v1/admin/master-merge/run` 호출로 자동 머지 가능"
            ),
            "candidate_count": len(codes),
        }
        hook.run(
            """
            INSERT INTO run.event_outbox
                (aggregate_type, aggregate_id, event_type, payload_json)
            VALUES ('master_merge', 'daily', 'notify.requested', %s::jsonb)
            """,
            parameters=(json.dumps(payload),),
        )
    return {"candidate_std_codes": len(codes)}


with DAG(
    dag_id="master_merge_daily",
    description="Phase 4.2.8 — 매일 03:00 KST product_master 자동 머지 후보 알람",
    schedule="0 3 * * *",
    start_date=datetime(2026, 5, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["master_merge", "phase4"],
    default_args={
        "owner": "datapipeline",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
):
    PythonOperator(
        task_id="emit_summary",
        python_callable=_emit_summary,
    )
