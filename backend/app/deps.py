"""FastAPI dependency injection — 공통 DI 집합.

- `SettingsDep` — Pydantic Settings 싱글톤.
- `SessionDep` — async DB 세션 (요청당 1개).
- `CurrentUserDep` — Bearer 토큰 → AppUser (비활성/무효 시 401).
- `require_roles(*codes)` — 지정 역할 중 1개 이상 보유자만 통과 (없으면 403).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import errors as app_errors
from app.db.session import get_session
from app.domain import auth as auth_domain
from app.models.ctl import AppUser
from app.repositories import users as users_repo

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AppUser:
    """Authorization: Bearer <jwt> → AppUser. 없거나 무효면 401."""
    if not authorization:
        raise app_errors.AuthenticationError("missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise app_errors.AuthenticationError("Authorization must be Bearer scheme")
    token = authorization[len("bearer ") :].strip()
    if not token:
        raise app_errors.AuthenticationError("empty token")
    return await auth_domain.get_current_user_from_token(session, token, settings)


CurrentUserDep = Annotated[AppUser, Depends(current_user)]


def require_roles(
    *required: str,
) -> Callable[..., Coroutine[Any, Any, AppUser]]:
    """최소 1개 역할 충족 보증. FastAPI Depends 로 장착.

    사용 예:
        @router.post("/users", dependencies=[Depends(require_roles("ADMIN"))])
        async def create_user(...): ...
    또는 반환값으로 사용자 주입:
        user: Annotated[AppUser, Depends(require_roles("ADMIN"))]
    """
    required_set = set(required)

    async def _dep(
        user: CurrentUserDep,
        session: SessionDep,
    ) -> AppUser:
        role_codes = await users_repo.get_user_role_codes(session, user.user_id)
        if not required_set.intersection(role_codes):
            raise app_errors.PermissionError(
                f"requires one of roles: {','.join(sorted(required_set))}"
            )
        return user

    return _dep


__all__ = [
    "CurrentUserDep",
    "SessionDep",
    "SettingsDep",
    "current_user",
    "require_roles",
]
