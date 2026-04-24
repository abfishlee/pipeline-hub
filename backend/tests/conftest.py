"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator

# Windows 로컬에서 psycopg async 사용 시 필요 (ADR-0001 회수 조건 참조).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import session as db_session
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


@pytest.fixture
def patch_db_ping_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """`db_session.ping` 을 항상 True 로 모킹 — DB 없이 readyz 테스트."""

    async def _ok(timeout_sec: float = 5.0) -> bool:
        return True

    monkeypatch.setattr(db_session, "ping", _ok)


@pytest.fixture
def patch_db_ping_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """`db_session.ping` 을 항상 False 로 모킹 — readyz unready 시나리오."""

    async def _fail(timeout_sec: float = 5.0) -> bool:
        return False

    monkeypatch.setattr(db_session, "ping", _fail)


@pytest.fixture
def client(test_settings: Settings, patch_db_ping_ok: None) -> Iterator[TestClient]:
    """Sync FastAPI TestClient — 라우트 단위 테스트에 사용 (기본: DB ping=OK 모킹)."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_db_down(test_settings: Settings, patch_db_ping_fail: None) -> Iterator[TestClient]:
    """DB 다운 시나리오 전용 TestClient."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c
