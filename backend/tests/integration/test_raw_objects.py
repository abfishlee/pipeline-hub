"""원천 데이터 조회 API 통합 테스트 — 실 PG + MinIO."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient


def _ingest_inline(
    client: TestClient,
    auth: dict[str, str],
    code: str,
    body: dict[str, object],
) -> dict[str, object]:
    """≤64KB JSON 수집 — payload_json 인라인. 응답 dict 반환."""
    r = client.post(f"/v1/ingest/api/{code}", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _ingest_large(client: TestClient, auth: dict[str, str], code: str) -> dict[str, object]:
    """>64KB JSON 수집 — Object Storage 저장."""
    body = {"big_field": "x" * (70 * 1024), "marker": "raw-detail-test"}
    r = client.post(f"/v1/ingest/api/{code}", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /v1/raw-objects
# ---------------------------------------------------------------------------
def test_list_raw_objects_filter_by_source(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    source_id = active_source["source_id"]

    for i in range(3):
        _ingest_inline(it_client, operator_auth, code, {"i": i, "k": f"v{i}"})

    r = it_client.get(f"/v1/raw-objects?source_id={source_id}", headers=operator_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    for item in body:
        assert item["source_id"] == source_id
        assert item["object_type"] == "JSON"
        assert item["status"] == "RECEIVED"
        # 작은 JSON → inline payload, object_uri 없음
        assert item["has_inline_payload"] is True
        assert item["object_uri_present"] is False


def test_list_raw_objects_filter_by_object_type(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    source_id = active_source["source_id"]
    _ingest_inline(it_client, operator_auth, code, {"k": "v"})

    r = it_client.get(
        f"/v1/raw-objects?source_id={source_id}&object_type=JSON",
        headers=operator_auth,
    )
    assert r.status_code == 200
    assert all(it["object_type"] == "JSON" for it in r.json())

    r = it_client.get(
        f"/v1/raw-objects?source_id={source_id}&object_type=PDF",
        headers=operator_auth,
    )
    assert r.json() == []


def test_list_raw_objects_pagination(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    source_id = active_source["source_id"]
    for i in range(4):
        _ingest_inline(it_client, operator_auth, code, {"i": i})

    r = it_client.get(
        f"/v1/raw-objects?source_id={source_id}&limit=2&offset=0",
        headers=operator_auth,
    )
    page1 = r.json()
    assert len(page1) == 2

    r = it_client.get(
        f"/v1/raw-objects?source_id={source_id}&limit=2&offset=2",
        headers=operator_auth,
    )
    page2 = r.json()
    assert len(page2) == 2
    assert {x["raw_object_id"] for x in page1}.isdisjoint({x["raw_object_id"] for x in page2})


# ---------------------------------------------------------------------------
# GET /v1/raw-objects/{id}
# ---------------------------------------------------------------------------
def test_get_raw_object_inline_payload(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    body = {"sku": "DETAIL-1", "price": 9999}
    ingested = _ingest_inline(it_client, operator_auth, code, body)
    raw_id = ingested["raw_object_id"]

    r = it_client.get(f"/v1/raw-objects/{raw_id}", headers=operator_auth)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["raw_object_id"] == raw_id
    assert detail["object_type"] == "JSON"
    assert detail["payload_json"] == body
    assert detail["object_uri"] is None
    assert detail["download_url"] is None
    assert "content_hash" in detail


def test_get_raw_object_object_storage_with_presigned_url(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    ingested = _ingest_large(it_client, operator_auth, code)
    raw_id = ingested["raw_object_id"]

    r = it_client.get(f"/v1/raw-objects/{raw_id}", headers=operator_auth)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["payload_json"] is None
    assert detail["object_uri"] is not None
    assert detail["object_uri"].startswith(("s3://", "nos://"))
    assert detail["download_url"] is not None
    assert detail["download_url"].startswith("http")

    # presigned URL 로 실제 다운로드 가능 → 본문에 marker 포함
    r2 = httpx.get(detail["download_url"], timeout=10.0)
    assert r2.status_code == 200
    assert b"raw-detail-test" in r2.content


def test_get_raw_object_with_explicit_partition_date(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    ingested = _ingest_inline(it_client, operator_auth, code, {"x": 1})
    raw_id = ingested["raw_object_id"]

    # list 에서 partition_date 확인
    r = it_client.get(
        f"/v1/raw-objects?source_id={active_source['source_id']}",
        headers=operator_auth,
    )
    pdate = r.json()[0]["partition_date"]

    r = it_client.get(
        f"/v1/raw-objects/{raw_id}?partition_date={pdate}",
        headers=operator_auth,
    )
    assert r.status_code == 200
    assert r.json()["partition_date"] == pdate


def test_get_unknown_raw_object_is_404(
    it_client: TestClient, operator_auth: dict[str, str]
) -> None:
    r = it_client.get("/v1/raw-objects/999999999", headers=operator_auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_raw_objects_unauthenticated_is_401(it_client: TestClient) -> None:
    r = it_client.get("/v1/raw-objects")
    assert r.status_code == 401


def test_raw_objects_viewer_is_403(it_client: TestClient, viewer_auth: dict[str, str]) -> None:
    r = it_client.get("/v1/raw-objects", headers=viewer_auth)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
