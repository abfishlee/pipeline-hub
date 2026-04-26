"""Phase 4.2.7 — 매월 1일 04:00 KST partition archive.

대상: raw.raw_object_*, run.pipeline_run_*, mart.price_fact_*, audit.access_log_*
조건: child partition 이름의 YYYY_MM 가 *현재로부터 13 개월 이전*.

본 DAG 는 *후보 detect + Slack 알람* 만 담당. 실제 archive 작업 (Object Storage 복제 +
DETACH + DROP) 은 backend 의 `partition_archive` 도메인이 처리 — 운영자가 admin
endpoint 로 1건씩 또는 일괄 실행. 자동 DROP 은 운영 사고 위험이 크므로 *반자동* 정책.

(완전 자동을 원하면 후속 ADR + flag 추가 — Phase 4.2.7 PoC 는 보수적으로 수동 승인.)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

PARENT_TABLES: tuple[tuple[str, str], ...] = (
    ("raw", "raw_object"),
    ("run", "pipeline_run"),
    ("mart", "price_fact"),
    ("audit", "access_log"),
)
ARCHIVE_AGE_MONTHS = 13


def _list_aged_partitions() -> list[dict[str, str]]:
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    out: list[dict[str, str]] = []
    for schema, parent in PARENT_TABLES:
        rows = hook.get_records(
            """
            SELECT child.relname
            FROM pg_inherits i
            JOIN pg_class child  ON child.oid = i.inhrelid
            JOIN pg_class par    ON par.oid   = i.inhparent
            JOIN pg_namespace n  ON n.oid     = par.relnamespace
            WHERE n.nspname = %s AND par.relname = %s
            ORDER BY child.relname
            """,
            parameters=(schema, parent),
        )
        now = datetime.now(UTC)
        for r in rows:
            partition_name = r[0]
            try:
                suffix = partition_name.replace(f"{parent}_", "", 1)
                year_str, month_str = suffix.split("_", 1)
                y = int(year_str)
                m = int(month_str)
            except (ValueError, AttributeError):
                continue
            age = (now.year - y) * 12 + (now.month - m)
            if age >= ARCHIVE_AGE_MONTHS:
                out.append(
                    {
                        "schema": schema,
                        "table": parent,
                        "partition": partition_name,
                        "age_months": age,
                    }
                )
    return out


def _detect_and_alert(**_kwargs: Any) -> dict[str, int]:
    """후보 detect + ctl.partition_archive_log 에 PENDING row 적재 + Slack 알람."""
    hook = PostgresHook(postgres_conn_id="postgres_datapipeline")
    candidates = _list_aged_partitions()
    inserted = 0
    for c in candidates:
        # ON CONFLICT — 이미 PENDING/ARCHIVED 가 있으면 건드리지 않음.
        result = hook.get_first(
            """
            INSERT INTO ctl.partition_archive_log
                (schema_name, table_name, partition_name, status)
            VALUES (%s, %s, %s, 'PENDING')
            ON CONFLICT (schema_name, table_name, partition_name) DO NOTHING
            RETURNING archive_id
            """,
            parameters=(c["schema"], c["table"], c["partition"]),
        )
        if result is not None:
            inserted += 1
    if candidates:
        payload = {
            "channel": "slack",
            "target": "",
            "level": "INFO",
            "subject": f"파티션 아카이브 후보 {len(candidates)}개",
            "body": f"detected={len(candidates)} new_pending={inserted} oldest_age=" + (
                str(max(c["age_months"] for c in candidates)) if candidates else "0"
            ),
            "candidates": candidates,
        }
        hook.run(
            """
            INSERT INTO run.event_outbox
                (aggregate_type, aggregate_id, event_type, payload_json)
            VALUES ('partition_archive', 'monthly', 'notify.requested', %s::jsonb)
            """,
            parameters=(json.dumps(payload),),
        )
    return {"detected": len(candidates), "new_pending": inserted}


with DAG(
    dag_id="partition_archive_monthly",
    description="Phase 4.2.7 — 매월 1일 04:00 KST 13개월+ 파티션 후보 detect + 알람",
    # 매월 1일 04:00 KST = 19:00 UTC 전날 → cron 간단화: 매월 1일 04:00 (Airflow tz=Asia/Seoul)
    schedule="0 4 1 * *",
    start_date=datetime(2026, 5, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["partition", "archive", "phase4"],
    default_args={
        "owner": "datapipeline",
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
):
    PythonOperator(
        task_id="detect_and_alert",
        python_callable=_detect_and_alert,
    )
