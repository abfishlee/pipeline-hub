"""Phase 2.2.3 — Airflow 학습용 Hello DAG.

이 프로젝트의 첫 시스템 DAG. **실제 운영에 쓰이는 DAG 아님** — Airflow 가 정상 기동
했고, scheduler 가 schedule 을 인식하며, BashOperator/PythonOperator 가 동작하는지
확인하기 위한 smoke test.

이후 시스템 DAG (Phase 2.2.x) 명명 규칙:
  - 파일/dag_id: `system_<purpose>` (예: `system_daily_agg`, `system_monthly_partition`)
  - tag: `["system", "<phase>"]`
  - owner: `platform`

사용자 정의 파이프라인은 Phase 3 Visual ETL 이 별도로 처리 — Airflow DAG 으로 직접
작성하지 않는다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

log = logging.getLogger(__name__)


def _hello_python(**context: object) -> dict[str, str]:
    """PythonOperator 학습용. context 의 일부를 stdout 에 찍고 반환."""
    ds = str(context.get("ds", "<unknown>"))
    run_id = str(context.get("run_id", "<unknown>"))
    log.info("hello_python invoked: ds=%s run_id=%s", ds, run_id)
    return {"ds": ds, "run_id": run_id, "phase": "2.2.3"}


default_args = {
    "owner": "platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="system_hello_pipeline",
    description="Phase 2.2.3 smoke test — Airflow 기동/스케줄/오퍼레이터 동작 확인.",
    start_date=datetime(2026, 4, 25),
    schedule="@daily",
    catchup=False,
    default_args=default_args,
    tags=["system", "phase-2", "smoke"],
    max_active_runs=1,
) as dag:
    bash_hello = BashOperator(
        task_id="bash_hello",
        bash_command='echo "Hello from Airflow @ $(date -u +%FT%TZ) — ds={{ ds }}"',
    )

    python_hello = PythonOperator(
        task_id="python_hello",
        python_callable=_hello_python,
    )

    bash_hello >> python_hello
