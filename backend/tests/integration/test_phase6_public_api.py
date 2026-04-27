"""Phase 6 Wave 1 — Public API Connector + PUBLIC_API_FETCH 노드 통합 테스트.

검증:
  1. ConnectorSpec save/load round-trip.
  2. render_template — {ymd} {page} 등 치환.
  3. parse_response_body — JSON / XML.
  4. extract_path — JSONPath-lite.
  5. PUBLIC_API_FETCH 노드 dispatcher 등록.
  6. dispatcher 14 종 (PUBLIC_API_FETCH 포함).
  7. dry_run=True 시 외부 호출 0건.
  8. /v2/connectors/public-api CRUD endpoint.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.nodes_v2 import NodeV2Context, get_v2_runner, list_v2_node_types
from app.domain.public_api import (
    AuthMethod,
    ConnectorSpec,
    HttpMethod,
    PaginationKind,
    ResponseFormat,
    load_spec_from_db,
    save_spec_to_db,
)
from app.domain.public_api.parser import (
    extract_path,
    normalize_to_rows,
    parse_response_body,
)
from app.domain.public_api.spec import render_template


@pytest.fixture
def cleanup() -> Iterator[dict[str, list[Any]]]:
    state: dict[str, list[Any]] = {"connector_ids": [], "tables": []}
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in state["tables"]:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        if state["connector_ids"]:
            session.execute(
                text("DELETE FROM domain.public_api_run WHERE connector_id = ANY(:ids)"),
                {"ids": state["connector_ids"]},
            )
            session.execute(
                text("DELETE FROM domain.public_api_connector WHERE connector_id = ANY(:ids)"),
                {"ids": state["connector_ids"]},
            )
        session.commit()
    dispose_sync_engine()


# ===========================================================================
# 1. parser
# ===========================================================================
def test_parse_response_body_json() -> None:
    out = parse_response_body('{"a": 1, "b": [2,3]}', response_format="json")
    assert out == {"a": 1, "b": [2, 3]}


def test_parse_response_body_xml() -> None:
    xml = "<root><items><item><name>apple</name><price>1500</price></item></items></root>"
    out = parse_response_body(xml, response_format="xml")
    assert isinstance(out, dict)
    assert out["root"]["items"]["item"]["name"] == "apple"


def test_extract_path_basic() -> None:
    data = {"response": {"body": {"items": {"item": [{"a": 1}, {"a": 2}]}}}}
    rows = extract_path(data, "$.response.body.items.item")
    assert isinstance(rows, list)
    assert rows == [{"a": 1}, {"a": 2}]


def test_extract_path_index() -> None:
    data = {"a": [10, 20, 30]}
    assert extract_path(data, "$.a[0]") == 10
    assert extract_path(data, "$.a[2]") == 30


def test_normalize_to_rows() -> None:
    assert normalize_to_rows([{"a": 1}]) == [{"a": 1}]
    assert normalize_to_rows({"a": 1}) == [{"a": 1}]
    assert normalize_to_rows(None) == []
    assert normalize_to_rows([1, 2]) == [{"value": 1}, {"value": 2}]


# ===========================================================================
# 2. render_template
# ===========================================================================
def test_render_template_full_substitution() -> None:
    """{ymd} 단독이면 원본 타입 보존."""
    tmpl = {"date": "{ymd}", "page": "{page}", "fixed": "value"}
    out = render_template(tmpl, {"ymd": "2026-04-27", "page": 5})
    assert out == {"date": "2026-04-27", "page": 5, "fixed": "value"}


def test_render_template_partial_substitution() -> None:
    """부분 치환은 str 강제."""
    tmpl = {"q": "prefix-{ymd}-suffix"}
    out = render_template(tmpl, {"ymd": "2026-04-27"})
    assert out == {"q": "prefix-2026-04-27-suffix"}


# ===========================================================================
# 3. ConnectorSpec save/load round-trip
# ===========================================================================
def _ensure_domain(session: Any, code: str) -> None:
    session.execute(
        text(
            "INSERT INTO domain.domain_definition "
            "(domain_code, name, schema_yaml, status, version) "
            "VALUES (:c, 'p6 it', '{}'::jsonb, 'PUBLISHED', 1) "
            "ON CONFLICT DO NOTHING"
        ),
        {"c": code},
    )


def test_connector_spec_round_trip(cleanup: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        _ensure_domain(session, "agri")
        spec = ConnectorSpec(
            connector_id=None,
            domain_code="agri",
            resource_code="P6_TEST",
            name=f"p6 test {secrets.token_hex(3)}",
            endpoint_url="http://example.invalid/api",
            http_method=HttpMethod.GET,
            auth_method=AuthMethod.QUERY_PARAM,
            auth_param_name="cert_key",
            secret_ref="P6_TEST_KEY",
            query_template={"p_action": "daily", "p_regday": "{ymd}"},
            pagination_kind=PaginationKind.PAGE_NUMBER,
            pagination_config={"page_param_name": "p_no", "page_size": 50},
            response_format=ResponseFormat.XML,
            response_path="$.response.body.items.item",
            timeout_sec=20,
        )
        cid = save_spec_to_db(session, spec, created_by=None)
        cleanup["connector_ids"].append(cid)
        session.commit()
    with sm() as session:
        loaded = load_spec_from_db(session, connector_id=cid)
    assert loaded is not None
    assert loaded.connector_id == cid
    assert loaded.endpoint_url == "http://example.invalid/api"
    assert loaded.auth_method == AuthMethod.QUERY_PARAM
    assert loaded.auth_param_name == "cert_key"
    assert loaded.query_template == {"p_action": "daily", "p_regday": "{ymd}"}
    assert loaded.pagination_kind == PaginationKind.PAGE_NUMBER
    assert loaded.response_format == ResponseFormat.XML
    assert loaded.response_path == "$.response.body.items.item"


# ===========================================================================
# 4. dispatcher 20 종 (Phase 8.4 — Phase 7 Wave 1A/1B 추가 반영)
# ===========================================================================
def test_dispatcher_includes_public_api_fetch() -> None:
    types = list_v2_node_types()
    assert "PUBLIC_API_FETCH" in types
    # Phase 6: 14 → Phase 7 Wave 1A (+3: WEBHOOK/FILE_UPLOAD/DB_INCREMENTAL)
    # → Phase 7 Wave 1B (+3: OCR_RESULT_INGEST/CRAWLER_RESULT_INGEST/CDC_EVENT_FETCH) = 20
    assert len(types) == 20
    runner = get_v2_runner("PUBLIC_API_FETCH")
    assert runner.node_type == "PUBLIC_API_FETCH"


# ===========================================================================
# 5. PUBLIC_API_FETCH dry_run (외부 호출 0)
# ===========================================================================
def test_public_api_fetch_dry_run(cleanup: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        _ensure_domain(session, "agri")
        spec = ConnectorSpec(
            connector_id=None,
            domain_code="agri",
            resource_code="P6_DRY",
            name=f"p6 dry {secrets.token_hex(3)}",
            endpoint_url="http://example.invalid/never-called",
            response_format=ResponseFormat.JSON,
            response_path="$",
        )
        cid = save_spec_to_db(session, spec, created_by=None)
        cleanup["connector_ids"].append(cid)
        session.commit()
    with sm() as session:
        ctx = NodeV2Context(
            session=session,
            pipeline_run_id=9_999_800,
            node_run_id=9_999_800,
            node_key="p6_dry",
            domain_code="agri",
            user_id=None,
        )
        runner = get_v2_runner("PUBLIC_API_FETCH")
        out = runner.run(
            ctx,
            {"connector_id": cid, "dry_run": True},
        )
    assert out.status == "success"
    assert out.payload["dry_run"] is True
    assert out.payload["connector_id"] == cid


def test_public_api_fetch_missing_connector() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = NodeV2Context(
            session=session,
            pipeline_run_id=9_999_801,
            node_run_id=9_999_801,
            node_key="p6_missing",
            domain_code="agri",
            user_id=None,
        )
        runner = get_v2_runner("PUBLIC_API_FETCH")
        out = runner.run(ctx, {"connector_id": 999_999_999, "dry_run": True})
    assert out.status == "failed"
    assert out.payload["reason"] == "connector_not_found"


# ===========================================================================
# 6. /v2/connectors/public-api endpoint smoke
# ===========================================================================
def test_connectors_endpoint_create_get_list(  # type: ignore[no-untyped-def]
    it_client, admin_auth, cleanup: dict[str, list[Any]]
) -> None:
    body = {
        "domain_code": "agri",
        "resource_code": f"P6_API_{secrets.token_hex(3)}",
        "name": f"p6 endpoint test {secrets.token_hex(3)}",
        "endpoint_url": "http://example.invalid/api",
        "auth_method": "query_param",
        "auth_param_name": "cert_key",
        "secret_ref": "P6_TEST_KEY",
        "query_template": {"p_action": "daily", "p_regday": "{ymd}"},
        "response_format": "xml",
        "response_path": "$.response.body.items.item",
    }
    r = it_client.post("/v2/connectors/public-api", json=body, headers=admin_auth)
    assert r.status_code == 201, r.text
    cid = r.json()["connector_id"]
    cleanup["connector_ids"].append(cid)

    # GET 1건
    r2 = it_client.get(f"/v2/connectors/public-api/{cid}", headers=admin_auth)
    assert r2.status_code == 200
    assert r2.json()["status"] == "DRAFT"

    # LIST
    r3 = it_client.get(
        "/v2/connectors/public-api?domain_code=agri", headers=admin_auth
    )
    assert r3.status_code == 200
    ids = [x["connector_id"] for x in r3.json()]
    assert cid in ids


def test_connectors_endpoint_status_transition(  # type: ignore[no-untyped-def]
    it_client, admin_auth, cleanup: dict[str, list[Any]]
) -> None:
    body = {
        "domain_code": "agri",
        "resource_code": f"P6_TR_{secrets.token_hex(3)}",
        "name": f"p6 transition test {secrets.token_hex(3)}",
        "endpoint_url": "http://example.invalid/api",
    }
    r = it_client.post("/v2/connectors/public-api", json=body, headers=admin_auth)
    cid = r.json()["connector_id"]
    cleanup["connector_ids"].append(cid)

    # DRAFT → REVIEW.
    r2 = it_client.post(
        f"/v2/connectors/public-api/{cid}/transition",
        json={"target_status": "REVIEW"},
        headers=admin_auth,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "REVIEW"

    # REVIEW → APPROVED.
    r3 = it_client.post(
        f"/v2/connectors/public-api/{cid}/transition",
        json={"target_status": "APPROVED"},
        headers=admin_auth,
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "APPROVED"

    # APPROVED → PUBLISHED.
    r4 = it_client.post(
        f"/v2/connectors/public-api/{cid}/transition",
        json={"target_status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert r4.status_code == 200
    assert r4.json()["status"] == "PUBLISHED"

    # PUBLISHED 는 삭제 불가.
    r5 = it_client.delete(
        f"/v2/connectors/public-api/{cid}", headers=admin_auth
    )
    assert r5.status_code == 409


def test_connectors_endpoint_invalid_transition(  # type: ignore[no-untyped-def]
    it_client, admin_auth, cleanup: dict[str, list[Any]]
) -> None:
    body = {
        "domain_code": "agri",
        "resource_code": f"P6_BAD_{secrets.token_hex(3)}",
        "name": f"p6 bad transition {secrets.token_hex(3)}",
        "endpoint_url": "http://example.invalid/api",
    }
    r = it_client.post("/v2/connectors/public-api", json=body, headers=admin_auth)
    cid = r.json()["connector_id"]
    cleanup["connector_ids"].append(cid)

    # DRAFT → APPROVED 직진 불가.
    r2 = it_client.post(
        f"/v2/connectors/public-api/{cid}/transition",
        json={"target_status": "APPROVED"},
        headers=admin_auth,
    )
    assert r2.status_code == 422
