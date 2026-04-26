"""Phase 5.2.7 STEP 10 — multi-domain /public/v2/{domain}/* 통합 테스트.

검증:
  1. cache_fingerprint — domain/resource/scope/api_key 모두 포함, 차이 시 다른 키.
  2. map_v1_to_v2_compat — v1 retailer_allowlist 가 agri 로 자동 매핑 (Q1).
  3. extract_domain_allowlist — 도메인 미등록 시 DomainScopeError.
  4. /public/v2/agri/standard-codes — 200 + AGRI_FOOD namespace.
  5. /public/v2/pos/standard-codes — 200 + PAYMENT_METHOD + STORE_CHANNEL.
  6. /public/v2/pos/TRANSACTION/latest — pos_mart.pos_transaction limit.
  7. 도메인 미인가 → 403.
  8. 잘못된 X-API-Key → 401.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.core.security import hash_password
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.public_v2 import (
    DomainScope,
    DomainScopeError,
    api_key_has_domain,
    cache_fingerprint,
    extract_domain_allowlist,
    map_v1_to_v2_compat,
)


@pytest.fixture
def cleanup_keys() -> Iterator[list[int]]:
    keys: list[int] = []
    yield keys
    if not keys:
        dispose_sync_engine()
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(
            text("DELETE FROM ctl.api_key WHERE api_key_id = ANY(:ids)"),
            {"ids": keys},
        )
        session.commit()
    dispose_sync_engine()


def _create_api_key(
    *,
    client_name: str,
    raw_key: str,
    scope: list[str],
    domain_resource_allowlist: dict[str, object],
) -> int:
    sm = get_sync_sessionmaker()
    prefix, _, _ = raw_key.partition(".")
    pw_hash = hash_password(raw_key)
    with sm() as session:
        api_key_id = session.execute(
            text(
                "INSERT INTO ctl.api_key "
                "(key_prefix, key_hash, client_name, scope, "
                " rate_limit_per_min, is_active, "
                " domain_resource_allowlist) "
                "VALUES (:p, :h, :c, :s, 60, TRUE, CAST(:dra AS JSONB)) "
                "RETURNING api_key_id"
            ),
            {
                "p": prefix,
                "h": pw_hash,
                "c": client_name,
                "s": scope,
                "dra": _json(domain_resource_allowlist),
            },
        ).scalar_one()
        session.commit()
    return int(api_key_id)


def _json(obj: object) -> str:
    import json as _json_mod

    return _json_mod.dumps(obj, default=str)


# ===========================================================================
# 1. cache_fingerprint
# ===========================================================================
def test_cache_fingerprint_distinct_per_domain() -> None:
    scope_a = DomainScope("agri", "PRICE_FACT", {"retailer_ids": [1, 2]})
    scope_b = DomainScope("pos", "TRANSACTION", {"shop_ids": [10]})
    fa = cache_fingerprint(
        api_version="v2",
        domain_code="agri",
        resource_code="PRICE_FACT",
        route="latest",
        query_params={"limit": 100},
        api_key_id=1,
        scope=scope_a,
    )
    fb = cache_fingerprint(
        api_version="v2",
        domain_code="pos",
        resource_code="TRANSACTION",
        route="latest",
        query_params={"limit": 100},
        api_key_id=1,
        scope=scope_b,
    )
    assert fa != fb
    assert fa.startswith("public:v2:agri:")
    assert fb.startswith("public:v2:pos:")


def test_cache_fingerprint_distinct_per_scope() -> None:
    s1 = DomainScope("agri", "PRICE_FACT", {"retailer_ids": [1]})
    s2 = DomainScope("agri", "PRICE_FACT", {"retailer_ids": [1, 2]})
    f1 = cache_fingerprint(
        api_version="v2",
        domain_code="agri",
        resource_code="PRICE_FACT",
        route="latest",
        query_params={},
        api_key_id=1,
        scope=s1,
    )
    f2 = cache_fingerprint(
        api_version="v2",
        domain_code="agri",
        resource_code="PRICE_FACT",
        route="latest",
        query_params={},
        api_key_id=1,
        scope=s2,
    )
    assert f1 != f2


# ===========================================================================
# 2. v1 retailer_allowlist → v2 agri 자동 매핑 (Q1)
# ===========================================================================
def test_v1_retailer_allowlist_auto_maps_to_agri() -> None:
    merged = map_v1_to_v2_compat(
        domain_resource_allowlist={},
        retailer_allowlist=[1, 2, 3],
    )
    assert "agri" in merged
    assert merged["agri"]["resources"]["prices"]["retailer_ids"] == [1, 2, 3]


def test_explicit_v2_takes_precedence() -> None:
    """이미 agri.resources.prices.retailer_ids 가 있으면 v1 값으로 덮어쓰지 않음."""
    merged = map_v1_to_v2_compat(
        domain_resource_allowlist={
            "agri": {"resources": {"prices": {"retailer_ids": [9, 9]}}}
        },
        retailer_allowlist=[1, 2, 3],
    )
    assert merged["agri"]["resources"]["prices"]["retailer_ids"] == [9, 9]


# ===========================================================================
# 3. extract_domain_allowlist
# ===========================================================================
def test_extract_unauthorized_domain() -> None:
    with pytest.raises(DomainScopeError):
        extract_domain_allowlist(
            {"agri": {"resources": {"prices": {}}}},
            domain_code="pos",
            resource_code="TRANSACTION",
        )


def test_extract_unauthorized_resource() -> None:
    with pytest.raises(DomainScopeError):
        extract_domain_allowlist(
            {"agri": {"resources": {"prices": {}}}},
            domain_code="agri",
            resource_code="PRICE_FACT",  # 등록 X
        )


def test_extract_returns_scope() -> None:
    scope = extract_domain_allowlist(
        {"agri": {"resources": {"prices": {"retailer_ids": [1, 2]}}}},
        domain_code="agri",
        resource_code="prices",
    )
    assert scope.domain_code == "agri"
    assert scope.allowlist == {"retailer_ids": [1, 2]}
    assert scope.has_id("retailer_ids", 1) is True
    assert scope.has_id("retailer_ids", 99) is False


def test_api_key_has_domain() -> None:
    assert (
        api_key_has_domain(
            {"agri": {}, "pos": {}}, domain_code="pos"
        )
        is True
    )
    assert (
        api_key_has_domain({"agri": {}}, domain_code="pharma") is False
    )


# ===========================================================================
# 4. /public/v2/agri/standard-codes endpoint
# ===========================================================================
def test_public_v2_agri_standard_codes(  # type: ignore[no-untyped-def]
    it_app, cleanup_keys: list[int]
) -> None:
    """agri 도메인 등록 + AGRI_FOOD namespace 시드 후 endpoint 호출."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        # agri 도메인 + AGRI_FOOD namespace 가 없으면 시드.
        session.execute(
            text(
                "INSERT INTO domain.domain_definition "
                "(domain_code, name, schema_yaml, status, version) "
                "VALUES ('agri','농축산물','{}'::jsonb,'PUBLISHED',1) "
                "ON CONFLICT DO NOTHING"
            )
        )
        session.execute(
            text(
                "INSERT INTO domain.standard_code_namespace "
                "(domain_code, name, description, std_code_table) "
                "VALUES ('agri','AGRI_FOOD','agri 도메인 식품 표준코드',"
                "        'mart.standard_code') "
                "ON CONFLICT DO NOTHING"
            )
        )
        session.commit()
    raw = f"agritest_{secrets.token_hex(4)}.{secrets.token_hex(8)}"
    key_id = _create_api_key(
        client_name="step10-agri-it",
        raw_key=raw,
        scope=["products.read"],
        domain_resource_allowlist={"agri": {"resources": {"standard_codes": {}}}},
    )
    cleanup_keys.append(key_id)
    r = it_app.get(
        "/public/v2/agri/standard-codes",
        headers={"X-API-Key": raw},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == "agri"
    assert any(ns["name"] == "AGRI_FOOD" for ns in body["namespaces"])


def test_public_v2_pos_standard_codes_via_alias(  # type: ignore[no-untyped-def]
    it_app, cleanup_keys: list[int]
) -> None:
    raw = f"postest_{secrets.token_hex(4)}.{secrets.token_hex(8)}"
    key_id = _create_api_key(
        client_name="step10-pos-it",
        raw_key=raw,
        scope=["products.read"],
        domain_resource_allowlist={"pos": {"resources": {"standard_codes": {}}}},
    )
    cleanup_keys.append(key_id)
    r = it_app.get(
        "/public/v2/pos/standard-codes?namespace=PAYMENT_METHOD",
        headers={"X-API-Key": raw},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == "pos"
    assert len(body["namespaces"]) == 1
    pm_codes = {c["std_code"] for c in body["codes"]["PAYMENT_METHOD"]}
    assert "CARD" in pm_codes
    assert "MOBILE_PAY" in pm_codes


# ===========================================================================
# 5. /public/v2/{domain}/{resource}/latest endpoint
# ===========================================================================
def test_public_v2_pos_transaction_latest(  # type: ignore[no-untyped-def]
    it_app, cleanup_keys: list[int]
) -> None:
    raw = f"postxn_{secrets.token_hex(4)}.{secrets.token_hex(8)}"
    key_id = _create_api_key(
        client_name="step10-pos-txn-it",
        raw_key=raw,
        scope=["aggregates.read"],
        domain_resource_allowlist={
            "pos": {"resources": {"TRANSACTION": {}}}
        },
    )
    cleanup_keys.append(key_id)
    r = it_app.get(
        "/public/v2/pos/TRANSACTION/latest?limit=10",
        headers={"X-API-Key": raw},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resource"] == "TRANSACTION"
    assert body["table"] == "pos_mart.pos_transaction"
    assert len(body["rows"]) > 0


# ===========================================================================
# 6. 권한 거부 케이스
# ===========================================================================
def test_public_v2_unauthorized_domain_returns_403(  # type: ignore[no-untyped-def]
    it_app, cleanup_keys: list[int]
) -> None:
    raw = f"limited_{secrets.token_hex(4)}.{secrets.token_hex(8)}"
    key_id = _create_api_key(
        client_name="step10-limited-it",
        raw_key=raw,
        scope=["products.read"],
        domain_resource_allowlist={"agri": {"resources": {"prices": {}}}},
    )
    cleanup_keys.append(key_id)
    # pos 도메인 미인가.
    r = it_app.get(
        "/public/v2/pos/TRANSACTION/latest",
        headers={"X-API-Key": raw},
    )
    assert r.status_code == 403


def test_public_v2_invalid_api_key_returns_401(it_app) -> None:  # type: ignore[no-untyped-def]
    r = it_app.get(
        "/public/v2/agri/standard-codes",
        headers={"X-API-Key": "nonexistent.fake"},
    )
    assert r.status_code == 401


def test_public_v2_missing_api_key_header_returns_401(it_app) -> None:  # type: ignore[no-untyped-def]
    r = it_app.get("/public/v2/agri/standard-codes")
    assert r.status_code == 401


# ===========================================================================
# 7. Phase 5 자동 호환: v1 retailer_allowlist 만 가진 api_key 가 agri 접근 가능
# ===========================================================================
def test_v1_only_api_key_accesses_agri_via_compat(  # type: ignore[no-untyped-def]
    it_app, cleanup_keys: list[int]
) -> None:
    raw = f"v1compat_{secrets.token_hex(4)}.{secrets.token_hex(8)}"
    sm = get_sync_sessionmaker()
    prefix, _, _ = raw.partition(".")
    pw_hash = hash_password(raw)
    with sm() as session:
        # v1 형 — retailer_allowlist 만 있고 domain_resource_allowlist 는 빈 dict.
        api_key_id = session.execute(
            text(
                "INSERT INTO ctl.api_key "
                "(key_prefix, key_hash, client_name, scope, "
                " rate_limit_per_min, is_active, retailer_allowlist, "
                " domain_resource_allowlist) "
                "VALUES (:p, :h, 'step10-v1compat', "
                "        ARRAY['products.read']::text[], 60, TRUE, "
                "        ARRAY[1,2]::bigint[], '{}'::jsonb) "
                "RETURNING api_key_id"
            ),
            {"p": prefix, "h": pw_hash},
        ).scalar_one()
        session.commit()
    cleanup_keys.append(int(api_key_id))

    # agri 도메인의 standard-codes 는 resources 안에 등록 안 되어 있어 통과 못함.
    # 하지만 *prices* resource 는 v1 매핑으로 자동 등록되므로 prices/latest 시도.
    # standard-codes 는 'standard_codes' resource 가 필요한데 v1 매핑이 prices 만 등록 →
    # 따라서 standard-codes 로 가면 403.
    r = it_app.get(
        "/public/v2/agri/standard-codes",
        headers={"X-API-Key": raw},
    )
    # standard-codes 는 *domain 자체* 만 인가 확인 (resource 별 X) — 통과해야.
    assert r.status_code == 200, r.text
