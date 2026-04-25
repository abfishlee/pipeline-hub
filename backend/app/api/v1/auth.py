"""HTTP 경계 — 인증 (login / refresh / me)."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUserDep, SessionDep, SettingsDep
from app.domain import auth as auth_domain
from app.repositories import users as users_repo
from app.schemas.auth import LoginRequest, MeResponse, TokenPair, TokenRefreshRequest

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenPair:
    user = await auth_domain.authenticate(session, body.login_id, body.password)
    role_codes = await users_repo.get_user_role_codes(session, user.user_id)
    access, refresh = await auth_domain.issue_token_pair(user, settings, roles=role_codes)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_ttl_min * 60,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: TokenRefreshRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenPair:
    _, access, refresh_tok = await auth_domain.refresh_tokens(session, body.refresh_token, settings)
    return TokenPair(
        access_token=access,
        refresh_token=refresh_tok,
        expires_in=settings.jwt_access_ttl_min * 60,
    )


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep, session: SessionDep) -> MeResponse:
    roles = await users_repo.get_user_role_codes(session, user.user_id)
    return MeResponse(
        user_id=user.user_id,
        login_id=user.login_id,
        display_name=user.display_name,
        email=user.email,
        is_active=user.is_active,
        roles=roles,
    )
