"""Public API (Phase 4.2.5) — `X-API-Key` 인증 → scope check → rate limit →
SET LOCAL ROLE app_public + retailer_allowlist GUC → masking view + RLS SELECT.

설계:
  - 라우터는 `/public/v1` prefix. main.py 가 별도 sub-app `public_app` 로 mount 해서
    `/public/docs` (OpenAPI 별도) 분리.
  - 모든 엔드포인트가 동일한 `_authenticated_query_session` dependency 를 사용 — 인증 +
    scope + rate limit + role/GUC 설정을 한 번에.
  - 응답 캐시 (Redis): standard-codes/products/prices.daily 5분, prices.latest 1분,
    prices.series 3분.
  - audit.public_api_usage 적재는 미들웨어 (`PublicApiUsageMiddleware`) 가 비동기로
    INSERT.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, date, datetime
from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import errors as app_errors
from app.core.rate_limit import check_rate_limit
from app.core.security import verify_password
from app.db.session import (
    set_retailer_allowlist,
    set_session_role,
)
from app.deps import SessionDep
from app.models.ctl import ApiKey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["public"])

# scope ↔ endpoint 매트릭스. endpoint label 은 audit.public_api_usage 의 endpoint 컬럼 +
# rate-limit/캐시 키.
ENDPOINT_REQUIRED_SCOPES: dict[str, frozenset[str]] = {
    "retailers": frozenset({"products.read"}),
    "sellers": frozenset({"products.read"}),
    "standard_codes": frozenset({"products.read"}),
    "products": frozenset({"products.read"}),
    "prices.latest": frozenset({"prices.read"}),
    "prices.daily": frozenset({"aggregates.read"}),
    "prices.series": frozenset({"aggregates.read"}),
}


# ---------------------------------------------------------------------------
# 응답 캐시 (Redis)
# ---------------------------------------------------------------------------
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url, decode_responses=True
        )
    return _redis_client


async def _cache_get(key: str) -> Any | None:
    try:
        raw = await _get_redis().get(key)
    except Exception:
        return None
    return None if raw is None else json.loads(raw)


async def _cache_set(key: str, value: Any, ttl_sec: int) -> None:
    try:
        await _get_redis().setex(key, ttl_sec, json.dumps(value, default=str))
    except Exception:
        return


# ---------------------------------------------------------------------------
# 인증 + 권한 + rate limit dependency
# ---------------------------------------------------------------------------
class PublicAuthContext:
    __slots__ = ("api_key", "endpoint", "matched_scopes")

    def __init__(self, api_key: ApiKey, endpoint: str, matched_scopes: frozenset[str]) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.matched_scopes = matched_scopes


async def _resolve_api_key(session: AsyncSession, raw_key: str) -> ApiKey:
    if not raw_key or "." not in raw_key:
        raise app_errors.AuthenticationError("invalid api key format")
    prefix, _, secret = raw_key.partition(".")
    if not prefix or not secret:
        raise app_errors.AuthenticationError("invalid api key format")
    row = (
        await session.execute(select(ApiKey).where(ApiKey.key_prefix == prefix))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or not row.is_active:
        raise app_errors.AuthenticationError("api key not found or inactive")
    if row.revoked_at is not None:
        raise app_errors.AuthenticationError("api key revoked")
    if row.expires_at is not None and row.expires_at < now:
        raise app_errors.AuthenticationError("api key expired")
    if not verify_password(secret, row.key_hash):
        raise app_errors.AuthenticationError("api key hash mismatch")
    api_key: ApiKey = row
    return api_key


from collections.abc import Callable, Coroutine


def require_endpoint(
    endpoint_label: str,
) -> Callable[..., Coroutine[Any, Any, "PublicAuthContext"]]:
    """endpoint 별 dependency factory — 인증 + scope + rate limit + role 설정.

    함수 그 자체는 라우트 dep 로 사용. 반환값은 PublicAuthContext.
    """

    async def _dep(
        request: Request,
        session: SessionDep,
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> PublicAuthContext:
        if x_api_key is None:
            raise app_errors.AuthenticationError("missing X-API-Key header")
        api_key = await _resolve_api_key(session, x_api_key)
        required = ENDPOINT_REQUIRED_SCOPES[endpoint_label]
        scope_set = set(api_key.scope or [])
        matched = required & scope_set
        if not matched:
            raise app_errors.PermissionError(
                f"required scope: one of {sorted(required)}",
            )
        # rate limit
        rl = await check_rate_limit(api_key_id=api_key.api_key_id, limit=api_key.rate_limit_per_min)
        if not rl.allowed:
            raise app_errors.RateLimitError(
                "rate limit exceeded",
                retry_after_seconds=rl.reset_seconds,
            )
        # role + allowlist GUC
        await set_session_role(session, "app_public")
        await set_retailer_allowlist(session, api_key.retailer_allowlist)
        # last_used_at 갱신 (best-effort, fire-and-forget OK).
        api_key.last_used_at = datetime.now(UTC)
        # request scope 정보 — middleware 가 audit 에 사용.
        request.state.public_api_key_id = api_key.api_key_id
        request.state.public_api_endpoint = endpoint_label
        request.state.public_api_scope = sorted(matched)[0]
        return PublicAuthContext(api_key, endpoint_label, frozenset(matched))

    return _dep


# ---------------------------------------------------------------------------
# 1) standard-codes
# ---------------------------------------------------------------------------
@router.get("/standard-codes")
async def list_standard_codes(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("standard_codes"))],
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    cache_key = f"dp:public_api:cache:standard_codes:{q or ''}:{category or ''}:{limit}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    where: list[str] = []
    params: dict[str, Any] = {"lim": limit}
    if q:
        where.append("(std_code ILIKE :q OR canonical_name ILIKE :q)")
        params["q"] = f"%{q}%"
    if category:
        where.append("category = :cat")
        params["cat"] = category
    where_clause = " AND ".join(where) if where else "TRUE"
    rows = await session.execute(
        text(
            f"SELECT std_code, canonical_name, category, unit_default "
            f"FROM mart.standard_code WHERE {where_clause} "
            f"ORDER BY std_code LIMIT :lim"
        ),
        params,
    )
    out = [dict(r._mapping) for r in rows]
    await _cache_set(cache_key, out, ttl_sec=300)
    return out


# ---------------------------------------------------------------------------
# 2) products
# ---------------------------------------------------------------------------
@router.get("/products")
async def list_products(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("products"))],
    std_code: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    cache_key = f"dp:public_api:cache:products:{std_code or ''}:{q or ''}:{limit}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    where: list[str] = []
    params: dict[str, Any] = {"lim": limit}
    if std_code:
        where.append("std_code = :sc")
        params["sc"] = std_code
    if q:
        where.append("canonical_name ILIKE :q")
        params["q"] = f"%{q}%"
    where_clause = " AND ".join(where) if where else "TRUE"
    rows = await session.execute(
        text(
            f"SELECT product_id, std_code, canonical_name, grade, package_type, "
            f"       sale_unit_norm, weight_g, confidence_score "
            f"FROM mart.product_master WHERE {where_clause} "
            f"ORDER BY product_id LIMIT :lim"
        ),
        params,
    )
    out = [dict(r._mapping) for r in rows]
    await _cache_set(cache_key, out, ttl_sec=300)
    return out


# ---------------------------------------------------------------------------
# 3) prices.latest
# ---------------------------------------------------------------------------
@router.get("/prices/latest")
async def prices_latest(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("prices.latest"))],
    std_code: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    retailer_id: Annotated[int | None, Query(ge=1)] = None,
    region: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    channel: Annotated[str | None, Query(pattern="^(OFFLINE|ONLINE)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    cache_key = (
        f"dp:public_api:cache:prices_latest:{std_code or ''}:{retailer_id or ''}:"
        f"{region or ''}:{channel or ''}:{limit}"
    )
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    where = ["true"]
    params: dict[str, Any] = {"lim": limit}
    if std_code:
        where.append("pm.std_code = :sc")
        params["sc"] = std_code
    if retailer_id:
        where.append("sm.retailer_id = :r")
        params["r"] = retailer_id
    if region:
        where.append("sm.region_sido = :region")
        params["region"] = region
    if channel:
        where.append("sm.channel = :ch")
        params["ch"] = channel
    where_clause = " AND ".join(where)
    sql = (
        "SELECT DISTINCT ON (pm.product_id, sm.retailer_id) "
        "       pm.product_id, pm.std_code, pm.canonical_name, "
        "       sm.retailer_id, sm.region_sido, sm.region_sigungu, sm.channel, "
        "       pf.price_krw, pf.discount_price_krw, pf.unit_price_per_kg, "
        "       pf.observed_at "
        "  FROM mart.price_fact pf "
        "  JOIN mart.product_master pm ON pm.product_id = pf.product_id "
        "  JOIN mart.seller_master sm  ON sm.seller_id  = pf.seller_id "
        f" WHERE {where_clause} "
        " ORDER BY pm.product_id, sm.retailer_id, pf.observed_at DESC "
        " LIMIT :lim"
    )
    rows = await session.execute(text(sql), params)
    out = [dict(r._mapping) for r in rows]
    await _cache_set(cache_key, out, ttl_sec=60)
    return out


# ---------------------------------------------------------------------------
# 4) prices.daily
# ---------------------------------------------------------------------------
@router.get("/prices/daily")
async def prices_daily(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("prices.daily"))],
    std_code: Annotated[str, Query(min_length=1, max_length=64)],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    retailer_id: Annotated[int | None, Query(ge=1)] = None,
    region: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
) -> list[dict[str, Any]]:
    if from_date > to_date:
        raise app_errors.ValidationError("`from` must be <= `to`")
    cache_key = (
        f"dp:public_api:cache:prices_daily:{std_code}:{from_date.isoformat()}:"
        f"{to_date.isoformat()}:{retailer_id or ''}:{region or ''}"
    )
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    where = ["pm.std_code = :sc", "pf.observed_at >= :from", "pf.observed_at < :to_excl"]
    params: dict[str, Any] = {
        "sc": std_code,
        "from": datetime.combine(from_date, datetime.min.time()).replace(tzinfo=UTC),
        "to_excl": datetime.combine(to_date, datetime.min.time()).replace(tzinfo=UTC).replace(
            day=to_date.day
        ),
    }
    # to_date 포함 — observed_at < (to_date + 1일).
    params["to_excl"] = datetime.combine(to_date, datetime.min.time()).replace(tzinfo=UTC)
    # day-by-day end exclusive: 더 안전한 표현 — observed_at::date 비교.
    where = ["pm.std_code = :sc", "pf.observed_at::date BETWEEN :from AND :to"]
    params = {"sc": std_code, "from": from_date, "to": to_date}
    if retailer_id:
        where.append("sm.retailer_id = :r")
        params["r"] = retailer_id
    if region:
        where.append("sm.region_sido = :region")
        params["region"] = region
    where_clause = " AND ".join(where)
    sql = (
        "SELECT pf.observed_at::date AS day, "
        "       pm.std_code, "
        "       AVG(pf.price_krw)::numeric(14,2) AS avg_price_krw, "
        "       MIN(pf.price_krw) AS min_price_krw, "
        "       MAX(pf.price_krw) AS max_price_krw, "
        "       COUNT(*) AS sample_count "
        "  FROM mart.price_fact pf "
        "  JOIN mart.product_master pm ON pm.product_id = pf.product_id "
        "  JOIN mart.seller_master sm  ON sm.seller_id  = pf.seller_id "
        f" WHERE {where_clause} "
        " GROUP BY pf.observed_at::date, pm.std_code "
        " ORDER BY day"
    )
    rows = await session.execute(text(sql), params)
    out = [dict(r._mapping) for r in rows]
    await _cache_set(cache_key, out, ttl_sec=300)
    return out


# ---------------------------------------------------------------------------
# 5) prices.series
# ---------------------------------------------------------------------------
@router.get("/prices/series")
async def prices_series(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("prices.series"))],
    product_id: Annotated[int, Query(ge=1)],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
) -> list[dict[str, Any]]:
    if from_date > to_date:
        raise app_errors.ValidationError("`from` must be <= `to`")
    cache_key = (
        f"dp:public_api:cache:prices_series:{product_id}:"
        f"{from_date.isoformat()}:{to_date.isoformat()}"
    )
    cached = await _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    sql = (
        "SELECT pf.observed_at, pf.price_krw, pf.discount_price_krw, "
        "       sm.retailer_id, sm.region_sido "
        "  FROM mart.price_fact pf "
        "  JOIN mart.seller_master sm ON sm.seller_id = pf.seller_id "
        " WHERE pf.product_id = :pid "
        "   AND pf.observed_at::date BETWEEN :from AND :to "
        " ORDER BY pf.observed_at"
    )
    rows = await session.execute(
        text(sql), {"pid": product_id, "from": from_date, "to": to_date}
    )
    out = [dict(r._mapping) for r in rows]
    await _cache_set(cache_key, out, ttl_sec=180)
    return out


# ---------------------------------------------------------------------------
# 6) retailers / sellers — 4.2.4 stub 호환 유지 (products.read 필요)
# ---------------------------------------------------------------------------
@router.get("/retailers")
async def list_retailers(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("retailers"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT retailer_id, retailer_code, retailer_name, retailer_type, "
            "       business_no, head_office_addr "
            "FROM mart.retailer_master_view "
            "ORDER BY retailer_id LIMIT :lim"
        ),
        {"lim": limit},
    )
    return [dict(r._mapping) for r in rows]


@router.get("/sellers")
async def list_sellers(
    session: SessionDep,
    ctx: Annotated[PublicAuthContext, Depends(require_endpoint("sellers"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT seller_id, retailer_id, seller_code, seller_name, channel, "
            "       region_sido, region_sigungu, address "
            "FROM mart.seller_master_view "
            "ORDER BY seller_id LIMIT :lim"
        ),
        {"lim": limit},
    )
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# audit.public_api_usage middleware
# ---------------------------------------------------------------------------
def _coerce_inet(value: str | None) -> str | None:
    """INET 캐스팅 가능한 IP 만 통과. 'testclient' 같은 hostname → None."""
    if not value:
        return None
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


async def record_usage_async(
    *,
    api_key_id: int,
    endpoint: str,
    scope: str | None,
    status_code: int,
    duration_ms: int,
    ip_addr: str | None,
) -> None:
    """audit.public_api_usage 1 row INSERT.

    sync session + asyncio.to_thread — TestClient 환경에서 매 요청마다 event loop 가
    재생성되어 async engine 의 loop binding 이 깨지는 케이스를 회피.
    """
    import asyncio

    from app.db.sync_session import get_sync_sessionmaker

    # 'testclient' 같은 비-IP 호스트명은 INET 캐스팅 실패 — None 으로 변환.
    safe_ip = _coerce_inet(ip_addr)

    def _do() -> None:
        sm = get_sync_sessionmaker()
        with sm() as session:
            session.execute(
                text(
                    "INSERT INTO audit.public_api_usage "
                    "(api_key_id, endpoint, scope, status_code, duration_ms, ip_addr) "
                    "VALUES (:k, :ep, :sc, :code, :dur, CAST(:ip AS INET))"
                ),
                {
                    "k": api_key_id,
                    "ep": endpoint,
                    "sc": scope,
                    "code": status_code,
                    "dur": duration_ms,
                    "ip": safe_ip,
                },
            )
            session.commit()

    try:
        await asyncio.to_thread(_do)
    except Exception:
        logger.exception("public_api_usage.insert_failed")


__all__ = [
    "ENDPOINT_REQUIRED_SCOPES",
    "PublicAuthContext",
    "_get_redis",
    "record_usage_async",
    "require_endpoint",
    "router",
]


_ = (Response, time)  # silence unused — Response/time can be used by future extensions
