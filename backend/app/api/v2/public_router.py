"""Public API v2 — `/public/v2/{domain}/*` (Phase 5.2.7 STEP 10).

Q3 답변 — 단일 OpenAPI + domain tag 분리. /public/v2/docs 에서 전체 표시,
프론트엔드가 domain 별 필터링된 docs 뷰를 제공.

흐름:
  1. X-API-Key → resolve api_key.
  2. domain_resource_allowlist 에 {domain} 가 있는지 확인 (DomainScopeError → 403).
  3. resource scope 추출 → DomainScope.
  4. domain × resource 별 cache fingerprint 로 Redis 응답 캐시.
  5. RLS GUC 설정 (도메인 인지 — 아래 set_domain_scope_gucs).

본 STEP MVP:
  * agri + pos 두 도메인의 *공통 패턴* endpoint 2종:
    - GET /public/v2/{domain}/standard-codes
    - GET /public/v2/{domain}/{resource}/latest
  * 도메인별 fact_table / canonical_table 은 domain.resource_definition 에서 dynamic 로딩.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import verify_password
from app.deps import SessionDep
from app.domain.public_v2 import (
    DomainScopeError,
    cache_fingerprint,
    extract_domain_allowlist,
    map_v1_to_v2_compat,
)
from app.models.ctl import ApiKey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["public-v2"])


# ---------------------------------------------------------------------------
# auth — v1 public 의 _resolve_api_key 재사용성을 위해 mini 버전 inline
# ---------------------------------------------------------------------------
async def _resolve_api_key(session: AsyncSession, raw_key: str) -> ApiKey:
    if not raw_key or "." not in raw_key:
        raise HTTPException(status_code=401, detail="invalid api key format")
    prefix = raw_key.split(".", 1)[0]
    row = (
        await session.execute(
            text(
                "SELECT api_key_id, key_prefix, key_hash, client_name, scope, "
                "       rate_limit_per_min, is_active, retailer_allowlist, "
                "       domain_resource_allowlist, expires_at, revoked_at "
                "FROM ctl.api_key WHERE key_prefix = :p AND is_active = TRUE LIMIT 1"
            ),
            {"p": prefix},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown api key")
    if row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="api key revoked")
    if not verify_password(raw_key, row.key_hash):
        raise HTTPException(status_code=401, detail="invalid api key")
    api_key = ApiKey()
    api_key.api_key_id = int(row.api_key_id)
    api_key.key_prefix = str(row.key_prefix)
    api_key.client_name = str(row.client_name)
    api_key.scope = list(row.scope or [])
    api_key.rate_limit_per_min = int(row.rate_limit_per_min)
    api_key.is_active = bool(row.is_active)
    api_key.retailer_allowlist = list(row.retailer_allowlist or [])
    api_key.domain_resource_allowlist = dict(row.domain_resource_allowlist or {})
    return api_key


def _scope_or_403(
    *,
    api_key: ApiKey,
    domain_code: str,
    resource_code: str,
) -> Any:
    merged = map_v1_to_v2_compat(
        api_key.domain_resource_allowlist,
        api_key.retailer_allowlist,
    )
    try:
        return extract_domain_allowlist(
            merged, domain_code=domain_code, resource_code=resource_code
        )
    except DomainScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Redis 캐시 — fingerprint v2 확장 (Q4)
# ---------------------------------------------------------------------------
import redis.asyncio as aioredis  # noqa: E402

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
# endpoint 1 — /public/v2/{domain}/standard-codes
# ---------------------------------------------------------------------------
@router.get("/{domain_code}/standard-codes")
async def list_standard_codes(
    request: Request,
    session: SessionDep,
    domain_code: str = Path(min_length=2, max_length=30, pattern=r"^[a-z][a-z0-9_]*$"),
    namespace: str | None = Query(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> JSONResponse:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    api_key = await _resolve_api_key(session, x_api_key)
    # standard-codes 자체는 *도메인 단위* — resource_code 는 'standard_codes' 가상.
    merged = map_v1_to_v2_compat(
        api_key.domain_resource_allowlist, api_key.retailer_allowlist
    )
    if domain_code not in merged:
        raise HTTPException(
            status_code=403,
            detail=f"api_key not authorized for domain {domain_code!r}",
        )
    # cache fingerprint.
    from app.domain.public_v2.scope import DomainScope

    scope = DomainScope(
        domain_code=domain_code,
        resource_code="standard_codes",
        allowlist={},
    )
    fp = cache_fingerprint(
        api_version="v2",
        domain_code=domain_code,
        resource_code="standard_codes",
        route="list",
        query_params={"namespace": namespace or ""},
        api_key_id=api_key.api_key_id,
        scope=scope,
    )
    cached = await _cache_get(fp)
    if cached is not None:
        return JSONResponse(content=cached, headers={"X-Cache": "HIT"})

    # registry 에서 도메인의 namespace 목록.
    rows = (
        await session.execute(
            text(
                "SELECT name, std_code_table FROM domain.standard_code_namespace "
                "WHERE domain_code = :d "
                + (" AND name = :n" if namespace else "")
                + " ORDER BY name"
            ),
            {"d": domain_code, **({"n": namespace} if namespace else {})},
        )
    ).all()
    namespaces = [
        {"name": r.name, "std_code_table": r.std_code_table} for r in rows
    ]
    # 각 namespace 의 std_code 일부 (limit 100 — table 별).
    codes: dict[str, list[Mapping[str, Any]]] = {}
    for ns in namespaces:
        tbl = ns["std_code_table"]
        if not tbl or "." not in tbl:
            codes[ns["name"]] = []
            continue
        try:
            crows = (
                await session.execute(
                    text(
                        f"SELECT std_code, display_name "
                        f"FROM {tbl} "
                        f"WHERE is_active = TRUE ORDER BY std_code LIMIT 100"
                    )
                )
            ).all()
            codes[ns["name"]] = [
                {"std_code": str(r.std_code), "display_name": str(r.display_name)}
                for r in crows
            ]
        except Exception as exc:
            logger.warning("std_code query failed for %s: %s", tbl, exc)
            codes[ns["name"]] = []

    body = {
        "domain": domain_code,
        "namespaces": namespaces,
        "codes": codes,
    }
    await _cache_set(fp, body, ttl_sec=300)
    return JSONResponse(content=body, headers={"X-Cache": "MISS"})


# ---------------------------------------------------------------------------
# endpoint 2 — /public/v2/{domain}/{resource}/latest
# ---------------------------------------------------------------------------
@router.get("/{domain_code}/{resource_code}/latest")
async def fetch_latest(
    request: Request,
    session: SessionDep,
    domain_code: str = Path(min_length=2, max_length=30, pattern=r"^[a-z][a-z0-9_]*$"),
    resource_code: str = Path(min_length=2, max_length=30, pattern=r"^[A-Za-z][A-Za-z0-9_]*$"),
    limit: int = Query(default=100, ge=1, le=1000),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> JSONResponse:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    api_key = await _resolve_api_key(session, x_api_key)
    scope = _scope_or_403(
        api_key=api_key, domain_code=domain_code, resource_code=resource_code
    )

    # registry 조회 — fact_table 또는 canonical_table.
    res_row = (
        await session.execute(
            text(
                "SELECT fact_table, canonical_table FROM domain.resource_definition "
                "WHERE domain_code = :d AND resource_code = :r "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"d": domain_code, "r": resource_code},
        )
    ).first()
    if res_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"resource {domain_code}.{resource_code} not registered",
        )
    target_table = res_row.fact_table or res_row.canonical_table
    if not target_table:
        raise HTTPException(
            status_code=500, detail="resource has no fact/canonical table"
        )

    fp = cache_fingerprint(
        api_version="v2",
        domain_code=domain_code,
        resource_code=resource_code,
        route="latest",
        query_params={"limit": limit},
        api_key_id=api_key.api_key_id,
        scope=scope,
    )
    cached = await _cache_get(fp)
    if cached is not None:
        return JSONResponse(content=cached, headers={"X-Cache": "HIT"})

    # 단순 SELECT — 정렬은 본 테이블의 PK 기준 DESC.
    # FQDN safety: registry 의 값을 *읽기만* 하므로 SQL injection 위험 낮음.
    safe_table = _validate_fqdn(target_table)
    rows = (
        await session.execute(
            text(f"SELECT * FROM {safe_table} ORDER BY 1 DESC LIMIT :lim"),
            {"lim": limit},
        )
    ).mappings().all()
    body = {
        "domain": domain_code,
        "resource": resource_code,
        "table": safe_table,
        "limit": limit,
        "rows": jsonable_encoder([dict(r) for r in rows]),
    }
    await _cache_set(fp, body, ttl_sec=60)
    return JSONResponse(content=body, headers={"X-Cache": "MISS"})


def _validate_fqdn(fqdn: str) -> str:
    import re

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$", fqdn):
        raise HTTPException(status_code=500, detail=f"invalid fqdn: {fqdn!r}")
    return fqdn


__all__ = ["router"]
