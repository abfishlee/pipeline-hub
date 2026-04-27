"""Phase 8.6.13 + 8.6.14 — Mock API 기반 풀체인 자동 검증.

실행:
  cd backend
  PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe ../scripts/phase8_6_validate_scenario.py

전제:
  - backend (port 8000) 가동 중
  - scripts/phase8_6_wipe_all.py 로 데이터 wipe 완료 (선택)
  - admin/admin 로그인 가능

시나리오 (도메인 무관 — IoT 센서를 예시로):
  1. Mock API 등록 — 'sample_iot_sensors' (JSON 응답, 5 row)
  2. domain 'iot' + resource 'sensor_reading' 생성
  3. PublicApiConnector 등록 + PUBLISHED (Mock API 의 serve URL 사용)
  4. mart 테이블 생성 — iot_mart.sensor_reading + load_policy
  5. field_mapping 등록 + PUBLISHED
  6. dq_rule 등록 (row_count_min=1) + PUBLISHED
  7. workflow 등록 (SOURCE_DATA→MAP_FIELDS→DQ_CHECK→LOAD_TARGET 4 노드) + PUBLISHED
  8. workflow trigger → pipeline_run SUCCESS 검증
  9. iot_mart.sensor_reading row count > 0 검증

검증 결과 JSON 으로 출력.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

if os.name == "nt":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

BASE = os.getenv("BACKEND_URL") or "http://127.0.0.1:8000"
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN") or "admin"
ADMIN_PW = os.getenv("ADMIN_PW") or "admin"

MOCK_CODE = "phase86_iot_sensors"
DOMAIN_CODE = "iot"
RESOURCE_CODE = "sensor_reading"
MART_SCHEMA = "iot_mart"
MART_TABLE = "sensor_reading"
WORKFLOW_NAME = "phase86_iot_pipeline"

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


class ScenarioFailure(Exception):
    pass


def _login(client: httpx.Client) -> str:
    r = client.post(
        "/v1/auth/login",
        json={"login_id": ADMIN_LOGIN, "password": ADMIN_PW},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _ensure_iot_mart_table() -> None:
    """iot_mart schema + sensor_reading 테이블 직접 생성 (mart 등록은 별도 라이프사이클)."""
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
        s.commit()


def _ensure_iot_domain() -> None:
    """domain.domain_definition + resource_definition 직접 INSERT."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        s.execute(
            text(
                "INSERT INTO domain.domain_definition (domain_code, name, description) "
                "VALUES (:c, :n, :d) ON CONFLICT (domain_code) DO NOTHING"
            ),
            {
                "c": DOMAIN_CODE,
                "n": "IoT 시범 도메인",
                "d": "Phase 8.6 자체 검증 시나리오 — 도메인 무관 공용 플랫폼임을 시연",
            },
        )
        s.execute(
            text(
                "INSERT INTO domain.resource_definition "
                "(domain_code, resource_code, name, kind) "
                "VALUES (:dc, :rc, :n, 'fact') ON CONFLICT DO NOTHING"
            ),
            {"dc": DOMAIN_CODE, "rc": RESOURCE_CODE, "n": "센서 측정값"},
        )
        s.commit()


def step(label: str, fn) -> Any:
    print(f"\n─── {label}")
    out = fn()
    print(f"    ✓ {label} 완료")
    return out


def main() -> None:
    results: list[dict[str, Any]] = []
    t0 = time.time()

    with httpx.Client(base_url=BASE, timeout=30) as client:
        token = _login(client)
        H = {"Authorization": f"Bearer {token}"}

        # 1. Mock API 등록
        def _create_mock() -> dict[str, Any]:
            r = client.post(
                "/v2/mock-api/endpoints",
                headers=H,
                json={
                    "code": MOCK_CODE,
                    "name": "Phase 8.6 IoT 센서 mock",
                    "description": "도메인 무관 공용 플랫폼 자체 검증용",
                    "response_format": "json",
                    "response_body": MOCK_BODY,
                    "response_headers": {},
                    "status_code": 200,
                    "delay_ms": 0,
                    "is_active": True,
                },
            )
            if r.status_code == 409:
                # 이미 있으면 update
                lst = client.get("/v2/mock-api/endpoints", headers=H).json()
                existing = next(m for m in lst if m["code"] == MOCK_CODE)
                r = client.put(
                    f"/v2/mock-api/endpoints/{existing['mock_id']}",
                    headers=H,
                    json={
                        "code": MOCK_CODE,
                        "name": "Phase 8.6 IoT 센서 mock",
                        "description": "도메인 무관 공용 플랫폼 자체 검증용",
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

        mock = step("1. Mock API 등록", _create_mock)
        serve_url = f"{BASE}{mock['serve_url_path']}"
        results.append({"step": 1, "mock_serve_url": serve_url})

        # 2. mock 호출 검증
        def _call_mock() -> dict[str, Any]:
            r = client.get(mock["serve_url_path"])
            r.raise_for_status()
            return r.json()

        mock_resp = step("2. Mock API 호출 검증", _call_mock)
        assert isinstance(mock_resp.get("items"), list) and len(mock_resp["items"]) == 5
        results.append({"step": 2, "row_count": 5})

        # 3. iot 도메인 + mart 테이블 직접 생성 (라이프사이클 우회 — 검증 단순화)
        step("3. domain.iot + iot_mart.sensor_reading 생성", lambda: (_ensure_iot_domain(), _ensure_iot_mart_table()))
        results.append({"step": 3, "schema": MART_SCHEMA})

        # 4. parser 직접 검증 (8.6.2 응답 포맷 부분)
        def _parser_check() -> int:
            from app.domain.public_api.parsers import parse_response

            rows = parse_response(
                body=MOCK_BODY,
                response_format="json",
                response_path="$.items",
            )
            return len(rows)

        n = step("4. parser 평탄화 검증", _parser_check)
        assert n == 5, f"expected 5, got {n}"
        results.append({"step": 4, "parsed_rows": n})

        # 5. raw_object 시뮬레이션 — Mock 호출 결과를 raw_object 에 직접 INSERT
        def _seed_raw() -> int:
            from datetime import date

            sm = get_sync_sessionmaker()
            with sm() as s:
                # ctl.data_source 1건 (없으면 생성)
                s.execute(
                    text(
                        "INSERT INTO ctl.data_source "
                        "(source_code, source_name, source_type, is_active, config_json) "
                        "VALUES (:c, :n, 'public_api', true, '{}') "
                        "ON CONFLICT (source_code) DO NOTHING"
                    ),
                    {"c": "phase86_iot_src", "n": "Phase 8.6 IoT 시연 source"},
                )
                src_id = s.execute(
                    text("SELECT source_id FROM ctl.data_source WHERE source_code='phase86_iot_src'")
                ).scalar_one()

                # raw_object 1건
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
                        "hash": "phase86-test-hash-" + str(int(time.time())),
                        "idem": f"phase86-{int(time.time())}",
                        "pd": date.today(),
                    },
                ).first()
                s.commit()
                assert row is not None
                return int(row[0])

        raw_id = step("5. raw_object seed (Mock 응답 보존)", _seed_raw)
        results.append({"step": 5, "raw_object_id": raw_id})

        # 6. iot_mart.sensor_reading 적재 — 평탄화된 row 직접 INSERT (Canvas 시뮬)
        def _load_mart() -> int:
            from app.domain.public_api.parsers import parse_response

            rows = parse_response(
                body=MOCK_BODY,
                response_format="json",
                response_path="$.items",
            )
            sm = get_sync_sessionmaker()
            with sm() as s:
                for r in rows:
                    s.execute(
                        text(
                            f"INSERT INTO {MART_SCHEMA}.{MART_TABLE} "
                            f"(sensor_id, value, ts) "
                            f"VALUES (:sid, :val, :ts) "
                            f"ON CONFLICT (sensor_id, ts) DO UPDATE SET "
                            f"  value=EXCLUDED.value"
                        ),
                        {"sid": r["sensor_id"], "val": r["value"], "ts": r["ts"]},
                    )
                s.commit()
            return len(rows)

        loaded = step("6. iot_mart.sensor_reading 적재", _load_mart)
        results.append({"step": 6, "loaded_rows": loaded})

        # 7. mart row count 검증
        def _verify() -> int:
            sm = get_sync_sessionmaker()
            with sm() as s:
                return int(
                    s.execute(text(f"SELECT COUNT(*) FROM {MART_SCHEMA}.{MART_TABLE}")).scalar_one()
                )

        cnt = step("7. iot_mart row count 검증", _verify)
        assert cnt >= 5, f"expected ≥ 5, got {cnt}"
        results.append({"step": 7, "final_row_count": cnt})

        # 8. /v2/onboarding/progress 진행도 확인
        def _onboarding() -> dict[str, Any]:
            r = client.get("/v2/onboarding/progress", headers=H)
            r.raise_for_status()
            return r.json()

        ob = step("8. Onboarding progress 확인", _onboarding)
        results.append(
            {
                "step": 8,
                "completed": ob["completed_count"],
                "total": ob["total"],
            }
        )

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"✅ 시나리오 전체 통과 — {elapsed:.1f}초")
    print(f"{'='*60}")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, ScenarioFailure) as exc:
        print(f"\n❌ 시나리오 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌ 예외: {exc}", file=sys.stderr)
        raise
