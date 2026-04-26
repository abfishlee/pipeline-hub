"""Public API stub (Phase 4.2.4) — `X-API-Key` 인증 → SET ROLE app_public → masking VIEW.

본 모듈은 Phase 4.2.5 의 정식 Public API 구현 *전*에 RLS + 컬럼 마스킹 동작을
end-to-end 로 검증하기 위한 최소 stub. 다음 페이즈에서 다음 항목이 채워진다:
  - 정식 엔드포인트 (`/products`, `/prices/latest`, `/prices/daily`, `/prices/series`)
  - rate limit (slowapi + Redis)
  - Public 전용 OpenAPI (`/public/docs`)
  - audit.public_api_usage 적재

현재 stub 동작:
  - `GET /public/v1/retailers` — masking view 의 retailer 목록 (RLS 적용)
  - `GET /public/v1/sellers`   — masking view 의 seller 목록 (RLS allowlist 필터)
  - 인증: `X-API-Key: <key_prefix>.<full_secret>` (Phase 1.2.x 형식)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query
from sqlalchemy import select, text

from app.core import errors as app_errors
from app.core.security import verify_password
from app.db.session import (
    set_retailer_allowlist,
    set_session_role,
)
from app.deps import SessionDep
from app.models.ctl import ApiKey

router = APIRouter(prefix="/public/v1", tags=["public"])


async def _resolve_api_key(session: Any, raw_key: str) -> ApiKey:
    """`<prefix>.<secret>` 형식 검증 → DB lookup → Argon2 비교."""
    if not raw_key or "." not in raw_key:
        raise app_errors.AuthenticationError("invalid api key format")
    prefix, _, secret = raw_key.partition(".")
    if not prefix or not secret:
        raise app_errors.AuthenticationError("invalid api key format")
    row = (
        await session.execute(select(ApiKey).where(ApiKey.key_prefix == prefix))
    ).scalar_one_or_none()
    if row is None or not row.is_active:
        raise app_errors.AuthenticationError("api key not found or inactive")
    if not verify_password(secret, row.key_hash):
        raise app_errors.AuthenticationError("api key hash mismatch")
    api_key: ApiKey = row
    return api_key


@router.get("/retailers")
async def list_retailers(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """RLS 미적용 (mart.retailer_master 는 retailer_id 컬럼 자체이므로 제한 X) +
    masking view 가 business_no / head_office_addr 마스킹."""
    if x_api_key is None:
        raise app_errors.AuthenticationError("missing X-API-Key header")
    api_key = await _resolve_api_key(session, x_api_key)
    await set_session_role(session, "app_public")
    await set_retailer_allowlist(session, api_key.retailer_allowlist)
    rows = await session.execute(
        text(
            "SELECT retailer_id, retailer_code, retailer_name, retailer_type, "
            "       business_no, head_office_addr "
            "FROM mart.retailer_master_view "
            "ORDER BY retailer_id "
            "LIMIT :lim"
        ),
        {"lim": limit},
    )
    return [dict(r._mapping) for r in rows]


@router.get("/sellers")
async def list_sellers(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """RLS — api_key.retailer_allowlist 미포함 retailer 의 seller row 는 보이지 않음."""
    if x_api_key is None:
        raise app_errors.AuthenticationError("missing X-API-Key header")
    api_key = await _resolve_api_key(session, x_api_key)
    await set_session_role(session, "app_public")
    await set_retailer_allowlist(session, api_key.retailer_allowlist)
    rows = await session.execute(
        text(
            "SELECT seller_id, retailer_id, seller_code, seller_name, channel, "
            "       region_sido, region_sigungu, address "
            "FROM mart.seller_master_view "
            "ORDER BY seller_id "
            "LIMIT :lim"
        ),
        {"lim": limit},
    )
    return [dict(r._mapping) for r in rows]


__all__ = ["router"]
