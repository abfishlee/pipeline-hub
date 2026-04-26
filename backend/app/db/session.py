"""Async SQLAlchemy engine + session lifecycle.

설계 원칙:
  - Engine 1개 / sessionmaker 1개를 프로세스당 lazy 생성.
  - FastAPI dependency `get_session` 은 요청마다 세션을 yield, 예외 시 rollback,
    종료 시 close. 명시적 commit은 호출자(라우트/도메인)가 담당.
  - lifespan shutdown 시 `dispose_engine` 으로 connection 풀 정리.
  - URL 스킴(`postgresql+asyncpg://` vs `postgresql+psycopg://`)에 의존하지 않음.
    SQLAlchemy 가 dialect 자동 매칭. ADR-0001 참조.

Phase 4.2.4 — RLS 컨텍스트 헬퍼:
  - `set_session_role(session, role)`: SET LOCAL ROLE 으로 PG role 전환
    (app_rw / app_mart_write / app_readonly / app_public). 트랜잭션 단위만 효과.
  - `set_retailer_allowlist(session, ids)`: SET LOCAL app.retailer_allowlist 로
    api_key 의 허용 retailer 셋 주입 — RLS 정책이 이 값을 읽음.
  - 라우트는 `request_role` dependency 로 일괄 적용 권장 (ADR-0012).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

PgAppRole = Literal["app_rw", "app_mart_write", "app_readonly", "app_public"]
ALLOWED_PG_ROLES: frozenset[str] = frozenset(
    ("app_rw", "app_mart_write", "app_readonly", "app_public")
)

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


# ---------------------------------------------------------------------------
# Phase 4.2.4 — RLS 컨텍스트 helpers
# ---------------------------------------------------------------------------
async def set_session_role(session: AsyncSession, role: PgAppRole) -> None:
    """현재 트랜잭션의 PG role 을 전환. SET LOCAL 이라 commit/rollback 시 자동 해제.

    주의: connection user 가 해당 role 의 멤버여야 한다 (migration 0024 가 GRANT).
    `role` 은 enum 만 허용 — 외부 입력에서 SQL 인젝션 회피.
    """
    if role not in ALLOWED_PG_ROLES:
        raise ValueError(f"invalid PG role: {role!r}")
    await session.execute(text(f'SET LOCAL ROLE "{role}"'))


async def reset_session_role(session: AsyncSession) -> None:
    """RESET ROLE — connection user 로 복귀."""
    await session.execute(text("RESET ROLE"))


async def set_retailer_allowlist(
    session: AsyncSession, retailer_ids: Iterable[int]
) -> None:
    """SET LOCAL app.retailer_allowlist — RLS 정책이 읽는 GUC.

    빈 배열이면 모든 row 차단 ("미포함 시 보이지 않음" 정책). 정수 외 값은 거부.
    """
    ids = [int(x) for x in retailer_ids]
    payload = ",".join(str(i) for i in ids) if ids else ""
    formatted = "{" + payload + "}"
    await session.execute(
        text("SELECT set_config('app.retailer_allowlist', :v, true)"),
        {"v": formatted},
    )


__all__ = [
    "ALLOWED_PG_ROLES",
    "PgAppRole",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "ping",
    "reset_engine_for_settings",
    "reset_session_role",
    "set_retailer_allowlist",
    "set_session_role",
]
