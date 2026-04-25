"""도메인 서비스 — 로그인 / 토큰 발급 / 현재 사용자 복원.

HTTP 경계 (api/v1/auth.py) 와 DB 경계 (repositories/users.py) 사이.
"""

from __future__ import annotations

import contextlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.ctl import AppUser
from app.repositories import users as users_repo

# 사용자 존재 여부를 노출하지 않도록 고정 메시지.
_INVALID_CREDENTIALS_MSG = "invalid credentials"


async def authenticate(session: AsyncSession, login_id: str, password: str) -> AppUser:
    """로그인 검증. 성공 시 AppUser 반환. 실패 시 동일 401 메시지."""
    user = await users_repo.get_by_login_id(session, login_id)
    if user is None or not user.is_active:
        # timing attack 완화: 존재하지 않아도 verify 1회 실행 (임의 해시 비교)
        _verify_dummy(password)
        raise AuthenticationError(_INVALID_CREDENTIALS_MSG)
    if not verify_password(password, user.password_hash):
        raise AuthenticationError(_INVALID_CREDENTIALS_MSG)
    return user


# Argon2id 더미 해시 — timing attack 대응용 (실행 시간을 균일화).
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "YWFhYWFhYWFhYWFhYWFhYQ$QeN1o0Hs1Kr3MScYkXj3oLJ1O/IHCnIJ0mCt1E+M3CI"
)


def _verify_dummy(password: str) -> None:
    """비교 자체의 결과는 무시. 시간만 소비."""
    with contextlib.suppress(Exception):
        verify_password(password, _DUMMY_HASH)


async def issue_token_pair(
    user: AppUser, settings: Settings, roles: list[str] | None = None
) -> tuple[str, str]:
    """Access + Refresh 토큰 동시 발급.

    roles 는 access 토큰 클레임에만 포함. Refresh 에는 포함하지 않음
    (refresh 시 DB 에서 최신 roles 재조회 → 즉시 반영).
    """
    access = create_access_token(
        user.user_id,
        settings=settings,
        extra_claims={"roles": roles or []},
    )
    refresh = create_refresh_token(user.user_id, settings=settings)
    return access, refresh


async def refresh_tokens(
    session: AsyncSession, refresh_token: str, settings: Settings
) -> tuple[AppUser, str, str]:
    """Refresh 토큰 → 새 access+refresh. 최신 roles 반영."""
    payload = decode_token(refresh_token, settings=settings)
    if payload.get("typ") != "refresh":
        raise AuthenticationError("invalid token type")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("invalid token payload") from exc

    user = await users_repo.get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("user disabled or missing")

    role_codes = await users_repo.get_user_role_codes(session, user.user_id)
    access, refresh = await issue_token_pair(user, settings, roles=role_codes)
    return user, access, refresh


async def get_current_user_from_token(
    session: AsyncSession, access_token: str, settings: Settings
) -> AppUser:
    """API 가드용 — access 토큰 → AppUser. 비활성/미존재 시 401."""
    payload = decode_token(access_token, settings=settings)
    if payload.get("typ") != "access":
        raise AuthenticationError("invalid token type")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("invalid token payload") from exc

    user = await users_repo.get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("user disabled or missing")
    return user


__all__ = [
    "authenticate",
    "get_current_user_from_token",
    "issue_token_pair",
    "refresh_tokens",
]
