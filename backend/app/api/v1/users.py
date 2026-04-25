"""HTTP 경계 — 사용자 CRUD + 역할 관리 (ADMIN 전용)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core import errors as app_errors
from app.core.security import hash_password
from app.deps import SessionDep, require_roles
from app.repositories import users as users_repo
from app.schemas.users import RoleAssign, UserCreate, UserOut, UserUpdate

# 전체 라우터에 ADMIN 가드. 이후 세밀 권한은 개별 route 에서 override.
router = APIRouter(
    prefix="/v1/users",
    tags=["users"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


async def _to_out(session: SessionDep, user_id: int) -> UserOut:
    """ORM → UserOut (+ roles)."""
    user = await users_repo.get_by_id(session, user_id)
    if user is None:
        raise app_errors.NotFoundError(f"user {user_id} not found")
    roles = await users_repo.get_user_role_codes(session, user_id)
    return UserOut(
        user_id=user.user_id,
        login_id=user.login_id,
        display_name=user.display_name,
        email=user.email,
        is_active=user.is_active,
        roles=roles,
        created_at=user.created_at,
    )


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, session: SessionDep) -> UserOut:
    user = await users_repo.create(
        session,
        login_id=body.login_id,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        email=body.email,
    )
    if body.role_codes:
        await users_repo.assign_roles(session, user.user_id, body.role_codes)
    await session.commit()
    return await _to_out(session, user.user_id)


@router.get("", response_model=list[UserOut])
async def list_users(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    is_active: bool | None = Query(None),
) -> list[UserOut]:
    users = await users_repo.list_paginated(
        session, limit=limit, offset=offset, is_active=is_active
    )
    return [await _to_out(session, u.user_id) for u in users]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: SessionDep) -> UserOut:
    return await _to_out(session, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, session: SessionDep) -> UserOut:
    await users_repo.update_fields(
        session,
        user_id,
        display_name=body.display_name,
        email=body.email,
        is_active=body.is_active,
    )
    await session.commit()
    return await _to_out(session, user_id)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, session: SessionDep) -> Response:
    """Soft delete — is_active=FALSE. 감사 이력 보존을 위해 row 제거 안 함."""
    await users_repo.deactivate(session, user_id)
    await session.commit()
    return Response(status_code=204)


@router.post("/{user_id}/roles", response_model=UserOut)
async def assign_user_roles(user_id: int, body: RoleAssign, session: SessionDep) -> UserOut:
    """지정 역할을 추가 부여 (기존 역할은 유지)."""
    await users_repo.assign_roles(session, user_id, body.role_codes)
    await session.commit()
    return await _to_out(session, user_id)


@router.put("/{user_id}/roles", response_model=UserOut)
async def replace_user_roles(user_id: int, body: RoleAssign, session: SessionDep) -> UserOut:
    """사용자 역할을 지정 집합으로 교체 (기존 역할은 전부 제거)."""
    await users_repo.replace_roles(session, user_id, body.role_codes)
    await session.commit()
    return await _to_out(session, user_id)


@router.delete("/{user_id}/roles/{role_code}", status_code=204)
async def revoke_user_role(user_id: int, role_code: str, session: SessionDep) -> Response:
    revoked = await users_repo.revoke_role(session, user_id, role_code)
    await session.commit()
    if not revoked:
        raise app_errors.NotFoundError(f"user {user_id} does not have role '{role_code}'")
    return Response(status_code=204)
