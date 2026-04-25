"""Sync SQLAlchemy session — Dramatiq worker / 동기 스크립트 전용.

Phase 2.2.1 부터 도입. Worker thread 는 sync 컨텍스트라 async session 을 그대로
쓸 수 없다. 같은 ORM 모델/스키마를 공유하면서 별도 sync engine 1개를 둔다.

URL 변환: `postgresql+asyncpg://...` 또는 `postgresql+psycopg://...` 모두
`postgresql+psycopg://...` (sync) 로 정규화. psycopg3 는 sync/async 동시 지원이라
별도 의존성 추가 없음 (ADR-0001).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def _to_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgresql+psycopg://"):
        # 그대로 sync (psycopg dialect 가 자동 분기, async 가 아닌 path 이면 sync 사용).
        return url
    return url  # 다른 drivers — 호출자가 책임


_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _build_engine(settings: Settings) -> Engine:
    return create_engine(
        _to_sync_url(settings.database_url),
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )


def get_sync_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_sync_sessionmaker() -> sessionmaker[Session]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(
            bind=get_sync_engine(), autoflush=False, expire_on_commit=False
        )
    return _sessionmaker


def dispose_sync_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None


__all__ = [
    "dispose_sync_engine",
    "get_sync_engine",
    "get_sync_sessionmaker",
]
