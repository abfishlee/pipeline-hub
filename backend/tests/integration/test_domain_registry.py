"""Phase 5.2.1 — domain.* registry 통합 테스트.

검증:
  1. agri.yaml 로드 → domain.* 적재 + v1 mart.product_master 그대로 가리킴
  2. v1 회귀 — 기존 mart.price_fact 조회 영향 0
  3. 한 source 에 (agri, PRICE) + (pharma, PRICE) 동시 contract — selector 분기
  4. selector 우선순위 (endpoint > payload_type > jsonpath)
  5. compatibility check — backward / forward / breaking 판정
  6. /v2/domains GET (DOMAIN_ADMIN 인증)
  7. /v2/contracts evaluate-selector
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.registry import (
    check_schema_compatibility,
    load_domain_from_dict,
    match_resource_selector,
)
from app.domain.registry.selector import _ContractCandidate
from app.models.ctl import DataSource
from app.models.domain import (
    DomainDefinition,
    ResourceDefinition,
    SourceContract,
    StandardCodeNamespace,
)


@pytest.fixture
def cleanup_domain() -> Iterator[None]:
    yield
    sm = get_sync_sessionmaker()
    with sm() as session:
        # 본 테스트가 만든 도메인 (test_*) 만 정리.
        session.execute(
            delete(SourceContract).where(SourceContract.domain_code.like("test_%"))
        )
        session.execute(
            delete(StandardCodeNamespace).where(
                StandardCodeNamespace.domain_code.like("test_%")
            )
        )
        session.execute(
            delete(ResourceDefinition).where(
                ResourceDefinition.domain_code.like("test_%")
            )
        )
        session.execute(
            delete(DomainDefinition).where(DomainDefinition.domain_code.like("test_%"))
        )
        session.commit()
    dispose_sync_engine()


# ---------------------------------------------------------------------------
# 1. agri.yaml 로드 — v1 테이블 그대로 등록
# ---------------------------------------------------------------------------
def test_load_agri_yaml_points_to_v1_tables(cleanup_domain: None) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    agri_yaml = repo_root / "domains" / "agri.yaml"
    assert agri_yaml.exists(), f"agri.yaml not found at {agri_yaml}"

    sm = get_sync_sessionmaker()
    with sm() as session:
        # 본 yaml 의 domain_code 가 'agri' — 본 테스트의 cleanup 은 'test_*' 만
        # 정리하므로 미리 'test_agri' 로 변환해 등록.
        with open(agri_yaml, encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        spec["domain_code"] = f"test_agri_{secrets.token_hex(2)}"
        loaded = load_domain_from_dict(session, data=spec)
        session.commit()

        assert loaded.domain_code.startswith("test_agri_")
        assert "PRICE_FACT" in loaded.resource_ids
        assert "DAILY_AGG" in loaded.resource_ids

        # v1 테이블 경로 그대로.
        res = session.execute(
            text(
                "SELECT canonical_table, fact_table FROM domain.resource_definition "
                "WHERE resource_id = :rid"
            ),
            {"rid": loaded.resource_ids["PRICE_FACT"]},
        ).one()
        assert res.canonical_table == "mart.product_master"
        assert res.fact_table == "mart.price_fact"


# ---------------------------------------------------------------------------
# 2. v1 회귀 — registry 적재 후에도 mart.price_fact / product_master 영향 0
# ---------------------------------------------------------------------------
def test_registry_does_not_affect_v1_tables(cleanup_domain: None) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        # agri-like 도메인 등록.
        load_domain_from_dict(
            session,
            data={
                "domain_code": "test_v1regress",
                "name": "v1 회귀 검증",
                "resources": [
                    {
                        "resource_code": "PRICE_FACT",
                        "canonical_table": "mart.product_master",
                        "fact_table": "mart.price_fact",
                    }
                ],
            },
        )
        session.commit()

        # v1 mart.product_master 가 여전히 정상 query 가능 + ORM 통한 query 동작.
        from app.models.mart import ProductMaster

        # ORM query (v1 path) — 0 row 든 N row 든 *깨지지 않으면* OK.
        list(session.query(ProductMaster).limit(1).all())

        # 직접 SQL — schema 가 살아있음.
        cnt = session.execute(text("SELECT COUNT(*) FROM mart.price_fact")).scalar_one()
        assert cnt is not None  # 존재 자체 검증 (값은 무관).


# ---------------------------------------------------------------------------
# 3. 한 source 가 두 도메인의 contract 동시 보유 + selector 분기
# ---------------------------------------------------------------------------
def test_one_source_two_domain_contracts_selector(cleanup_domain: None) -> None:
    sm = get_sync_sessionmaker()
    suffix = secrets.token_hex(3).upper()
    with sm() as session:
        # 두 도메인 등록.
        for code, name in (("test_agri_x", "agri"), ("test_pharma_x", "pharma")):
            load_domain_from_dict(
                session,
                data={
                    "domain_code": code,
                    "name": name,
                    "resources": [{"resource_code": "PRICE", "fact_table": f"{code}.price_fact"}],
                },
            )
        # source 1개 시드.
        ds = DataSource(
            source_code=f"IT_DOMAIN_{suffix}",
            source_name="multi-domain source",
            source_type="API",
            is_active=True,
            config_json={},
        )
        session.add(ds)
        session.flush()

        # contract 2개 — 각각 다른 selector.
        c1 = SourceContract(
            source_id=ds.source_id,
            domain_code="test_agri_x",
            resource_code="PRICE",
            schema_version=1,
            schema_json={"fields": [{"name": "sku", "type": "string", "required": True}]},
            resource_selector_json={"endpoint": "/v1/retail/agri-prices"},
            compatibility_mode="backward",
        )
        c2 = SourceContract(
            source_id=ds.source_id,
            domain_code="test_pharma_x",
            resource_code="PRICE",
            schema_version=1,
            schema_json={"fields": [{"name": "drug_id", "type": "string", "required": True}]},
            resource_selector_json={"payload_type": "PHARMA_PRICE"},
            compatibility_mode="backward",
        )
        session.add_all([c1, c2])
        session.flush()

        cands = [
            _ContractCandidate(
                contract_id=c1.contract_id,
                domain_code="test_agri_x",
                resource_code="PRICE",
                schema_version=1,
                selector={"endpoint": "/v1/retail/agri-prices"},
            ),
            _ContractCandidate(
                contract_id=c2.contract_id,
                domain_code="test_pharma_x",
                resource_code="PRICE",
                schema_version=1,
                selector={"payload_type": "PHARMA_PRICE"},
            ),
        ]

        # endpoint 매치 → agri.
        m1 = match_resource_selector(
            payload={"items": []},
            request_endpoint="/v1/retail/agri-prices",
            candidates=cands,
        )
        assert m1 is not None
        assert m1.domain_code == "test_agri_x"
        assert m1.matched_by == "endpoint"

        # payload_type 매치 → pharma.
        m2 = match_resource_selector(
            payload={"type": "PHARMA_PRICE", "items": []},
            request_endpoint="/some/other",
            candidates=cands,
        )
        assert m2 is not None
        assert m2.domain_code == "test_pharma_x"
        assert m2.matched_by == "payload_type"

        # cleanup data_source — cleanup_domain 가 contract 만 정리.
        session.execute(
            delete(SourceContract).where(SourceContract.source_id == ds.source_id)
        )
        session.execute(text("DELETE FROM ctl.data_source WHERE source_id = :id"),
                        {"id": ds.source_id})
        session.commit()


# ---------------------------------------------------------------------------
# 4. selector 우선순위 검증
# ---------------------------------------------------------------------------
def test_selector_priority_endpoint_first() -> None:
    """endpoint, payload_type, jsonpath 모두 매치 가능한 상황 — endpoint 우선."""
    cands = [
        _ContractCandidate(
            contract_id=1, domain_code="d1", resource_code="r1", schema_version=1,
            selector={"endpoint": "/api/x"},
        ),
        _ContractCandidate(
            contract_id=2, domain_code="d2", resource_code="r2", schema_version=1,
            selector={"payload_type": "T"},
        ),
        _ContractCandidate(
            contract_id=3, domain_code="d3", resource_code="r3", schema_version=1,
            selector={"jsonpath": "$.x"},
        ),
    ]
    payload = {"type": "T", "x": 123}
    m = match_resource_selector(
        payload=payload, request_endpoint="/api/x", candidates=cands
    )
    assert m is not None
    assert m.contract_id == 1
    assert m.matched_by == "endpoint"


def test_selector_no_match_returns_none() -> None:
    cands = [
        _ContractCandidate(
            contract_id=1, domain_code="d1", resource_code="r1", schema_version=1,
            selector={"endpoint": "/api/y"},
        ),
    ]
    m = match_resource_selector(
        payload={}, request_endpoint="/api/x", candidates=cands
    )
    assert m is None


# ---------------------------------------------------------------------------
# 5. compatibility — backward / forward / breaking
# ---------------------------------------------------------------------------
def test_compatibility_backward_compatible() -> None:
    old = {"fields": [
        {"name": "sku", "type": "string", "required": True},
        {"name": "price", "type": "number", "required": True},
    ]}
    new = {"fields": [
        {"name": "sku", "type": "string", "required": True},
        {"name": "price", "type": "number", "required": True},
        {"name": "discount", "type": "number", "required": False},  # 추가 optional → OK
    ]}
    r = check_schema_compatibility(old_schema=old, new_schema=new, mode="backward")
    assert r.is_compatible
    assert "discount" in str(r.additive_changes)


def test_compatibility_backward_breaking_required_field_added() -> None:
    old = {"fields": [{"name": "sku", "type": "string", "required": True}]}
    new = {"fields": [
        {"name": "sku", "type": "string", "required": True},
        {"name": "vendor_id", "type": "string", "required": True},  # 새 required → backward break
    ]}
    r = check_schema_compatibility(old_schema=old, new_schema=new, mode="backward")
    assert not r.is_compatible
    assert any("vendor_id" in s for s in r.breaking_changes)


def test_compatibility_breaking_required_removed() -> None:
    old = {"fields": [
        {"name": "sku", "type": "string", "required": True},
        {"name": "price", "type": "number", "required": True},
    ]}
    new = {"fields": [
        {"name": "sku", "type": "string", "required": True},
    ]}
    r = check_schema_compatibility(old_schema=old, new_schema=new, mode="backward")
    assert not r.is_compatible
    assert any("price" in s for s in r.breaking_changes)


def test_compatibility_none_mode_always_compatible() -> None:
    old = {"fields": [{"name": "x", "type": "string", "required": True}]}
    new = {"fields": []}  # 모든 필드 제거 — 정상이라면 break 인데 mode=none 으로 skip.
    r = check_schema_compatibility(old_schema=old, new_schema=new, mode="none")
    assert r.is_compatible


# ---------------------------------------------------------------------------
# 6. v2 API — list_domains
# ---------------------------------------------------------------------------
def test_v2_domains_endpoint_lists_loaded(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_domain: None,
) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        load_domain_from_dict(
            session,
            data={
                "domain_code": "test_api_d",
                "name": "API endpoint test",
                "resources": [{"resource_code": "R1", "fact_table": "test_api_d.r1"}],
            },
        )
        session.commit()

    r = it_client.get("/v2/domains", headers=admin_auth)
    assert r.status_code == 200
    body = r.json()
    codes = [d["domain_code"] for d in body]
    assert "test_api_d" in codes


# ---------------------------------------------------------------------------
# 7. v2 API — evaluate-selector
# ---------------------------------------------------------------------------
def test_v2_contracts_evaluate_selector(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_domain: None,
) -> None:
    sm = get_sync_sessionmaker()
    suffix = secrets.token_hex(3).upper()
    with sm() as session:
        load_domain_from_dict(
            session,
            data={
                "domain_code": "test_eval",
                "name": "selector eval",
                "resources": [{"resource_code": "P", "fact_table": "test_eval.p"}],
            },
        )
        ds = DataSource(
            source_code=f"IT_EVAL_{suffix}",
            source_name="eval src",
            source_type="API",
            is_active=True,
            config_json={},
        )
        session.add(ds)
        session.flush()
        c = SourceContract(
            source_id=ds.source_id,
            domain_code="test_eval",
            resource_code="P",
            schema_version=1,
            resource_selector_json={"endpoint": "/test/eval"},
        )
        session.add(c)
        session.flush()
        sid = ds.source_id
        session.commit()

    r = it_client.post(
        "/v2/contracts/evaluate-selector",
        json={
            "source_id": sid,
            "payload": {},
            "request_endpoint": "/test/eval",
        },
        headers=admin_auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matched"] is True
    assert body["domain_code"] == "test_eval"
    assert body["matched_by"] == "endpoint"

    # cleanup ds + contract.
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(SourceContract).where(SourceContract.source_id == sid))
        session.execute(text("DELETE FROM ctl.data_source WHERE source_id = :id"), {"id": sid})
        session.commit()
