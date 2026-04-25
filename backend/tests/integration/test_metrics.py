"""Prometheus 메트릭 + audit.access_log 통합 테스트."""

from __future__ import annotations

import re
import time

import psycopg
from fastapi.testclient import TestClient

from app.config import Settings

from .conftest import _sync_url


# ---------------------------------------------------------------------------
# /metrics 엔드포인트
# ---------------------------------------------------------------------------
def test_metrics_endpoint_returns_prometheus_format(it_client: TestClient) -> None:
    r = it_client.get("/metrics")
    assert r.status_code == 200
    # Prometheus exposition format header
    ct = r.headers.get("content-type", "")
    assert ct.startswith("text/plain"), ct
    body = r.text
    # 표준 메트릭 이름 + HELP/TYPE 메타데이터 포함
    assert "# HELP http_requests_total" in body
    assert "# TYPE http_requests_total counter" in body
    assert "# HELP http_request_duration_seconds" in body
    assert "ingest_requests_total" in body  # 정의만 있어도 OK (데이터 없으면 빈 라벨셋)


def test_metrics_endpoint_does_not_require_auth(it_client: TestClient) -> None:
    """`/metrics` 는 인증 없이 접근 가능 (내부 scrape 전용)."""
    r = it_client.get("/metrics")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Counter 증가 검증
# ---------------------------------------------------------------------------
_INGEST_COUNTER_RE = re.compile(
    r'ingest_requests_total\{[^}]*kind="api"[^}]*status="created"[^}]*\}\s+([\d.eE+-]+)'
)


def _sum_ingest_created_counter(metrics_text: str, source_code: str) -> float:
    """주어진 source_code 의 created 카운터 값 합산. 없으면 0.0."""
    total = 0.0
    for line in metrics_text.splitlines():
        if not line.startswith("ingest_requests_total{"):
            continue
        if (
            f'source_code="{source_code}"' in line
            and 'kind="api"' in line
            and 'status="created"' in line
        ):
            m = re.search(r"\}\s+([\d.eE+-]+)$", line)
            if m:
                total += float(m.group(1))
    return total


def test_ingest_increments_counter(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = str(active_source["source_code"])
    before_text = it_client.get("/metrics").text
    before = _sum_ingest_created_counter(before_text, code)

    r = it_client.post(
        f"/v1/ingest/api/{code}",
        json={"sku": "METRICS-INC", "v": 42},
        headers=operator_auth,
    )
    assert r.status_code == 201, r.text

    after_text = it_client.get("/metrics").text
    after = _sum_ingest_created_counter(after_text, code)
    assert after == before + 1, (
        f"created counter delta != 1 (before={before}, after={after}, " f"source={code})"
    )


def test_dedup_increments_dedup_counter(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = str(active_source["source_code"])
    body = {"k": "DEDUP-METRICS"}
    # 1차 — 신규
    r1 = it_client.post(f"/v1/ingest/api/{code}", json=body, headers=operator_auth)
    assert r1.status_code == 201

    metrics_before = it_client.get("/metrics").text
    dedup_before = _count_dedup_total(metrics_before, code, "api")

    # 2차 — content_hash dedup
    r2 = it_client.post(f"/v1/ingest/api/{code}", json=body, headers=operator_auth)
    assert r2.status_code == 200
    assert r2.json()["dedup"] is True

    metrics_after = it_client.get("/metrics").text
    dedup_after = _count_dedup_total(metrics_after, code, "api")
    assert dedup_after == dedup_before + 1


def _count_dedup_total(text: str, source_code: str, kind: str) -> float:
    total = 0.0
    for line in text.splitlines():
        if not line.startswith("ingest_dedup_total{"):
            continue
        if f'source_code="{source_code}"' in line and f'kind="{kind}"' in line:
            m = re.search(r"\}\s+([\d.eE+-]+)$", line)
            if m:
                total += float(m.group(1))
    return total


def test_http_request_counter_records_path_template(
    it_client: TestClient, operator_auth: dict[str, str]
) -> None:
    """`/v1/users/123` 같은 raw URL 이 아니라 라우트 템플릿이 라벨로 들어가는지 확인."""
    # 미존재 사용자 — 어쨌든 라우트 매칭은 됨, 응답은 404
    it_client.get("/v1/users/999999999", headers=operator_auth)
    text = it_client.get("/metrics").text

    # 템플릿 형식 라벨 존재
    assert 'path="/v1/users/{user_id}"' in text
    # 원시 ID 라벨 부재 (cardinality 폭발 방지 검증)
    assert 'path="/v1/users/999999999"' not in text


# ---------------------------------------------------------------------------
# audit.access_log 미들웨어
# ---------------------------------------------------------------------------
def test_access_log_records_v1_request(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
    integration_settings: Settings,
) -> None:
    """수집 1건 후 audit.access_log 에 row 가 비동기 INSERT 되었는지 확인.

    create_task 가 fire-and-forget 이라 작은 폴링 루프로 기다림.
    """
    code = str(active_source["source_code"])
    request_id = "it-access-log-test-001"
    r = it_client.post(
        f"/v1/ingest/api/{code}",
        json={"k": "access-log-marker"},
        headers={**operator_auth, "X-Request-ID": request_id},
    )
    assert r.status_code == 201

    # 비동기 INSERT 가 commit 될 때까지 최대 5초 대기.
    deadline = time.monotonic() + 5.0
    row: tuple[object, ...] | None = None
    while time.monotonic() < deadline:
        with (
            psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                """
                SELECT method, path, status_code, request_id, duration_ms
                  FROM audit.access_log
                 WHERE request_id = %s
                 ORDER BY occurred_at DESC
                 LIMIT 1
                """,
                (request_id,),
            )
            row = cur.fetchone()
        if row is not None:
            break
        time.sleep(0.2)

    assert row is not None, (
        "access_log row not found within 5s — middleware fire-and-forget "
        "task may have failed silently"
    )
    method, path, status_code, req_id, duration_ms = row
    assert method == "POST"
    assert path == f"/v1/ingest/api/{code}"
    assert status_code == 201
    assert req_id == request_id
    assert isinstance(duration_ms, int) and duration_ms >= 0


def test_health_endpoints_excluded_from_access_log(
    it_client: TestClient,
    integration_settings: Settings,
) -> None:
    """`/healthz` 는 access_log 에 기록되지 않는다 (노이즈 제외)."""
    request_id = "it-health-exclude-001"
    it_client.get("/healthz", headers={"X-Request-ID": request_id})
    # 전파 시간 여유.
    time.sleep(0.5)
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT count(*) FROM audit.access_log WHERE request_id = %s",
            (request_id,),
        )
        cnt = cur.fetchone()[0]  # type: ignore[index]
    assert cnt == 0
