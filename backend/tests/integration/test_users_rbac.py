"""Phase 4.0.5 — RBAC 확장 통합 테스트.

검증:
  1. GET /v1/users/roles — 8 종 role 카탈로그 반환 (Phase 3 의 5 + Phase 4 의 3).
  2. PUBLIC_READER role 부여 → JWT claim 의 roles 에 포함.
  3. PUBLIC_READER 만 가진 사용자가 /v1/users 같은 ADMIN endpoint 호출 → 403.
  4. 기존 4 role (ADMIN/APPROVER/OPERATOR/REVIEWER/VIEWER) 동작 동일 — 회귀 0.
  5. 알려지지 않은 role_code 부여 시도 → 404.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from jose import jwt


def test_list_roles_returns_eight(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    r = it_client.get("/v1/users/roles", headers=admin_auth)
    assert r.status_code == 200, r.text
    codes = {row["role_code"] for row in r.json()}
    assert codes == {
        "ADMIN",
        "APPROVER",
        "OPERATOR",
        "REVIEWER",
        "VIEWER",
        "PUBLIC_READER",
        "MART_WRITER",
        "SANDBOX_READER",
    }


def test_phase4_role_assignment_propagates_to_jwt(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    """PUBLIC_READER role 부여 후 그 사용자의 JWT claim 에 roles 포함 확인."""
    login_id = f"it_pr_{rand_suffix.lower()}"
    password = f"pw-{rand_suffix}"

    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "Public Reader",
            "password": password,
            "role_codes": ["PUBLIC_READER"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]
    assert r.json()["roles"] == ["PUBLIC_READER"]

    # 로그인 → JWT claim 검증.
    login = it_client.post(
        "/v1/auth/login",
        json={"login_id": login_id, "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    payload = jwt.get_unverified_claims(token)
    assert "PUBLIC_READER" in payload["roles"]

    # 추가 부여 — MART_WRITER + SANDBOX_READER.
    r = it_client.put(
        f"/v1/users/{user_id}/roles",
        json={"role_codes": ["PUBLIC_READER", "MART_WRITER", "SANDBOX_READER"]},
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert set(r.json()["roles"]) == {"PUBLIC_READER", "MART_WRITER", "SANDBOX_READER"}


def test_public_reader_only_user_blocked_from_admin_endpoint(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    """PUBLIC_READER 만 가진 사용자가 ADMIN endpoint (/v1/users) 호출 → 403."""
    login_id = f"it_pr_only_{rand_suffix.lower()}"
    password = f"pw-{rand_suffix}"

    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "PR only",
            "password": password,
            "role_codes": ["PUBLIC_READER"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)

    login = it_client.post("/v1/auth/login", json={"login_id": login_id, "password": password})
    pr_token = login.json()["access_token"]
    pr_auth = {"Authorization": f"Bearer {pr_token}"}

    # ADMIN 가드 endpoint — /v1/users
    listed = it_client.get("/v1/users", headers=pr_auth)
    assert listed.status_code == 403


def test_unknown_role_assign_404(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    """존재하지 않는 role_code 부여 시도 → 404."""
    login_id = f"it_bad_role_{rand_suffix.lower()}"

    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "x",
            "password": "pw-12345678",
            "role_codes": [],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]

    bad = it_client.post(
        f"/v1/users/{user_id}/roles",
        json={"role_codes": ["DOES_NOT_EXIST"]},
        headers=admin_auth,
    )
    assert bad.status_code == 404, bad.text


def test_existing_5_roles_still_work(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    """Phase 3 의 5 role 부여 + 회수 — 회귀 0 검증."""
    login_id = f"it_legacy_{rand_suffix.lower()}"
    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "legacy",
            "password": "pw-12345678",
            "role_codes": ["OPERATOR", "REVIEWER"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    cleanup_users.append(login_id)
    user_id = r.json()["user_id"]
    assert set(r.json()["roles"]) == {"OPERATOR", "REVIEWER"}

    # 회수 — REVIEWER 만 제거.
    rev = it_client.delete(f"/v1/users/{user_id}/roles/REVIEWER", headers=admin_auth)
    assert rev.status_code == 204

    # 확인.
    g = it_client.get(f"/v1/users/{user_id}", headers=admin_auth)
    assert g.json()["roles"] == ["OPERATOR"]


@pytest.mark.parametrize("role_code", ["PUBLIC_READER", "MART_WRITER", "SANDBOX_READER"])
def test_phase4_each_role_grantable(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
    role_code: str,
) -> None:
    """Phase 4 의 3 role 각각 단독 부여 가능 검증."""
    login_id = f"it_{role_code.lower()}_{rand_suffix.lower()}"
    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": role_code,
            "password": "pw-12345678",
            "role_codes": [role_code],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    cleanup_users.append(login_id)
    assert r.json()["roles"] == [role_code]
