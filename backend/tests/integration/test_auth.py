"""인증 API 통합 테스트 — 실 PG 대상."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt

from app.config import Settings
from app.core.security import JWT_ALGORITHM

from .conftest import TEST_ADMIN_LOGIN, TEST_ADMIN_PASSWORD


# ---------------------------------------------------------------------------
# /v1/auth/login
# ---------------------------------------------------------------------------
def test_login_success_returns_tokens(it_client: TestClient) -> None:
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": TEST_ADMIN_LOGIN, "password": TEST_ADMIN_PASSWORD},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] > 0


def test_login_wrong_password_is_401(it_client: TestClient) -> None:
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": TEST_ADMIN_LOGIN, "password": "nope-nope-nope"},
    )
    assert r.status_code == 401
    body = r.json()
    # 메시지는 일반화 (사용자 존재 노출 금지)
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "invalid credentials"


def test_login_unknown_user_is_401_with_same_message(it_client: TestClient) -> None:
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": "nobody-exists-1234", "password": "whatever12345"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "invalid credentials"


def test_login_inactive_user_is_401(
    it_client: TestClient,
    integration_settings: Settings,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> None:
    login_id = f"ituser_inactive_{rand_suffix}"
    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "비활성 테스트",
            "password": "somepassword-ok",
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["user_id"]
    cleanup_users.append(login_id)

    # 비활성화
    r = it_client.patch(
        f"/v1/users/{user_id}",
        json={"is_active": False},
        headers=admin_auth,
    )
    assert r.status_code == 200

    # 로그인 시도
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": login_id, "password": "somepassword-ok"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "invalid credentials"


# ---------------------------------------------------------------------------
# /v1/auth/refresh
# ---------------------------------------------------------------------------
def test_refresh_rotates_tokens(it_client: TestClient) -> None:
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": TEST_ADMIN_LOGIN, "password": TEST_ADMIN_PASSWORD},
    )
    tokens = r.json()

    r2 = it_client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 200, r2.text
    new_tokens = r2.json()
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]


def test_refresh_with_access_token_is_401(it_client: TestClient, admin_token: str) -> None:
    """access 토큰으로 refresh 시도 → typ 체크 실패."""
    r = it_client.post("/v1/auth/refresh", json={"refresh_token": admin_token})
    assert r.status_code == 401
    assert "token type" in r.json()["error"]["message"]


def test_refresh_invalid_token_is_401(it_client: TestClient) -> None:
    r = it_client.post("/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /v1/auth/me
# ---------------------------------------------------------------------------
def test_me_returns_current_user_with_roles(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    r = it_client.get("/v1/auth/me", headers=admin_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["login_id"] == TEST_ADMIN_LOGIN
    assert body["is_active"] is True
    assert "ADMIN" in body["roles"]


def test_me_without_token_is_401(it_client: TestClient) -> None:
    r = it_client.get("/v1/auth/me")
    assert r.status_code == 401
    assert "Authorization" in r.json()["error"]["message"]


def test_me_with_invalid_scheme_is_401(it_client: TestClient) -> None:
    r = it_client.get("/v1/auth/me", headers={"Authorization": "Basic xyz"})
    assert r.status_code == 401
    assert "Bearer" in r.json()["error"]["message"]


def test_me_with_expired_token_is_401(
    it_client: TestClient, integration_settings: Settings
) -> None:
    """만료된 access 토큰 → 401."""
    # 과거 시각으로 강제 만든 토큰
    now = datetime.now(UTC) - timedelta(hours=2)
    exp = now + timedelta(minutes=1)  # 이미 만료
    payload = {
        "sub": "999999",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    expired = jwt.encode(
        payload,
        integration_settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    r = it_client.get("/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_me_with_refresh_token_is_401(
    it_client: TestClient, integration_settings: Settings
) -> None:
    """refresh 토큰으로 /me 접근 → typ 불일치 401."""
    r = it_client.post(
        "/v1/auth/login",
        json={"login_id": TEST_ADMIN_LOGIN, "password": TEST_ADMIN_PASSWORD},
    )
    refresh = r.json()["refresh_token"]
    r = it_client.get("/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401
    assert "token type" in r.json()["error"]["message"]
