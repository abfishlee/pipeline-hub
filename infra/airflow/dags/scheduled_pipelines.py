"""Phase 4.0.4 — Visual ETL 워크플로의 cron 자동 트리거.

매분(`*/1 * * * *`) 가동 — backend 에 직접 PG 접속해 다음 조건의 워크플로 조회:

  status = 'PUBLISHED'  AND  schedule_enabled = TRUE  AND  schedule_cron IS NOT NULL

각 row 의 cron 표현식으로 직전/다음 trigger 시각 계산. *직전 1분 안에 trigger 시각이
들어 있으면* `POST /v1/pipelines/internal/runs` 호출.

설계:
  - **croniter polling** 방식 (Airflow sensor 대신 단순 PythonOperator) — Phase 4
    인프라 단순화 + 운영자 디버깅 용이성. 트래픽 늘어나면 sensor + DeferrableOperator 로
    재평가 (ADR 후속).
  - **멱등** — backend internal endpoint 가 같은 (workflow_id, today) 가 RUNNING/SUCCESS
    면 새 run 안 만듦. 1분 cron 이 두 번 발화해도 안전.
  - **실패 격리** — 한 워크플로 trigger 가 실패해도 다음 워크플로는 계속 처리.

Variable (Airflow 측):
  BACKEND_INTERNAL_URL    — http://backend-api:8000 / http://host.docker.internal:8000
  BACKEND_INTERNAL_TOKEN  — backend Settings.airflow_internal_token 와 동일

Connection (Airflow 측):
  postgres_datapipeline   — backend 와 같은 PG 의 read-only 접속
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from croniter import croniter

# plugins/operators/ 가 PYTHONPATH 에 있어야 함 (Airflow 가 plugins 자동 등록).
try:
    from operators.start_pipeline_op import trigger_pipeline_run
except ImportError:  # pragma: no cover
    # Airflow 컨테이너 외부에서 import 될 때 fallback (테스트 등).
    from infra.airflow.plugins.operators.start_pipeline_op import (  # type: ignore[no-redef]
        trigger_pipeline_run,
    )

log = logging.getLogger(__name__)


def _list_due_workflows(now_utc: datetime, lookback_seconds: int = 60) -> list[dict[str, Any]]:
    """PG 에서 schedule_enabled=TRUE PUBLISHED 워크플로 + cron 직전 1분 안 발화 분 조회.

    반환: [{"workflow_id": int, "name": str, "schedule_cron": str, "due_at": datetime}, ...]
    """
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    rows: list[tuple[int, str, str]] = hook.get_records(
        """
        SELECT workflow_id, name, schedule_cron
          FROM wf.workflow_definition
         WHERE status = 'PUBLISHED'
           AND schedule_enabled = TRUE
           AND schedule_cron IS NOT NULL
         ORDER BY workflow_id
        """
    )

    window_start = now_utc - timedelta(seconds=lookback_seconds)
    due: list[dict[str, Any]] = []
    for wf_id, name, cron in rows:
        try:
            it = croniter(cron, window_start)
            next_fire = it.get_next(datetime)
            # next_fire 가 [window_start, now_utc] 사이에 있으면 발화 대상.
            if window_start <= next_fire <= now_utc:
                due.append(
                    {
                        "workflow_id": int(wf_id),
                        "name": str(name),
                        "schedule_cron": str(cron),
                        "due_at": next_fire.isoformat(),
                    }
                )
        except (ValueError, KeyError) as exc:
            log.warning("invalid cron for workflow %s (%s): %s", wf_id, name, exc)

    log.info("due workflows in last %ds: %d", lookback_seconds, len(due))
    return due


def _trigger_due_workflows(**context: Any) -> dict[str, Any]:
    """DAG task callable.

    1. PG 에서 발화 대상 워크플로 조회.
    2. 각 워크플로에 대해 backend internal endpoint 호출.
    3. 결과 dict 를 XCom 에 push (Airflow web UI 에서 확인 가능).

    실패한 워크플로 1개가 다른 워크플로 trigger 를 막지 않음 — 개별 try/except.
    """
    base_url = Variable.get("BACKEND_INTERNAL_URL", default_var="http://host.docker.internal:8000")
    token = Variable.get("BACKEND_INTERNAL_TOKEN", default_var="")
    if not token:
        log.error("BACKEND_INTERNAL_TOKEN Variable not set — skipping all triggers")
        return {"triggered": 0, "skipped": 0, "errors": 0, "due": 0}

    now_utc = datetime.now(UTC)
    due = _list_due_workflows(now_utc)
    triggered = 0
    skipped = 0
    errors = 0
    results: list[dict[str, Any]] = []

    for wf in due:
        try:
            res = trigger_pipeline_run(
                workflow_id=wf["workflow_id"],
                base_url=base_url,
                token=token,
            )
            if res.get("created"):
                triggered += 1
            else:
                skipped += 1
            results.append({**wf, "result": res})
        except Exception as exc:
            errors += 1
            log.exception("trigger failed for workflow_id=%s: %s", wf["workflow_id"], exc)
            results.append({**wf, "error": str(exc)})

    summary = {"triggered": triggered, "skipped": skipped, "errors": errors, "due": len(due)}
    log.info("scheduled_pipelines summary: %s", summary)
    # 너무 큰 list 는 XCom 에 부담 — 50개로 truncate.
    context["ti"].xcom_push(key="results", value=results[:50])
    return summary


default_args = {
    "owner": "platform",
    "retries": 0,  # 같은 분에 재시도하면 멱등이긴 해도 noise 늘어남.
    "depends_on_past": False,
}

with DAG(
    dag_id="system_scheduled_pipelines",
    description="Phase 4.0.4 — wf.workflow_definition 의 cron 자동 트리거.",
    start_date=datetime(2026, 4, 26),
    schedule="*/1 * * * *",  # 매 분.
    catchup=False,
    default_args=default_args,
    tags=["system", "phase-4", "cron-trigger"],
    max_active_runs=1,  # 동시에 1번만.
) as dag:
    PythonOperator(
        task_id="trigger_due_workflows",
        python_callable=_trigger_due_workflows,
    )
