"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from typing import Any

# Windows 로컬에서 psycopg async 사용 시 필요 (ADR-0001 회수 조건 참조).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import session as db_session
from app.integrations import object_storage as object_storage_module
from app.main import create_app


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """테스트용 Settings — 실제 외부 서비스 미접근 가정."""
    return Settings(
        env="local",
        debug=True,
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/1",
        log_level="WARNING",  # 테스트 노이즈 줄이기
        log_json=False,
        jwt_secret="test-secret-test-secret-test-secret-32b",  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# DB ping mocks
# ---------------------------------------------------------------------------
@pytest.fixture
def patch_db_ping_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(timeout_sec: float = 5.0) -> bool:
        return True

    monkeypatch.setattr(db_session, "ping", _ok)


@pytest.fixture
def patch_db_ping_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(timeout_sec: float = 5.0) -> bool:
        return False

    monkeypatch.setattr(db_session, "ping", _fail)


# ---------------------------------------------------------------------------
# Object Storage mocks — 유닛 테스트가 실제 MinIO 에 의존하지 않도록.
# ---------------------------------------------------------------------------
class _FakeStorage:
    """/readyz 테스트용 가짜 ObjectStorage. ping 만 구현."""

    def __init__(self, ping_result: bool) -> None:
        self._ping_result = ping_result
        self.bucket = "fake-bucket"

    @property
    def uri_scheme(self) -> str:
        return "s3"

    def object_uri(self, key: str) -> str:
        return f"s3://fake-bucket/{key}"

    async def ping(self, timeout_sec: float = 5.0) -> bool:
        return self._ping_result

    # 이하는 유닛 테스트에서 호출 안 하지만 Protocol 준수 목적.
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        return self.object_uri(key)

    async def put_stream(
        self, key: str, chunks: Any, content_type: str = "application/octet-stream"
    ) -> str:
        return self.object_uri(key)

    async def presigned_put(
        self, key: str, expires_sec: int = 300, content_type: str | None = None
    ) -> str:
        return f"https://fake/{key}"

    async def presigned_get(self, key: str, expires_sec: int = 300) -> str:
        return f"https://fake/{key}"

    async def exists(self, key: str) -> bool:
        return False

    async def delete(self, key: str) -> bool:
        return True


@pytest.fixture
def patch_object_storage_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """실제 boto3 클라이언트 대신 가짜 ping=True storage 주입."""
    monkeypatch.setattr(object_storage_module, "get_object_storage", lambda: _FakeStorage(True))


@pytest.fixture
def patch_object_storage_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(object_storage_module, "get_object_storage", lambda: _FakeStorage(False))


# ---------------------------------------------------------------------------
# Test clients
# ---------------------------------------------------------------------------
@pytest.fixture
def client(
    test_settings: Settings,
    patch_db_ping_ok: None,
    patch_object_storage_ok: None,
) -> Iterator[TestClient]:
    """Sync FastAPI TestClient — 라우트 단위 테스트 (DB+OS ping 모두 OK 모킹)."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_db_down(
    test_settings: Settings,
    patch_db_ping_fail: None,
    patch_object_storage_ok: None,
) -> Iterator[TestClient]:
    """DB 다운 + OS 정상 시나리오."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_os_down(
    test_settings: Settings,
    patch_db_ping_ok: None,
    patch_object_storage_fail: None,
) -> Iterator[TestClient]:
    """Object Storage 다운 + DB 정상 시나리오."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c
