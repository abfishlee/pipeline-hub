"""실 PG(docker-compose) 대상 통합 테스트 fixture.

pytest 실행 시 docker-compose 가 기동되어 있어야 함. DB 미접속 시 skip.
시드 데이터(test_admin) 는 `ON CONFLICT DO NOTHING` 으로 idempotent 생성.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core.security import hash_password
from app.main import create_app

TEST_ADMIN_LOGIN = "it_admin"
TEST_ADMIN_PASSWORD = "it-admin-pw-0425"


def _sync_url(async_url: str) -> str:
    """SQLAlchemy async URL → 동기 psycopg URL.

    통합 테스트 seed 는 빠르고 단순한 sync psycopg 로 처리.
    """
    return async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    """실제 .env 기반 Settings."""
    # cached singleton 초기화 — conftest.py 에서 test_settings 가 override 했을 수도 있음.
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def _require_db_reachable(integration_settings: Settings) -> None:
    """DB 미도달 시 통합 테스트 전체 skip."""
    try:
        with (
            psycopg.connect(
                _sync_url(integration_settings.database_url), connect_timeout=3
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"integration DB unreachable: {exc}")


@pytest.fixture(scope="session")
def _admin_seed(integration_settings: Settings) -> dict[str, str]:
    """test_admin 사용자 idempotent 보장 + ADMIN 역할 부여."""
    pw_hash = hash_password(TEST_ADMIN_PASSWORD)
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            INSERT INTO ctl.app_user
                (login_id, display_name, email, password_hash, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (login_id) DO UPDATE
               SET password_hash = EXCLUDED.password_hash,
                   is_active     = TRUE
            """,
            (TEST_ADMIN_LOGIN, "IT Admin", "it_admin@example.test", pw_hash),
        )
        cur.execute(
            """
            INSERT INTO ctl.user_role (user_id, role_id)
            SELECT u.user_id, r.role_id
              FROM ctl.app_user u, ctl.role r
             WHERE u.login_id = %s
               AND r.role_code = 'ADMIN'
            ON CONFLICT DO NOTHING
            """,
            (TEST_ADMIN_LOGIN,),
        )
    return {"login_id": TEST_ADMIN_LOGIN, "password": TEST_ADMIN_PASSWORD}


@pytest.fixture(scope="session")
def it_app(integration_settings: Settings) -> Iterator[TestClient]:
    """실제 DB 붙는 TestClient (ping 모킹 안 함)."""
    app = create_app(integration_settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def it_client(it_app: TestClient, _admin_seed: dict[str, str]) -> TestClient:
    """IT 테스트에서 인증 없이 쓰는 기본 client (admin_seed 선행 보장)."""
    return it_app


@pytest.fixture
def admin_token(it_client: TestClient, _admin_seed: dict[str, str]) -> str:
    """admin 로그인 → access_token."""
    r = it_client.post("/v1/auth/login", json=_admin_seed)
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


@pytest.fixture
def admin_auth(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def rand_suffix() -> str:
    """테스트 간 login_id 충돌 방지용 랜덤 suffix."""
    return uuid.uuid4().hex[:8] + secrets.token_hex(2)


@pytest.fixture
def cleanup_users(integration_settings: Settings) -> Iterator[list[str]]:
    """생성된 login_id 를 테스트 종료 시 삭제."""
    to_delete: list[str] = []
    yield to_delete
    if not to_delete:
        return
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            DELETE FROM ctl.user_role
             WHERE user_id IN (SELECT user_id FROM ctl.app_user WHERE login_id = ANY(%s))
            """,
            (to_delete,),
        )
        cur.execute(
            "DELETE FROM ctl.app_user WHERE login_id = ANY(%s)",
            (to_delete,),
        )
