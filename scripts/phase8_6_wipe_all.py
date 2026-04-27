"""Phase 8.6.14 — 데이터 wipe.

운영자가 시스템을 *깨끗한 상태* 로 리셋한 후 Mock API 시나리오로 처음부터 끝까지
검증할 수 있도록 사용자 데이터 (run/raw/audit/domain 자산 등) 만 truncate.

남기는 것:
  - ctl.app_user / ctl.role / ctl.user_role        — 로그인 계정 유지
  - ctl.api_key                                     — API key 유지
  - ctl.mock_api_endpoint                           — mock 페이지 등록 유지 (Phase 8.6 시나리오)
  - alembic_version                                 — 마이그레이션 상태 유지
  - mart.standard_code (있으면)                     — 시스템 시드 표준코드 유지

지우는 것:
  - run.* (pipeline_run, node_run, ingest_job, event_outbox, hold_decision)
  - raw.* (raw_object 모든 파티션)
  - audit.* (access_log, inbound_event, security_event, alert_log, sql_execution_log,
            public_api_usage, perf_slo, provider_usage)
  - dq.quality_result
  - crowd.task / crowd_task
  - domain.* 자산 (public_api_connector, field_mapping, sql_asset, dq_rule,
                  load_policy, mart_design_draft, inbound_channel,
                  source_provider_binding, source_contract,
                  resource_definition, domain_definition)
  - wf.workflow_definition / node_definition / edge_definition / pipeline_release
  - mart.product_master / retailer_master / seller_master / product_mapping (있으면)
  - service_mart.* / *_mart.* / *_stg.*
  - stg.*

실행:
  cd backend
  PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe ../scripts/phase8_6_wipe_all.py [--yes]
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable

if os.name == "nt":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

# 도메인 무관 — 모든 사용자 schema 자동 검출
SAFE_SYSTEM_SCHEMAS = frozenset(
    {
        "pg_catalog",
        "information_schema",
        "alembic_version_schema",  # 일부 alembic config
        "public",  # alembic_version 만 있으므로 별도 처리
    }
)

WIPE_TABLES_ORDERED: list[tuple[str, str]] = [
    # 의존성 순서 — child 부터
    ("audit", "alert_log"),
    ("audit", "security_event"),
    ("audit", "sql_execution_log"),
    ("audit", "perf_slo"),
    ("audit", "download_log"),
    ("audit", "public_api_usage"),
    ("audit", "provider_usage"),
    ("audit", "access_log"),
    ("audit", "inbound_event"),
    ("dq", "quality_result"),
    ("crowd", "task"),
    ("crowd", "skill_tag"),
    ("crowd", "payout"),
    ("crowd", "reviewer_stats"),
    ("run", "event_outbox"),
    ("run", "hold_decision"),
    ("run", "node_run"),
    ("run", "pipeline_run"),
    ("run", "ingest_job"),
    ("raw", "raw_object_audit"),
    ("raw", "ocr_result"),
    ("raw", "raw_object"),
    ("raw", "content_hash_index"),
    ("raw", "db_cdc_event"),
    ("raw", "db_snapshot"),
    ("wf", "edge_definition"),
    ("wf", "node_definition"),
    ("wf", "pipeline_release"),
    ("wf", "workflow_dag_lock"),
    ("wf", "pipeline_template"),
    ("wf", "workflow_definition"),
    ("domain", "field_mapping"),
    ("domain", "dq_rule"),
    ("domain", "load_policy"),
    ("domain", "mart_design_draft"),
    ("domain", "sql_asset"),
    ("domain", "inbound_channel"),
    ("domain", "source_provider_binding"),
    ("domain", "public_api_connector"),
    ("domain", "source_contract"),
    ("domain", "resource_definition"),
    ("domain", "provider_definition"),
    ("domain", "domain_definition"),
    ("ctl", "dry_run_record"),
    ("ctl", "cdc_subscription"),
    ("ctl", "data_source"),
    ("mart", "product_mapping"),
    ("mart", "product_master"),
    ("mart", "seller_master"),
    ("mart", "retailer_master"),
    ("mart", "price_daily_agg"),
    ("mart", "price_fact"),  # partitioned
    ("service_mart", "product_price"),
    ("service_mart", "std_product"),
    ("agri_mart", "kamis_price"),
    ("pos_mart", "pos_transaction"),
    ("pos_mart", "std_payment_method_alias"),
]


def _table_exists(session: object, schema: str, table: str) -> bool:
    return bool(
        session.execute(  # type: ignore[attr-defined]
            text(
                "SELECT to_regclass(:fqdn) IS NOT NULL"
            ),
            {"fqdn": f"{schema}.{table}"},
        ).scalar()
    )


def _all_schemas_with_pattern(session: object, pattern: str) -> list[str]:
    rows = session.execute(  # type: ignore[attr-defined]
        text(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname LIKE :pat "
            "  AND nspname NOT IN ('pg_catalog','information_schema') "
            "ORDER BY nspname"
        ),
        {"pat": pattern},
    ).all()
    return [str(r[0]) for r in rows]


def _all_tables_in_schema(session: object, schema: str) -> list[str]:
    rows = session.execute(  # type: ignore[attr-defined]
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname=:s ORDER BY tablename"
        ),
        {"s": schema},
    ).all()
    return [str(r[0]) for r in rows]


def main(args: Iterable[str]) -> None:
    auto_yes = "--yes" in args or os.getenv("WIPE_AUTO_YES") == "1"

    sm = get_sync_sessionmaker()
    with sm() as session:
        print("== Phase 8.6 Data Wipe — 시작 ==")

        # 1. 알려진 테이블 truncate
        wiped: list[str] = []
        skipped: list[str] = []
        for schema, table in WIPE_TABLES_ORDERED:
            if _table_exists(session, schema, table):
                session.execute(text(f"TRUNCATE {schema}.{table} CASCADE"))
                wiped.append(f"{schema}.{table}")
            else:
                skipped.append(f"{schema}.{table}")

        # 2. 동적으로 _stg / _mart 스키마 전체 truncate
        stg_schemas = _all_schemas_with_pattern(session, "%_stg")
        mart_schemas = _all_schemas_with_pattern(session, "%_mart")
        for sc in stg_schemas + mart_schemas:
            for tbl in _all_tables_in_schema(session, sc):
                # service_mart 는 위 list 에서 처리됨 — 중복 ok (TRUNCATE idempotent)
                session.execute(text(f"TRUNCATE {sc}.{tbl} CASCADE"))
                wiped.append(f"{sc}.{tbl}")

        # 3. wf.tmp_run_* 임시 sandbox 테이블 정리 (이전 run 잔재)
        tmp_tables = session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='wf' AND tablename LIKE 'tmp_run_%'"
            )
        ).all()
        for r in tmp_tables:
            session.execute(text(f"DROP TABLE IF EXISTS wf.{r[0]} CASCADE"))
            wiped.append(f"wf.{r[0]} (DROPPED)")

        # 4. sequence reset
        session.execute(text("SELECT setval(c.oid, 1, false) "
                             "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                             "WHERE c.relkind='S' AND n.nspname IN ('raw','run','audit','wf','domain','dq','crowd','service_mart')"))

        if not auto_yes:
            print(f"\n  truncated/dropped: {len(wiped)} 객체")
            print(f"  skipped (미존재): {len(skipped)} 객체")
            ans = input("commit 하시겠습니까? (y/N): ").strip().lower()
            if ans != "y":
                session.rollback()
                print("ROLLBACK — 데이터 그대로.")
                return

        session.commit()
        print(f"\n✓ wipe 완료 — {len(wiped)} 객체 정리.")
        print("  남은 것: ctl.app_user / ctl.role / ctl.api_key / ctl.mock_api_endpoint / mart.standard_code")
        print("  다음 단계: scripts/phase8_6_validate_scenario.py 실행")


if __name__ == "__main__":
    main(sys.argv[1:])
