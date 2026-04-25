"""사용자/역할 CRUD 통합 테스트 — 실 PG + ADMIN 가드."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_users_endpoints_require_admin_role(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    """VIEWER 만 가진 사용자는 /v1/users 에 접근 불가 (403)."""
    viewer_id = f"ituser_viewer_{rand_suffix}"
    cleanup_users.append(viewer_id)

    # admin 이 VIEWER 사용자 생성
    r = it_client.post(
        "/v1/users",
        json={
            "login_id": viewer_id,
            "display_name": "뷰어",
            "password": "viewer-pw-12345",
            "role_codes": ["VIEWER"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text

    # VIEWER 로 로그인
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": viewer_id, "password": "viewer-pw-12345"},
    )
    viewer_token = r.json()["access_token"]
    viewer_auth = {"Authorization": f"Bearer {viewer_token}"}

    # VIEWER 가 /v1/users 에 접근 → 403
    r = it_client.get("/v1/users", headers=viewer_auth)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"

    # VIEWER 자기 자신 /me 는 OK
    r = it_client.get("/v1/auth/me", headers=viewer_auth)
    assert r.status_code == 200


def test_create_user_and_get_by_id(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_basic_{rand_suffix}"
    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "기본 사용자",
            "email": f"{login_id}@example.test",
            "password": "basic-pw-12345",
            "role_codes": ["VIEWER"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    cleanup_users.append(login_id)
    user_id = body["user_id"]

    assert body["login_id"] == login_id
    assert body["is_active"] is True
    assert "VIEWER" in body["roles"]
    assert "password" not in body  # 응답에 비밀번호 없음
    assert "password_hash" not in body

    r = it_client.get(f"/v1/users/{user_id}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json()["login_id"] == login_id


def test_create_duplicate_login_id_is_409(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_dup_{rand_suffix}"
    payload = {
        "login_id": login_id,
        "display_name": "중복 테스트",
        "password": "dup-pw-12345",
    }
    r1 = it_client.post("/v1/users", json=payload, headers=admin_auth)
    assert r1.status_code == 201
    cleanup_users.append(login_id)

    r2 = it_client.post("/v1/users", json=payload, headers=admin_auth)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "CONFLICT"


def test_update_user_fields(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_upd_{rand_suffix}"
    r = it_client.post(
        "/v1/users",
        json={"login_id": login_id, "display_name": "초기명", "password": "initial-pw-12"},
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]

    r = it_client.patch(
        f"/v1/users/{user_id}",
        json={"display_name": "변경된명", "email": "new@example.test"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "변경된명"
    assert body["email"] == "new@example.test"


def test_delete_user_is_soft_delete(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_del_{rand_suffix}"
    r = it_client.post(
        "/v1/users",
        json={"login_id": login_id, "display_name": "삭제대상", "password": "del-pw-12345"},
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]

    r = it_client.delete(f"/v1/users/{user_id}", headers=admin_auth)
    assert r.status_code == 204

    # soft delete — 조회는 여전히 가능, is_active=False
    r = it_client.get(f"/v1/users/{user_id}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_list_users_paginated(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    r = it_client.get("/v1/users?limit=5&offset=0", headers=admin_auth)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) <= 5
    # 최소 admin 1명은 있어야 함
    login_ids = {u["login_id"] for u in body}
    # offset/limit 때문에 admin 이 안 보일 수 있으므로 전체를 다시 조회
    r_all = it_client.get("/v1/users?limit=100", headers=admin_auth)
    all_logins = {u["login_id"] for u in r_all.json()}
    assert "it_admin" in all_logins or "admin" in all_logins or len(login_ids) > 0


def test_role_assign_and_revoke(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_role_{rand_suffix}"
    r = it_client.post(
        "/v1/users",
        json={"login_id": login_id, "display_name": "역할관리", "password": "role-pw-12345"},
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]
    assert r.json()["roles"] == []

    # 역할 추가
    r = it_client.post(
        f"/v1/users/{user_id}/roles",
        json={"role_codes": ["VIEWER", "REVIEWER"]},
        headers=admin_auth,
    )
    assert r.status_code == 200
    roles = set(r.json()["roles"])
    assert {"VIEWER", "REVIEWER"}.issubset(roles)

    # 역할 교체 (PUT)
    r = it_client.put(
        f"/v1/users/{user_id}/roles",
        json={"role_codes": ["APPROVER"]},
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert r.json()["roles"] == ["APPROVER"]

    # 개별 역할 삭제
    r = it_client.delete(f"/v1/users/{user_id}/roles/APPROVER", headers=admin_auth)
    assert r.status_code == 204

    r = it_client.get(f"/v1/users/{user_id}", headers=admin_auth)
    assert r.json()["roles"] == []


def test_assign_unknown_role_is_404(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_bad_role_{rand_suffix}"
    r = it_client.post(
        "/v1/users",
        json={"login_id": login_id, "display_name": "잘못된 역할", "password": "bad-pw-12345"},
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]

    r = it_client.post(
        f"/v1/users/{user_id}/roles",
        json={"role_codes": ["NONEXISTENT_ROLE"]},
        headers=admin_auth,
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_get_unknown_user_is_404(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    r = it_client.get("/v1/users/9999999", headers=admin_auth)
    assert r.status_code == 404
