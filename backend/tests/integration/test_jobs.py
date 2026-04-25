"""작업 조회 API 통합 테스트 — 실 PG."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _ingest_n(
    client: TestClient,
    auth: dict[str, str],
    code: str,
    n: int,
    *,
    base_payload: dict[str, object] | None = None,
) -> list[int]:
    """수집 N건 실행 후 raw_object_id 목록 반환 (job 도 동일 갯수 생성)."""
    base = base_payload or {"sku": "TEST"}
    raw_ids: list[int] = []
    for i in range(n):
        body = {**base, "_seq": i}
        r = client.post(f"/v1/ingest/api/{code}", json=body, headers=auth)
        assert r.status_code == 201, r.text
        raw_ids.append(r.json()["raw_object_id"])
    return raw_ids


# ---------------------------------------------------------------------------
# GET /v1/jobs
# ---------------------------------------------------------------------------
def test_list_jobs_filter_by_source_id(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    source_id = active_source["source_id"]

    _ingest_n(it_client, operator_auth, code, 3)

    r = it_client.get(f"/v1/jobs?source_id={source_id}&limit=10", headers=operator_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 3
    assert all(j["source_id"] == source_id for j in body)
    assert all(j["status"] == "SUCCESS" for j in body)
    assert all(j["job_type"] == "ON_DEMAND" for j in body)


def test_list_jobs_pagination(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    source_id = active_source["source_id"]
    _ingest_n(it_client, operator_auth, code, 5)

    r = it_client.get(f"/v1/jobs?source_id={source_id}&limit=2&offset=0", headers=operator_auth)
    page1 = r.json()
    assert len(page1) == 2

    r = it_client.get(f"/v1/jobs?source_id={source_id}&limit=2&offset=2", headers=operator_auth)
    page2 = r.json()
    assert len(page2) == 2
    # 다른 page → job_id 다름
    page1_ids = {j["job_id"] for j in page1}
    page2_ids = {j["job_id"] for j in page2}
    assert page1_ids.isdisjoint(page2_ids)


def test_list_jobs_filter_by_status(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    source_id = active_source["source_id"]
    _ingest_n(it_client, operator_auth, code, 2)

    # 수집 API 가 만드는 job 은 항상 SUCCESS — 그 필터로 수신 확인.
    r = it_client.get(f"/v1/jobs?source_id={source_id}&status=SUCCESS", headers=operator_auth)
    assert r.status_code == 200
    assert len(r.json()) == 2

    # 다른 status → 0 건.
    r = it_client.get(f"/v1/jobs?source_id={source_id}&status=FAILED", headers=operator_auth)
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /v1/jobs/{id}
# ---------------------------------------------------------------------------
def test_get_job_by_id(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    _ingest_n(it_client, operator_auth, code, 1)

    # source_id 로 list → 첫 건의 job_id 추출
    r = it_client.get(f"/v1/jobs?source_id={active_source['source_id']}", headers=operator_auth)
    job_id = r.json()[0]["job_id"]

    r = it_client.get(f"/v1/jobs/{job_id}", headers=operator_auth)
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["source_id"] == active_source["source_id"]
    assert body["status"] == "SUCCESS"
    assert "started_at" in body and body["started_at"] is not None
    assert "finished_at" in body and body["finished_at"] is not None


def test_get_unknown_job_is_404(it_client: TestClient, operator_auth: dict[str, str]) -> None:
    r = it_client.get("/v1/jobs/999999999", headers=operator_auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_jobs_unauthenticated_is_401(it_client: TestClient) -> None:
    r = it_client.get("/v1/jobs")
    assert r.status_code == 401


def test_jobs_viewer_is_403(
    it_client: TestClient,
    viewer_auth: dict[str, str],
) -> None:
    r = it_client.get("/v1/jobs", headers=viewer_auth)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
