"""Async SQLAlchemy engine + session lifecycle.

설계 원칙:
  - Engine 1개 / sessionmaker 1개를 프로세스당 lazy 생성.
  - FastAPI dependency `get_session` 은 요청마다 세션을 yield, 예외 시 rollback,
    종료 시 close. 명시적 commit은 호출자(라우트/도메인)가 담당.
  - lifespan shutdown 시 `dispose_engine` 으로 connection 풀 정리.
  - URL 스킴(`postgresql+asyncpg://` vs `postgresql+psycopg://`)에 의존하지 않음.
    SQLAlchemy 가 dialect 자동 매칭. ADR-0001 참조.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.debug and settings.is_local,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,  # 1h, NCP Cloud DB tcp keepalive 회피
        future=True,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. 요청마다 세션 1개 발급.

    호출자가 commit 책임. 예외 발생 시 rollback. 종료 시 close.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping(timeout_sec: float = 5.0) -> bool:
    """`/readyz` 용 가벼운 DB 연결 체크.

    별도 트랜잭션 없이 connect → SELECT 1.
    """
    import asyncio

    engine = get_engine()

    async def _do_ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_do_ping(), timeout=timeout_sec)
        return True
    except (TimeoutError, Exception):
        return False


async def dispose_engine() -> None:
    """lifespan shutdown 시 호출. 풀 정리 + 모듈 전역 초기화."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


# 테스트용: 외부 코드가 별도 settings 로 engine 재구성하고 싶을 때.
async def reset_engine_for_settings(settings: Settings) -> None:
    """주의: 운영 코드에서 호출 금지. 테스트/셸 전용."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = _build_engine(settings)
    _sessionmaker = async_sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)


__all__ = [
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "ping",
    "reset_engine_for_settings",
]
