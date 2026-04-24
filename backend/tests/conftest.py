"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """테스트용 Settings — 실제 외부 서비스 미접근 가정."""
    return Settings(
        env="local",
        debug=True,
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/1",
        log_level="WARNING",  # 테스트 노이즈 줄이기
        log_json=False,
        jwt_secret="test-secret-test-secret-test-secret-32b",  # type: ignore[arg-type]
    )


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """Sync FastAPI TestClient — 라우트 단위 테스트에 사용."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c
