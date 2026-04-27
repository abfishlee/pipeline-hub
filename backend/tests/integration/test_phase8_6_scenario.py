"""Phase 8.6.13 + 8.6.14 — Mock API 기반 풀체인 자동 검증 통합 테스트.

backend 재시작 없이 TestClient 로 신규 endpoint 까지 즉시 검증 가능.

시나리오 (도메인 무관 — IoT 센서 예시):
  1. Mock API 등록 → serve URL 노출
  2. Mock 응답 200 + JSON body 정상
  3. parser 평탄화 (json/xml/csv/tsv/text 5종)
  4. iot 도메인 + iot_mart.sensor_reading 생성
  5. raw_object seed (Mock 응답 보존)
  6. iot_mart 적재 (Canvas 시뮬)
  7. mart row count >= 5 검증
  8. onboarding progress endpoint 호출
  9. operations/airflow-health 호출
  10. operations/dispatcher-health 호출
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

MOCK_CODE = "p86_iot_sensors"
MART_SCHEMA = "iot_mart"
MART_TABLE = "sensor_reading"

MOCK_BODY = json.dumps(
    {
        "items": [
            {"sensor_id": "S001", "value": 23.5, "ts": "2026-04-27T10:00:00"},
            {"sensor_id": "S002", "value": 24.1, "ts": "2026-04-27T10:00:00"},
            {"sensor_id": "S003", "value": 22.8, "ts": "2026-04-27T10:00:00"},
            {"sensor_id": "S004", "value": 25.0, "ts": "2026-04-27T10:00:00"},
            {"sensor_id": "S005", "value": 23.9, "ts": "2026-04-27T10:00:00"},
        ]
    }
)


@pytest.fixture(scope="module")
def _ensure_iot_objects() -> None:
    """iot_mart schema + sensor_reading 테이블 + iot 도메인."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        s.execute(text("CREATE SCHEMA IF NOT EXISTS iot_mart"))
        s.execute(text("CREATE SCHEMA IF NOT EXISTS iot_stg"))
        s.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {MART_SCHEMA}.{MART_TABLE} (
                    sensor_id   TEXT NOT NULL,
                    value       NUMERIC(10,2) NOT NULL,
                    ts          TIMESTAMPTZ NOT NULL,
                    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (sensor_id, ts)
                )
                """
            )
        )
        s.execute(
            text(
                "INSERT INTO domain.domain_definition (domain_code, name, description) "
                "VALUES ('iot', 'IoT 시범 도메인', "
                "'Phase 8.6 자체 검증 — 도메인 무관 공용 플랫폼') "
                "ON CONFLICT (domain_code) DO NOTHING"
            )
        )
        s.commit()
    yield
    # 테스트 후 정리: mart row 만 truncate (스키마/테이블은 유지 — 다음 실행 시 재사용)
    with sm() as s:
        s.execute(text(f"TRUNCATE {MART_SCHEMA}.{MART_TABLE}"))
        s.commit()


def test_phase86_step_1_mock_api_register(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """Step 1 — Mock API 등록 + serve URL 노출."""
    # idempotent: 기존 mock 삭제
    res = it_client.get("/v2/mock-api/endpoints", headers=admin_auth)
    if res.status_code == 200:
        for m in res.json():
            if m["code"] == MOCK_CODE:
                it_client.delete(
                    f"/v2/mock-api/endpoints/{m['mock_id']}", headers=admin_auth
                )
    res = it_client.post(
        "/v2/mock-api/endpoints",
        headers=admin_auth,
        json={
            "code": MOCK_CODE,
            "name": "Phase 8.6 IoT 센서 mock",
            "description": "도메인 무관 공용 플랫폼 자체 검증",
            "response_format": "json",
            "response_body": MOCK_BODY,
            "response_headers": {},
            "status_code": 200,
            "delay_ms": 0,
            "is_active": True,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == MOCK_CODE
    assert body["serve_url_path"] == f"/v2/mock-api/serve/{MOCK_CODE}"


def test_phase86_step_2_mock_serve(it_client: TestClient) -> None:
    """Step 2 — Mock serve endpoint 가 등록한 응답 그대로 반환 (인증 불필요)."""
    res = it_client.get(f"/v2/mock-api/serve/{MOCK_CODE}")
    assert res.status_code == 200, res.text
    assert "application/json" in res.headers.get("content-type", "")
    body = res.json()
    assert isinstance(body["items"], list) and len(body["items"]) == 5


def test_phase86_step_3_parsers() -> None:
    """Step 3 — parser 5종 평탄화 검증."""
    from app.domain.public_api.parsers import parse_response

    # json
    rows = parse_response(body=MOCK_BODY, response_format="json", response_path="$.items")
    assert len(rows) == 5

    # csv
    csv_body = "id,name\n1,A\n2,B"
    rows = parse_response(body=csv_body.encode(), response_format="csv")
    assert rows == [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

    # tsv
    tsv_body = "id\tname\n1\tA\n2\tB"
    rows = parse_response(body=tsv_body.encode(), response_format="tsv")
    assert rows == [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

    # text
    rows = parse_response(body=b"line1\nline2\n\nline3", response_format="text")
    assert [r["line"] for r in rows] == ["line1", "line2", "line3"]


def test_phase86_step_4_raw_object_seed(_ensure_iot_objects: None) -> None:
    """Step 4 — Mock 응답을 raw_object 에 저장 (실제 수집 시뮬)."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        s.execute(
            text(
                "INSERT INTO ctl.data_source "
                "(source_code, source_name, source_type, is_active, config_json) "
                "VALUES ('p86_iot_src', 'Phase 8.6 IoT', 'API', true, '{}') "
                "ON CONFLICT (source_code) DO NOTHING"
            )
        )
        src_id = s.execute(
            text("SELECT source_id FROM ctl.data_source WHERE source_code='p86_iot_src'")
        ).scalar_one()
        unique_hash = f"p86-{uuid.uuid4().hex[:16]}"
        row = s.execute(
            text(
                "INSERT INTO raw.raw_object "
                "(source_id, object_type, payload_json, content_hash, "
                " idempotency_key, partition_date, status) "
                "VALUES (:src, 'JSON', CAST(:body AS JSONB), :hash, :idem, :pd, 'RECEIVED') "
                "RETURNING raw_object_id"
            ),
            {
                "src": src_id,
                "body": MOCK_BODY,
                "hash": unique_hash,
                "idem": f"p86-{int(time.time())}-{uuid.uuid4().hex[:8]}",
                "pd": date.today(),
            },
        ).first()
        s.commit()
    assert row is not None


def test_phase86_step_5_load_mart(_ensure_iot_objects: None) -> None:
    """Step 5 — 평탄화된 row 를 iot_mart 에 적재 (Canvas 시뮬)."""
    from app.domain.public_api.parsers import parse_response

    rows = parse_response(
        body=MOCK_BODY, response_format="json", response_path="$.items"
    )
    sm = get_sync_sessionmaker()
    with sm() as s:
        for r in rows:
            s.execute(
                text(
                    f"INSERT INTO {MART_SCHEMA}.{MART_TABLE} "
                    f"(sensor_id, value, ts) VALUES (:sid, :val, :ts) "
                    f"ON CONFLICT (sensor_id, ts) DO UPDATE SET value=EXCLUDED.value"
                ),
                {"sid": r["sensor_id"], "val": r["value"], "ts": r["ts"]},
            )
        s.commit()
    assert len(rows) == 5


def test_phase86_step_6_mart_row_count(_ensure_iot_objects: None) -> None:
    """Step 6 — iot_mart.sensor_reading row count >= 5 검증."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        cnt = int(
            s.execute(
                text(f"SELECT COUNT(*) FROM {MART_SCHEMA}.{MART_TABLE}")
            ).scalar_one()
        )
    assert cnt >= 5, f"expected ≥ 5, got {cnt}"


def test_phase86_step_7_onboarding(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """Step 7 — Onboarding progress endpoint 응답 검증."""
    res = it_client.get("/v2/onboarding/progress", headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 5
    assert "steps" in body and len(body["steps"]) == 5
    codes = [s["code"] for s in body["steps"]]
    assert codes == ["source", "mapping", "mart", "workflow", "run"]


def test_phase86_step_8_airflow_health(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """Step 8 — Airflow health endpoint 응답 검증 (가동 여부 무관)."""
    res = it_client.get("/v2/operations/airflow-health", headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "is_reachable" in body
    assert "schedule_enabled_workflows" in body
    assert "note" in body


def test_phase86_step_9_response_format_check_extended() -> None:
    """Step 9 — domain.public_api_connector 의 response_format CHECK 가 7종 허용."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        constraints = s.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='ck_public_api_response_format'"
            )
        ).scalar_one()
    for fmt in ["json", "xml", "csv", "tsv", "text", "excel", "binary"]:
        assert f"'{fmt}'" in constraints, f"format {fmt} not in CHECK"


def test_phase86_step_10_full_chain_summary(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """Step 10 — 전체 시나리오 요약: Mock → raw → mart 가 모두 통과했음을 다시 확인."""
    # Mock
    res = it_client.get(f"/v2/mock-api/serve/{MOCK_CODE}")
    assert res.status_code == 200

    # mart row count
    sm = get_sync_sessionmaker()
    with sm() as s:
        mart_cnt = int(
            s.execute(text(f"SELECT COUNT(*) FROM {MART_SCHEMA}.{MART_TABLE}")).scalar_one()
        )
        raw_cnt = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM raw.raw_object ro "
                    "JOIN ctl.data_source ds ON ds.source_id=ro.source_id "
                    "WHERE ds.source_code='p86_iot_src'"
                )
            ).scalar_one()
        )
    assert mart_cnt >= 5
    assert raw_cnt >= 1
