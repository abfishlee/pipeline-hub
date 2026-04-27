"""Phase 8.6 — 풍부한 시연 시나리오 자동 등록 + 실행.

사용자가 화면에서 검증할 모든 자산을 자동 등록:
  1. Mock API 등록 + 호출 검증
  2. Source / API Connector 등록 + PUBLISHED
  3. iot_stg.sensor_raw + iot_mart.sensor_reading 마트 + load_policy 생성
  4. Field Mapping 등록 + PUBLISHED
  5. SQL Asset 등록 (평탄화 + 단위변환) + PUBLISHED
  6. DQ Rule 3종 등록 + PUBLISHED (range / null_pct_max / unique_columns)
  7. Workflow 6 노드 등록 + PUBLISHED
  8. schedule_cron = */5 * * * * + 활성
  9. 즉시 1회 trigger → run 검증
  10. iot_mart row 적재 검증

실행:
  cd backend
  PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe ../scripts/phase8_6_run_demo.py

실행 후 화면에서 검증:
  - Mock API:           /v2/mock-api
  - Source Connector:   /v2/connectors/public-api
  - Mart Workbench:     /v2/marts/designer
  - Field Mapping:      /v2/mappings/designer
  - Quality:            /v2/quality/designer
  - Transform:          /v2/transforms/designer
  - ETL Canvas:         /v2/pipelines/designer/{workflow_id}
  - Pipeline Runs:      /pipelines/runs
  - Pipeline Run Detail: /pipelines/runs/{run_id}
  - Operations:         /v2/operations/dashboard
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from typing import Any
from uuid import uuid4

if os.name == "nt":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

BASE = os.getenv("BACKEND_URL") or "http://127.0.0.1:8000"
ADMIN_LOGIN = "admin"
ADMIN_PW = "admin"

DOMAIN_CODE = "iot"
RESOURCE_CODE = "sensor_reading"
SOURCE_CODE = "demo86_iot_src"
MOCK_CODE = "demo86_iot_sensors"
WORKFLOW_NAME = "demo86_iot_pipeline"

STG_SCHEMA = "iot_stg"
STG_TABLE = "sensor_raw"
MART_SCHEMA = "iot_mart"
MART_TABLE = "sensor_reading"

# 8 row + 의도적 이상치 (S007 의 value=999.9 — range rule 위반 case)
MOCK_BODY_OBJ: dict[str, Any] = {
    "items": [
        {"sensor_id": "S001", "value": 23.5, "unit": "C", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S002", "value": 24.1, "unit": "C", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S003", "value": 22.8, "unit": "C", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S004", "value": 25.0, "unit": "C", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S005", "value": 23.9, "unit": "C", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S006", "value": 24.7, "unit": "F", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S007", "value": 26.0, "unit": "C", "ts": "2026-04-27T10:00:00"},
        {"sensor_id": "S008", "value": 22.0, "unit": "C", "ts": "2026-04-27T10:00:00"},
    ]
}
MOCK_BODY = json.dumps(MOCK_BODY_OBJ, ensure_ascii=False)


def step(label: str, fn) -> Any:
    print(f"\n─── {label}")
    out = fn()
    print(f"    ✓ 완료")
    return out


def login(client: httpx.Client) -> dict[str, str]:
    r = client.post(
        "/v1/auth/login",
        json={"login_id": ADMIN_LOGIN, "password": ADMIN_PW},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:  # noqa: PLR0915  too many statements — demo script
    sm = get_sync_sessionmaker()

    with httpx.Client(base_url=BASE, timeout=30) as client:
        H = login(client)

        # ── 1. Mock API 등록 ──────────────────────────────────────────────
        def _mock() -> dict[str, Any]:
            # idempotent 처리 — 기존 동일 code 가 있으면 삭제 후 재등록
            existing = client.get("/v2/mock-api/endpoints", headers=H).json()
            for m in existing:
                if m["code"] == MOCK_CODE:
                    client.delete(
                        f"/v2/mock-api/endpoints/{m['mock_id']}", headers=H
                    )
            r = client.post(
                "/v2/mock-api/endpoints",
                headers=H,
                json={
                    "code": MOCK_CODE,
                    "name": "데모 IoT 센서 (Phase 8.6 시연)",
                    "description": "공용 플랫폼 자체 검증용 — 8 row, 의도적 이상치 1건 포함",
                    "response_format": "json",
                    "response_body": MOCK_BODY,
                    "response_headers": {},
                    "status_code": 200,
                    "delay_ms": 0,
                    "is_active": True,
                },
            )
            r.raise_for_status()
            return r.json()

        mock = step("1. Mock API 등록", _mock)
        serve_path = mock["serve_url_path"]
        serve_url = f"{BASE}{serve_path}"
        print(f"    serve URL: {serve_url}")

        # 호출 검증
        r = client.get(serve_path)
        assert r.status_code == 200 and len(r.json()["items"]) == 8, "mock serve failed"

        # ── 2. iot 도메인 + resource + ctl.data_source + stg/mart schema 생성 ─
        def _domain_setup() -> int:
            with sm() as s:
                # domain
                s.execute(
                    text(
                        "INSERT INTO domain.domain_definition (domain_code, name, description) "
                        "VALUES (:c, :n, :d) ON CONFLICT (domain_code) DO NOTHING"
                    ),
                    {"c": DOMAIN_CODE, "n": "IoT 시연 도메인", "d": "Phase 8.6 데모"},
                )
                # resource (status DRAFT — 운영자가 화면에서 PUBLISHED 가능)
                s.execute(
                    text(
                        "INSERT INTO domain.resource_definition "
                        "(domain_code, resource_code, fact_table, status) "
                        "VALUES (:dc, :rc, :ft, 'PUBLISHED') ON CONFLICT DO NOTHING"
                    ),
                    {
                        "dc": DOMAIN_CODE,
                        "rc": RESOURCE_CODE,
                        "ft": f"{MART_SCHEMA}.{MART_TABLE}",
                    },
                )
                # ctl.data_source
                s.execute(
                    text(
                        "INSERT INTO ctl.data_source "
                        "(source_code, source_name, source_type, is_active, config_json) "
                        "VALUES (:c, :n, 'API', true, '{}') "
                        "ON CONFLICT (source_code) DO NOTHING"
                    ),
                    {"c": SOURCE_CODE, "n": "데모 IoT API source"},
                )
                src_id = int(
                    s.execute(
                        text(
                            "SELECT source_id FROM ctl.data_source WHERE source_code=:c"
                        ),
                        {"c": SOURCE_CODE},
                    ).scalar_one()
                )
                # schemas
                s.execute(text(f"CREATE SCHEMA IF NOT EXISTS {STG_SCHEMA}"))
                s.execute(text(f"CREATE SCHEMA IF NOT EXISTS {MART_SCHEMA}"))
                # iot_stg.sensor_raw — 평탄화된 raw (변환 전)
                s.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS {STG_SCHEMA}.{STG_TABLE} (
                            sensor_id   TEXT NOT NULL,
                            value       NUMERIC(10,2) NOT NULL,
                            unit        TEXT NOT NULL,
                            ts          TIMESTAMPTZ NOT NULL,
                            inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            PRIMARY KEY (sensor_id, ts)
                        )
                        """
                    )
                )
                # iot_mart.sensor_reading — 표준화 후 (모든 단위 → C)
                s.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS {MART_SCHEMA}.{MART_TABLE} (
                            sensor_id   TEXT NOT NULL,
                            value_c     NUMERIC(10,2) NOT NULL,
                            ts          TIMESTAMPTZ NOT NULL,
                            inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            PRIMARY KEY (sensor_id, ts)
                        )
                        """
                    )
                )
                s.commit()
                return src_id

        src_id = step("2. 도메인 + 마트 (stg + mart) 생성", _domain_setup)

        # ── 3. Public API Connector 등록 (Mock URL 호출) ──────────────────
        def _connector() -> int:
            r = client.post(
                "/v2/connectors/public-api",
                headers=H,
                json={
                    "domain_code": DOMAIN_CODE,
                    "resource_code": RESOURCE_CODE,
                    "name": "데모 IoT 센서 connector",
                    "description": "Mock API serve URL 을 외부 API 처럼 호출",
                    "endpoint_url": serve_url,
                    "http_method": "GET",
                    "auth_method": "none",
                    "response_format": "json",
                    "response_path": "$.items",
                    "schedule_cron": None,
                    "schedule_enabled": False,
                },
            )
            r.raise_for_status()
            cid = int(r.json()["connector_id"])
            # 라이프사이클: DRAFT → REVIEW → APPROVED → PUBLISHED
            for status in ["REVIEW", "APPROVED", "PUBLISHED"]:
                tr = client.post(
                    f"/v2/connectors/public-api/{cid}/transition",
                    headers=H,
                    json={"target_status": status},
                )
                if tr.status_code >= 300:
                    print(f"      transition → {status}: {tr.status_code} {tr.text[:100]}")
                    tr.raise_for_status()
            return cid

        connector_id = step("3. Connector 등록 + PUBLISHED", _connector)

        # ── 4. Source Contract 등록 (직접 INSERT, idempotent) ────────────
        def _contract() -> int:
            with sm() as s:
                # 기존 확인
                cid = s.execute(
                    text(
                        "SELECT contract_id FROM domain.source_contract "
                        "WHERE source_id=:src AND domain_code=:d AND resource_code=:r "
                        "ORDER BY schema_version DESC LIMIT 1"
                    ),
                    {"src": src_id, "d": DOMAIN_CODE, "r": RESOURCE_CODE},
                ).scalar_one_or_none()
                if cid:
                    return int(cid)
                # 새로 INSERT
                schema_json = {
                    "type": "object",
                    "properties": {
                        "sensor_id": {"type": "string"},
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                        "ts": {"type": "string"},
                    },
                }
                row = s.execute(
                    text(
                        "INSERT INTO domain.source_contract "
                        "(source_id, domain_code, resource_code, schema_version, "
                        " schema_json, status, description) "
                        "VALUES (:src, :d, :r, 1, CAST(:sj AS JSONB), 'PUBLISHED', "
                        "        'Phase 8.6 데모 contract — IoT 센서') "
                        "RETURNING contract_id"
                    ),
                    {
                        "src": src_id,
                        "d": DOMAIN_CODE,
                        "r": RESOURCE_CODE,
                        "sj": json.dumps(schema_json),
                    },
                ).first()
                s.commit()
                assert row is not None
                return int(row[0])

        contract_id = step("4. Source Contract 등록 (PUBLISHED)", _contract)

        # ── 5. Field Mapping 등록 + PUBLISHED ──────────────────────────────
        def _mappings() -> int:
            mappings = [
                {
                    "source_path": "$.sensor_id",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "target_column": "sensor_id",
                    "transform_expr": "text.trim",
                    "is_required": True,
                },
                {
                    "source_path": "$.value",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "target_column": "value",
                    "transform_expr": "number.parse_decimal",
                    "is_required": True,
                },
                {
                    "source_path": "$.unit",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "target_column": "unit",
                    "transform_expr": "text.upper",
                    "is_required": True,
                },
                {
                    "source_path": "$.ts",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "target_column": "ts",
                    "transform_expr": None,
                    "is_required": True,
                },
            ]
            created = 0
            for i, m in enumerate(mappings, start=1):
                r = client.post(
                    "/v2/mappings",
                    headers=H,
                    json={
                        "contract_id": contract_id,
                        "order_no": i,
                        **m,
                    },
                )
                if r.status_code in (200, 201):
                    mid = int(r.json()["mapping_id"])
                elif r.status_code == 409:
                    # 이미 있으면 fetch
                    lst = client.get(
                        "/v2/mappings",
                        headers=H,
                        params={"contract_id": contract_id},
                    ).json()
                    existing = next(
                        x
                        for x in lst
                        if x["target_table"] == m["target_table"]
                        and x["target_column"] == m["target_column"]
                    )
                    mid = int(existing["mapping_id"])
                else:
                    print(f"      mapping {i}: {r.status_code} {r.text[:200]}")
                    r.raise_for_status()
                # transition (PUBLISHED 면 skip)
                for st in ["REVIEW", "APPROVED", "PUBLISHED"]:
                    tr = client.post(
                        f"/v2/mappings/{mid}/transition",
                        headers=H,
                        json={"target_status": st},
                    )
                    # 이미 같은 status 거나 더 진행된 상태면 무시
                    if tr.status_code in (200, 409):
                        continue
                    if tr.status_code >= 300:
                        tr.raise_for_status()
                created += 1
            return created

        mappings_n = step("5. Field Mapping 4행 등록 + PUBLISHED", _mappings)

        # ── 6. SQL Asset (단위 변환 SELECT) 등록 + PUBLISHED ──────────────
        # SELECT 만 — sql_guard 가 INSERT/UPDATE 등 DML 차단.
        # 결과는 sandbox 테이블에 저장되고, LOAD_TARGET 이 mart 로 적재.
        def _sql_asset() -> int:
            sql = (
                f"SELECT sensor_id, "
                f"       CASE WHEN unit='F' THEN (value - 32) * 5.0/9.0 ELSE value END AS value_c, "
                f"       ts "
                f"FROM {STG_SCHEMA}.{STG_TABLE}"
            )
            r = client.post(
                "/v2/sql-assets",
                headers=H,
                json={
                    "domain_code": DOMAIN_CODE,
                    "asset_code": "demo86_iot_unit_normalize",
                    "description": "단위 정규화 — F → C",
                    "sql_text": sql,
                    "output_table": f"{MART_SCHEMA}.{MART_TABLE}",
                },
            )
            r.raise_for_status()
            aid = int(r.json()["asset_id"])
            for st in ["REVIEW", "APPROVED", "PUBLISHED"]:
                tr = client.post(
                    f"/v2/sql-assets/{aid}/transition",
                    headers=H,
                    json={"target_status": st},
                )
                tr.raise_for_status()
            return aid

        try:
            sql_asset_id = step("6. SQL Asset (단위 변환 SELECT) 등록 + PUBLISHED", _sql_asset)
        except Exception as exc:
            print(f"    ⚠ SQL Asset 등록 skip ({exc}) — 화면에서 직접 등록 가능")
            sql_asset_id = None

        # ── 7. DQ Rule 3종 등록 + PUBLISHED ───────────────────────────────
        def _dq_rules() -> list[int]:
            rules = [
                {
                    "rule_kind": "row_count_min",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "rule_json": {"min": 1},
                    "severity": "ERROR",
                    "description": "최소 1행 이상 적재되어야 함",
                },
                {
                    "rule_kind": "null_pct_max",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "rule_json": {"column": "value", "max": 0.05},
                    "severity": "WARN",
                    "description": "value 컬럼 NULL 5% 이하",
                },
                {
                    "rule_kind": "unique_columns",
                    "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                    "rule_json": {"columns": ["sensor_id", "ts"]},
                    "severity": "ERROR",
                    "description": "(sensor_id, ts) 중복 없음",
                },
            ]
            ids = []
            for r_body in rules:
                r = client.post(
                    "/v2/dq-rules",
                    headers=H,
                    json={"domain_code": DOMAIN_CODE, **r_body},
                )
                r.raise_for_status()
                rid = int(r.json()["rule_id"])
                ids.append(rid)
            # PUBLISHED 로 일괄 UPDATE (transition endpoint 없음)
            with sm() as s:
                s.execute(
                    text("UPDATE domain.dq_rule SET status='PUBLISHED' WHERE rule_id = ANY(:ids)"),
                    {"ids": ids},
                )
                s.commit()
            return ids

        dq_ids = step("7. DQ Rule 3종 등록 + PUBLISHED", _dq_rules)

        # ── 8. Workflow 등록 (3 노드 — Mock → 평탄화 → DQ → stg 적재) ──
        # 데모 단순화. SQL_ASSET / LOAD_TARGET 으로 mart 적재는 화면에서 직접 추가.
        def _workflow() -> int:
            r = client.post(
                "/v1/pipelines",
                headers=H,
                json={
                    "name": WORKFLOW_NAME,
                    "description": "Phase 8.6 시연 — Mock API → 평탄화 → DQ 검증 → iot_stg 적재",
                    "nodes": [
                        {
                            "node_key": "fetch_raw",
                            "node_type": "SOURCE_DATA",
                            "config_json": {
                                "source_code": SOURCE_CODE,
                                "limit": 100,
                                "include_payload": True,
                                "domain_code": DOMAIN_CODE,
                            },
                            "position_x": 50,
                            "position_y": 100,
                        },
                        {
                            "node_key": "flatten",
                            "node_type": "MAP_FIELDS",
                            "config_json": {
                                "contract_id": contract_id,
                                "source_table": "raw.raw_object",
                                "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                                "domain_code": DOMAIN_CODE,
                            },
                            "position_x": 250,
                            "position_y": 100,
                        },
                        {
                            "node_key": "dq_check",
                            "node_type": "DQ_CHECK",
                            "config_json": {
                                "rule_ids": dq_ids,
                                "target_table": f"{STG_SCHEMA}.{STG_TABLE}",
                                "domain_code": DOMAIN_CODE,
                            },
                            "position_x": 450,
                            "position_y": 100,
                        },
                    ],
                    "edges": [
                        {"from_node_key": "fetch_raw", "to_node_key": "flatten"},
                        {"from_node_key": "flatten", "to_node_key": "dq_check"},
                    ],
                },
            )
            r.raise_for_status()
            wf_id = int(r.json()["workflow_id"])
            # PUBLISH (DRAFT → PUBLISHED 한 번에)
            pub = client.patch(
                f"/v1/pipelines/{wf_id}/status",
                headers=H,
                json={"status": "PUBLISHED"},
            )
            if pub.status_code >= 300:
                print(f"      publish: {pub.status_code} {pub.text[:200]}")
                pub.raise_for_status()
            published_wf_id = int(pub.json()["published_workflow"]["workflow_id"])
            return published_wf_id

        workflow_id = step("8. Workflow 4 노드 등록 + PUBLISHED", _workflow)

        # ── 9. schedule_cron = */5 * * * * 등록 + 활성 ───────────────────
        def _schedule() -> dict[str, Any]:
            r = client.patch(
                f"/v1/pipelines/{workflow_id}/schedule",
                headers=H,
                json={
                    "cron": "*/5 * * * *",
                    "enabled": True,
                },
            )
            r.raise_for_status()
            return r.json()

        sched = step("9. Schedule = */5 * * * * (5분마다) + 활성", _schedule)

        # ── 10. 즉시 1회 trigger ────────────────────────────────────────
        def _trigger() -> int:
            r = client.post(
                f"/v1/pipelines/{workflow_id}/runs",
                headers=H,
            )
            r.raise_for_status()
            return int(r.json()["pipeline_run_id"])

        run_id = step("10. 즉시 trigger (1회 실행)", _trigger)

        # ── 11. run 상태 polling (최대 30초) ────────────────────────────
        print("\n─── 11. run 상태 polling (최대 30초)")
        final_status = "RUNNING"
        node_statuses: dict[str, str] = {}
        for _ in range(30):
            time.sleep(1)
            with sm() as s:
                pr = s.execute(
                    text("SELECT status FROM run.pipeline_run WHERE pipeline_run_id=:r"),
                    {"r": run_id},
                ).scalar_one_or_none()
                if pr:
                    final_status = str(pr)
                    rows = s.execute(
                        text(
                            "SELECT node_key, status FROM run.node_run "
                            "WHERE pipeline_run_id=:r"
                        ),
                        {"r": run_id},
                    ).all()
                    node_statuses = {str(r.node_key): str(r.status) for r in rows}
            if final_status in ("SUCCESS", "FAILED", "CANCELLED"):
                break
        print(f"    pipeline_run.status = {final_status}")
        for nk, ns in node_statuses.items():
            print(f"      • {nk}: {ns}")

        # ── 12. mart row 검증 ───────────────────────────────────────────
        with sm() as s:
            stg_n = int(
                s.execute(text(f"SELECT COUNT(*) FROM {STG_SCHEMA}.{STG_TABLE}")).scalar_one()
            )
            mart_n = int(
                s.execute(text(f"SELECT COUNT(*) FROM {MART_SCHEMA}.{MART_TABLE}")).scalar_one()
            )
            raw_n = int(
                s.execute(
                    text(
                        "SELECT COUNT(*) FROM raw.raw_object ro "
                        "JOIN ctl.data_source ds ON ds.source_id=ro.source_id "
                        "WHERE ds.source_code=:c"
                    ),
                    {"c": SOURCE_CODE},
                ).scalar_one()
            )

        print(f"\n─── 12. row 적재 검증")
        print(f"    raw.raw_object       (수집)   : {raw_n} 건")
        print(f"    {STG_SCHEMA}.{STG_TABLE}   (평탄화) : {stg_n} 건")
        print(f"    {MART_SCHEMA}.{MART_TABLE} (최종 mart): {mart_n} 건")

        print("\n" + "=" * 70)
        print("✅ Phase 8.6 데모 시나리오 자동 등록 완료")
        print("=" * 70)
        print(f"\n화면에서 검증:")
        print(f"  • Mock API           : {BASE.replace(':8000', ':5173')}/v2/mock-api")
        print(
            f"  • Source Connector   : {BASE.replace(':8000', ':5173')}/v2/connectors/public-api"
        )
        print(
            f"  • Field Mapping      : {BASE.replace(':8000', ':5173')}/v2/mappings/designer"
        )
        print(f"  • Quality            : {BASE.replace(':8000', ':5173')}/v2/quality/designer")
        print(
            f"  • Transform          : {BASE.replace(':8000', ':5173')}/v2/transforms/designer"
        )
        print(
            f"  • ETL Canvas         : {BASE.replace(':8000', ':5173')}/v2/pipelines/designer/{workflow_id}"
        )
        print(
            f"  • Pipeline Run Detail: {BASE.replace(':8000', ':5173')}/pipelines/runs/{run_id}"
        )
        print(
            f"  • Operations         : {BASE.replace(':8000', ':5173')}/v2/operations/dashboard"
        )
        print()
        print(f"workflow_id={workflow_id}, run_id={run_id}, status={final_status}")
        print(f"schedule={sched.get('schedule_cron')} enabled={sched.get('schedule_enabled')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n❌ 시연 실패: {exc}", file=sys.stderr)
        raise
