"""HTTP — `/v1/api-keys` (ADMIN 만, Phase 4.2.5).

발급 시 `<prefix>.<secret>` 평문은 *응답에 1회만* 등장. 이후 GET 시 prefix 만 노출.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core import errors as app_errors
from app.core.security import hash_password
from app.deps import SessionDep, require_roles
from app.models.ctl import ApiKey
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(
    prefix="/v1/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


def _generate_prefix() -> str:
    return "dpk_" + secrets.token_hex(4)


def _generate_secret() -> str:
    return secrets.token_urlsafe(32)


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(body: ApiKeyCreate, session: SessionDep) -> ApiKeyCreated:
    """평문 `<prefix>.<secret>` 응답 1회. Argon2 hash 만 저장."""
    prefix = _generate_prefix()
    # prefix 충돌 방지 — 중복 시 한 번 더 시도.
    existing = await session.execute(select(ApiKey).where(ApiKey.key_prefix == prefix))
    if existing.scalar_one_or_none() is not None:
        prefix = _generate_prefix()
    secret = _generate_secret()
    api_key = ApiKey(
        key_prefix=prefix,
        key_hash=hash_password(secret),
        client_name=body.client_name,
        scope=list(body.scope),
        retailer_allowlist=list(body.retailer_allowlist),
        rate_limit_per_min=body.rate_limit_per_min,
        is_active=True,
        expires_at=body.expires_at,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return ApiKeyCreated(
        **ApiKeyOut.model_validate(api_key).model_dump(),
        secret=f"{prefix}.{secret}",
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(session: SessionDep) -> list[ApiKeyOut]:
    rows = (
        await session.execute(select(ApiKey).order_by(ApiKey.api_key_id.desc()))
    ).scalars().all()
    return [ApiKeyOut.model_validate(r) for r in rows]


@router.get("/{api_key_id}", response_model=ApiKeyOut)
async def get_api_key(api_key_id: int, session: SessionDep) -> ApiKeyOut:
    row = (
        await session.execute(select(ApiKey).where(ApiKey.api_key_id == api_key_id))
    ).scalar_one_or_none()
    if row is None:
        raise app_errors.NotFoundError(f"api_key {api_key_id} not found")
    return ApiKeyOut.model_validate(row)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(api_key_id: int, session: SessionDep) -> Response:
    """soft revoke — is_active=false + revoked_at 기록."""
    from datetime import UTC, datetime

    row = (
        await session.execute(select(ApiKey).where(ApiKey.api_key_id == api_key_id))
    ).scalar_one_or_none()
    if row is None:
        raise app_errors.NotFoundError(f"api_key {api_key_id} not found")
    row.is_active = False
    row.revoked_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
