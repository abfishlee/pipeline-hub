"""Repository — AppUser / Role / UserRole.

DB 접근을 이 모듈로 격리. API / domain 는 직접 ORM 쿼리 작성하지 않는다.
모든 함수는 async. commit 책임은 호출자(domain/api).
"""

from __future__ import annotations

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.ctl import AppUser, Role, UserRole


# ---------------------------------------------------------------------------
# AppUser
# ---------------------------------------------------------------------------
async def get_by_id(session: AsyncSession, user_id: int) -> AppUser | None:
    stmt = select(AppUser).where(AppUser.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_by_login_id(session: AsyncSession, login_id: str) -> AppUser | None:
    stmt = select(AppUser).where(AppUser.login_id == login_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_paginated(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    is_active: bool | None = None,
) -> list[AppUser]:
    stmt = select(AppUser).order_by(AppUser.user_id.asc()).limit(limit).offset(offset)
    if is_active is not None:
        stmt = stmt.where(AppUser.is_active == is_active)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create(
    session: AsyncSession,
    *,
    login_id: str,
    display_name: str,
    password_hash: str,
    email: str | None = None,
) -> AppUser:
    # login_id 중복 방지 — unique 제약으로도 막히지만 명확한 에러 코드 위해 사전 체크.
    if await get_by_login_id(session, login_id):
        raise ConflictError(f"login_id '{login_id}' already exists")
    user = AppUser(
        login_id=login_id,
        display_name=display_name,
        password_hash=password_hash,
        email=email,
    )
    session.add(user)
    await session.flush()  # user_id 발급
    return user


async def update_fields(
    session: AsyncSession,
    user_id: int,
    *,
    display_name: str | None = None,
    email: str | None = None,
    is_active: bool | None = None,
) -> AppUser:
    user = await get_by_id(session, user_id)
    if user is None:
        raise NotFoundError(f"user {user_id} not found")
    if display_name is not None:
        user.display_name = display_name
    if email is not None:
        user.email = email
    if is_active is not None:
        user.is_active = is_active
    await session.flush()
    return user


async def deactivate(session: AsyncSession, user_id: int) -> AppUser:
    """Soft delete — is_active=FALSE. 실제 row 삭제는 안 함 (감사 이력 보존)."""
    return await update_fields(session, user_id, is_active=False)


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------
async def get_role_by_code(session: AsyncSession, role_code: str) -> Role | None:
    stmt = select(Role).where(Role.role_code == role_code)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_role_or_raise(session: AsyncSession, role_code: str) -> Role:
    role = await get_role_by_code(session, role_code)
    if role is None:
        raise NotFoundError(f"role '{role_code}' not found")
    return role


async def list_roles(session: AsyncSession) -> list[Role]:
    stmt = select(Role).order_by(Role.role_id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# UserRole
# ---------------------------------------------------------------------------
async def get_user_role_codes(session: AsyncSession, user_id: int) -> list[str]:
    stmt = (
        select(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.role_code.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def assign_roles(session: AsyncSession, user_id: int, role_codes: list[str]) -> list[str]:
    """지정 역할 전부 부여 (이미 있으면 무시). 최종 보유 역할 목록 반환."""
    # 사용자 존재 확인
    user = await get_by_id(session, user_id)
    if user is None:
        raise NotFoundError(f"user {user_id} not found")

    # 존재하는 role 만 처리 + 없는 코드는 NotFound
    for code in role_codes:
        role = await get_role_or_raise(session, code)
        # 이미 존재하면 skip
        exists_stmt = select(UserRole).where(
            and_(UserRole.user_id == user_id, UserRole.role_id == role.role_id)
        )
        existing = await session.execute(exists_stmt)
        if existing.scalar_one_or_none() is None:
            session.add(UserRole(user_id=user_id, role_id=role.role_id))
    await session.flush()
    return await get_user_role_codes(session, user_id)


async def revoke_role(session: AsyncSession, user_id: int, role_code: str) -> bool:
    role = await get_role_or_raise(session, role_code)
    stmt = delete(UserRole).where(
        and_(UserRole.user_id == user_id, UserRole.role_id == role.role_id)
    )
    result = await session.execute(stmt)
    # SQLAlchemy async execute(Delete) → CursorResult — mypy 추론 한계 우회
    rowcount: int = result.rowcount  # type: ignore[attr-defined]
    return rowcount > 0


async def replace_roles(session: AsyncSession, user_id: int, role_codes: list[str]) -> list[str]:
    """기존 역할 전부 삭제 후 지정 역할로 교체."""
    user = await get_by_id(session, user_id)
    if user is None:
        raise NotFoundError(f"user {user_id} not found")

    await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
    return await assign_roles(session, user_id, role_codes)


__all__ = [
    "assign_roles",
    "create",
    "deactivate",
    "get_by_id",
    "get_by_login_id",
    "get_role_by_code",
    "get_role_or_raise",
    "get_user_role_codes",
    "list_paginated",
    "list_roles",
    "replace_roles",
    "revoke_role",
    "update_fields",
]
