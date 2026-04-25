"""데이터 소스 관리 API 통합 테스트 — 실 PG + RBAC."""

from __future__ import annotations

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def test_create_source_minimal_admin_ok(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "테스트 API 수집",
            "source_type": "API",
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    cleanup_sources.append(rand_source_code)
    body = r.json()
    assert body["source_code"] == rand_source_code
    assert body["source_type"] == "API"
    assert body["is_active"] is True
    assert body["config_json"] == {}
    assert body["schedule_cron"] is None
    assert body["retailer_id"] is None


def test_create_source_full_payload(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "전체 필드 테스트",
            "source_type": "CRAWLER",
            "retailer_id": 1,
            "owner_team": "data-platform",
            "is_active": False,
            "config_json": {"base_url": "https://example.test", "rate_limit": 5},
            "schedule_cron": "*/15 * * * *",
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    cleanup_sources.append(rand_source_code)
    body = r.json()
    assert body["source_type"] == "CRAWLER"
    assert body["retailer_id"] == 1
    assert body["owner_team"] == "data-platform"
    assert body["is_active"] is False
    assert body["config_json"]["base_url"] == "https://example.test"
    assert body["schedule_cron"] == "*/15 * * * *"


def test_create_duplicate_source_code_is_409(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    payload = {
        "source_code": rand_source_code,
        "source_name": "중복 1",
        "source_type": "API",
    }
    r1 = it_client.post("/v1/sources", json=payload, headers=admin_auth)
    assert r1.status_code == 201
    cleanup_sources.append(rand_source_code)

    r2 = it_client.post("/v1/sources", json=payload, headers=admin_auth)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# Validation (422)
# ---------------------------------------------------------------------------
def test_create_invalid_source_code_lowercase_is_422(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": "lowercase_not_allowed",
            "source_name": "x",
            "source_type": "API",
        },
        headers=admin_auth,
    )
    assert r.status_code == 422


def test_create_invalid_source_code_starts_with_digit_is_422(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": "1_DIGIT_FIRST",
            "source_name": "x",
            "source_type": "API",
        },
        headers=admin_auth,
    )
    assert r.status_code == 422


def test_create_invalid_source_type_is_422(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": "TEST_BAD_TYPE",
            "source_name": "x",
            "source_type": "NONEXISTENT",
        },
        headers=admin_auth,
    )
    assert r.status_code == 422


def test_create_invalid_cron_is_422(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "잘못된 크론",
            "source_type": "API",
            "schedule_cron": "not a cron expression",
        },
        headers=admin_auth,
    )
    assert r.status_code == 422


def test_create_valid_cron_accepted(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "크론 OK",
            "source_type": "API",
            "schedule_cron": "0 */6 * * *",
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_sources.append(rand_source_code)
    assert r.json()["schedule_cron"] == "0 */6 * * *"


def test_empty_cron_is_normalized_to_null(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "빈 크론",
            "source_type": "API",
            "schedule_cron": "",
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_sources.append(rand_source_code)
    assert r.json()["schedule_cron"] is None


# ---------------------------------------------------------------------------
# Read (GET list / GET by id)
# ---------------------------------------------------------------------------
def test_get_source_by_id(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "조회 테스트",
            "source_type": "DB",
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    source_id = r.json()["source_id"]

    r = it_client.get(f"/v1/sources/{source_id}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json()["source_code"] == rand_source_code


def test_get_unknown_source_is_404(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    r = it_client.get("/v1/sources/999999999", headers=admin_auth)
    assert r.status_code == 404


def test_list_sources_filter_by_type(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "필터 OCR",
            "source_type": "OCR",
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_sources.append(rand_source_code)

    r = it_client.get("/v1/sources?source_type=OCR&limit=100", headers=admin_auth)
    assert r.status_code == 200
    body = r.json()
    assert all(item["source_type"] == "OCR" for item in body)
    assert any(item["source_code"] == rand_source_code for item in body)


def test_list_sources_filter_by_inactive(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "비활성 필터",
            "source_type": "API",
            "is_active": False,
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    assert r.status_code == 201

    r = it_client.get("/v1/sources?is_active=false&limit=100", headers=admin_auth)
    assert r.status_code == 200
    assert all(item["is_active"] is False for item in r.json())


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------
def test_update_source_partial(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "원본명",
            "source_type": "API",
            "owner_team": "team-a",
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    source_id = r.json()["source_id"]

    r = it_client.patch(
        f"/v1/sources/{source_id}",
        json={"source_name": "변경된 이름", "schedule_cron": "*/30 * * * *"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source_name"] == "변경된 이름"
    assert body["schedule_cron"] == "*/30 * * * *"
    # 미제공 필드는 보존
    assert body["owner_team"] == "team-a"
    assert body["source_type"] == "API"


def test_update_source_clear_nullable_field(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    """명시적 None 으로 nullable 필드 unset (owner_team 비우기)."""
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "owner clear",
            "source_type": "API",
            "owner_team": "to-be-cleared",
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    source_id = r.json()["source_id"]
    assert r.json()["owner_team"] == "to-be-cleared"

    r = it_client.patch(
        f"/v1/sources/{source_id}",
        json={"owner_team": None},
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert r.json()["owner_team"] is None


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------
def test_delete_source_is_soft(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "삭제 대상",
            "source_type": "API",
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    source_id = r.json()["source_id"]

    r = it_client.delete(f"/v1/sources/{source_id}", headers=admin_auth)
    assert r.status_code == 204

    # 조회는 여전히 가능, is_active=False
    r = it_client.get(f"/v1/sources/{source_id}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json()["is_active"] is False


# ---------------------------------------------------------------------------
# RBAC — OPERATOR 는 read only, mutate 는 403
# ---------------------------------------------------------------------------
def test_operator_can_list_and_get(
    it_client: TestClient,
    admin_auth: dict[str, str],
    operator_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    # admin 이 source 생성 (operator 는 권한 없으므로)
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "OPER 조회 테스트",
            "source_type": "API",
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    source_id = r.json()["source_id"]

    # OPERATOR 가 list / get 가능
    r = it_client.get("/v1/sources?limit=5", headers=operator_auth)
    assert r.status_code == 200
    r = it_client.get(f"/v1/sources/{source_id}", headers=operator_auth)
    assert r.status_code == 200


def test_operator_cannot_create_403(
    it_client: TestClient,
    operator_auth: dict[str, str],
    rand_source_code: str,
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "OPER 생성 시도",
            "source_type": "API",
        },
        headers=operator_auth,
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_operator_cannot_update_or_delete_403(
    it_client: TestClient,
    admin_auth: dict[str, str],
    operator_auth: dict[str, str],
    rand_source_code: str,
    cleanup_sources: list[str],
) -> None:
    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "OPER 변경 차단",
            "source_type": "API",
        },
        headers=admin_auth,
    )
    cleanup_sources.append(rand_source_code)
    source_id = r.json()["source_id"]

    r = it_client.patch(
        f"/v1/sources/{source_id}",
        json={"source_name": "operator update attempt"},
        headers=operator_auth,
    )
    assert r.status_code == 403

    r = it_client.delete(f"/v1/sources/{source_id}", headers=operator_auth)
    assert r.status_code == 403


def test_unauthenticated_request_is_401(it_client: TestClient, rand_source_code: str) -> None:
    r = it_client.get("/v1/sources")
    assert r.status_code == 401

    r = it_client.post(
        "/v1/sources",
        json={
            "source_code": rand_source_code,
            "source_name": "no auth",
            "source_type": "API",
        },
    )
    assert r.status_code == 401
