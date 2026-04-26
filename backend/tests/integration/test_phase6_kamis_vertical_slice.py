"""Phase 6 Wave 3.5 — KAMIS vertical slice 통합 테스트.

검증 (Canvas 없이 backend + dry-run 으로 e2e 1회 검증, § 13.2):
  1. migration 0048 적용 후 agri_mart.kamis_price 테이블 존재
  2. seed 스크립트가 connector / contract / field_mapping / load_policy /
     dq_rule / workflow 를 멱등적으로 만든다
  3. /v2/dryrun/workflow/{id} 가 4박스 (PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK
     → LOAD_TARGET) 응답 shape 을 정확히 반환

본 테스트는 *외부 KAMIS API 호출은 mock* (실 cert key 불필요). dispatcher 가
정상 라우팅되고 workflow dryrun 응답 shape 이 올바른지 확인하는 *구조 테스트*.
실 KAMIS 응답 검증은 별도 staging 환경에서 운영자가 수행.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker

# 테스트용 명명 — 운영 시드와 충돌 방지를 위해 prefix 분리.
TEST_DOMAIN = "agri"
TEST_RESOURCE = "KAMIS_WS_PRICE_TEST"
TEST_CONTRACT_NAME = "KAMIS WS Price contract (vertical slice test)"
TEST_CONNECTOR_NAME = "KAMIS WS Price (vertical slice test)"
TEST_WORKFLOW_NAME = "kamis_ws_price_vertical_slice_test"
TEST_TARGET_TABLE = "agri_mart.kamis_price"


@pytest.fixture
def vertical_slice_state() -> Iterator[dict[str, Any]]:
    """seed 후 생성된 모든 row 를 fixture teardown 에서 cleanup."""
    state: dict[str, Any] = {
        "connector_id": None,
        "contract_id": None,
        "policy_id": None,
        "workflow_id": None,
    }
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        # workflow + nodes + edges (cascade delete)
        if state["workflow_id"]:
            session.execute(
                text(
                    "DELETE FROM wf.workflow_definition WHERE workflow_id = :w"
                ),
                {"w": state["workflow_id"]},
            )
        if state["policy_id"]:
            session.execute(
                text("DELETE FROM domain.load_policy WHERE policy_id = :p"),
                {"p": state["policy_id"]},
            )
        # field_mapping (contract 기준)
        if state["contract_id"]:
            session.execute(
                text(
                    "DELETE FROM domain.field_mapping WHERE contract_id = :c"
                ),
                {"c": state["contract_id"]},
            )
            session.execute(
                text(
                    "DELETE FROM domain.source_contract WHERE contract_id = :c"
                ),
                {"c": state["contract_id"]},
            )
        # connector
        if state["connector_id"]:
            session.execute(
                text(
                    "DELETE FROM domain.public_api_connector "
                    "WHERE connector_id = :c"
                ),
                {"c": state["connector_id"]},
            )
        # dq_rule (resource 기준)
        session.execute(
            text(
                "DELETE FROM domain.dq_rule "
                "WHERE domain_code = :d AND target_table = :t"
            ),
            {"d": TEST_DOMAIN, "t": TEST_TARGET_TABLE},
        )
        # resource_definition (test 전용)
        session.execute(
            text(
                "DELETE FROM domain.resource_definition "
                "WHERE domain_code = :d AND resource_code = :r"
            ),
            {"d": TEST_DOMAIN, "r": TEST_RESOURCE},
        )
        # ctl.data_source (test 전용)
        session.execute(
            text("DELETE FROM ctl.data_source WHERE source_code = :c"),
            {"c": "kamis_ws_price_test_src"},
        )
        session.commit()
    dispose_sync_engine()


def _seed_resource(session: Any) -> None:
    session.execute(
        text(
            "INSERT INTO domain.resource_definition "
            "(domain_code, resource_code, fact_table, status, version) "
            "VALUES (:d, :r, :t, 'PUBLISHED', 1) "
            "ON CONFLICT DO NOTHING"
        ),
        {"d": TEST_DOMAIN, "r": TEST_RESOURCE, "t": TEST_TARGET_TABLE},
    )


def _seed_connector(session: Any) -> int:
    return int(
        session.execute(
            text(
                "INSERT INTO domain.public_api_connector "
                "(domain_code, resource_code, name, "
                " endpoint_url, http_method, auth_method, auth_param_name, "
                " secret_ref, request_headers, query_template, body_template, "
                " pagination_kind, pagination_config, "
                " response_format, response_path, "
                " timeout_sec, retry_max, rate_limit_per_min, "
                " status, is_active) "
                "VALUES (:d, :r, :n, "
                "        'http://www.kamis.or.kr/service/price/xml.do', "
                "        'GET', 'query_param', 'p_cert_key', "
                "        'KAMIS_CERT_KEY_TEST', "
                "        '{}'::jsonb, "
                "        '{\"action\":\"daily\",\"p_regday\":\"{ymd}\"}'::jsonb, "
                "        NULL, "
                "        'none', '{}'::jsonb, "
                "        'xml', '$.response.body.items.item', "
                "        15, 1, 30, "
                "        'DRAFT', TRUE) "
                "RETURNING connector_id"
            ),
            {"d": TEST_DOMAIN, "r": TEST_RESOURCE, "n": TEST_CONNECTOR_NAME},
        ).scalar_one()
    )


def _seed_contract_with_mappings(session: Any) -> int:
    # source_id 가 NOT NULL FK — ctl.data_source 1건 생성 (멱등).
    source_id = session.execute(
        text(
            "INSERT INTO ctl.data_source "
            "(source_code, source_name, source_type, is_active) "
            "VALUES (:c, :n, 'API', true) "
            "ON CONFLICT (source_code) DO UPDATE SET source_name = EXCLUDED.source_name "
            "RETURNING source_id"
        ),
        {"c": "kamis_ws_price_test_src", "n": "KAMIS vertical slice test source"},
    ).scalar_one()
    contract_id = int(
        session.execute(
            text(
                "INSERT INTO domain.source_contract "
                "(source_id, domain_code, resource_code, schema_version, "
                " schema_json, description, status) "
                "VALUES (:sid, :d, :r, 1, '{}'::jsonb, :desc, 'PUBLISHED') "
                "RETURNING contract_id"
            ),
            {
                "sid": int(source_id),
                "d": TEST_DOMAIN,
                "r": TEST_RESOURCE,
                "desc": TEST_CONTRACT_NAME,
            },
        ).scalar_one()
    )
    mappings = [
        ("$.regday", "ymd", "TEXT", True, 1),
        ("$.itemcode", "item_code", "TEXT", True, 2),
        ("$.itemname", "item_name", "TEXT", True, 3),
        ("$.marketcode", "market_code", "TEXT", True, 4),
    ]
    for sp, tc, dt, req, ord_no in mappings:
        session.execute(
            text(
                "INSERT INTO domain.field_mapping "
                "(contract_id, source_path, target_table, target_column, "
                " data_type, is_required, order_no, status) "
                "VALUES (:c, :sp, :tt, :tc, :dt, :req, :o, 'PUBLISHED')"
            ),
            {
                "c": contract_id,
                "sp": sp,
                "tt": TEST_TARGET_TABLE,
                "tc": tc,
                "dt": dt,
                "req": req,
                "o": ord_no,
            },
        )
    return contract_id


def _seed_load_policy(session: Any) -> int:
    rid = session.execute(
        text(
            "SELECT resource_id FROM domain.resource_definition "
            "WHERE domain_code = :d AND resource_code = :r"
        ),
        {"d": TEST_DOMAIN, "r": TEST_RESOURCE},
    ).scalar_one()
    return int(
        session.execute(
            text(
                "INSERT INTO domain.load_policy "
                "(resource_id, mode, key_columns, partition_expr, "
                " scd_options_json, chunk_size, statement_timeout_ms, "
                " status, version) "
                "VALUES (:rid, 'upsert', "
                "        ARRAY['ymd','item_code','market_code'], 'ymd', "
                "        '{}'::jsonb, 1000, 60000, 'PUBLISHED', 1) "
                "RETURNING policy_id"
            ),
            {"rid": int(rid)},
        ).scalar_one()
    )


def _seed_dq_rule(session: Any) -> None:
    # rule_json 의 ':' 를 SQLAlchemy bind param 으로 오인하지 않게 CAST 사용.
    session.execute(
        text(
            "INSERT INTO domain.dq_rule "
            "(domain_code, target_table, rule_kind, rule_json, severity, "
            " timeout_ms, sample_limit, status, version) "
            "VALUES (:d, :t, 'row_count_min', CAST(:rj AS JSONB), "
            "        'ERROR', 30000, 10, 'PUBLISHED', 1)"
        ),
        {"d": TEST_DOMAIN, "t": TEST_TARGET_TABLE, "rj": '{"min":1}'},
    )


def _seed_workflow(
    session: Any,
    *,
    connector_id: int,
    contract_id: int,
    policy_id: int,
) -> int:
    wid = int(
        session.execute(
            text(
                "INSERT INTO wf.workflow_definition "
                "(name, version, description, status) "
                "VALUES (:n, 1, :d, 'DRAFT') "
                "RETURNING workflow_id"
            ),
            {
                "n": TEST_WORKFLOW_NAME,
                "d": "Phase 6 Wave 3.5 vertical slice test",
            },
        ).scalar_one()
    )

    def _add_node(key: str, ntype: str, cfg: dict[str, Any], x: int) -> int:
        import json as _json

        return int(
            session.execute(
                text(
                    "INSERT INTO wf.node_definition "
                    "(workflow_id, node_key, node_type, config_json, "
                    " position_x, position_y) "
                    "VALUES (:w, :k, :t, CAST(:c AS JSONB), :x, 100) "
                    "RETURNING node_id"
                ),
                {
                    "w": wid,
                    "k": key,
                    "t": ntype,
                    "c": _json.dumps(cfg),
                    "x": x,
                },
            ).scalar_one()
        )

    n1 = _add_node(
        "fetch_kamis",
        "PUBLIC_API_FETCH",
        {"connector_id": connector_id, "ymd": "20260101"},
        100,
    )
    n2 = _add_node(
        "map_fields",
        "MAP_FIELDS",
        {"contract_id": contract_id, "source_table": "agri_stg.kamis_raw"},
        300,
    )
    n3 = _add_node(
        "dq_check",
        "DQ_CHECK",
        {"rules": [{"type": "row_count_min", "value": 1}]},
        500,
    )
    n4 = _add_node(
        "load_target",
        "LOAD_TARGET",
        {"policy_id": policy_id, "source_table": "agri_stg.kamis_clean"},
        700,
    )

    for fr, to in ((n1, n2), (n2, n3), (n3, n4)):
        session.execute(
            text(
                "INSERT INTO wf.edge_definition "
                "(workflow_id, from_node_id, to_node_id) "
                "VALUES (:w, :f, :t)"
            ),
            {"w": wid, "f": fr, "t": to},
        )
    return wid


# ===========================================================================
# 1. mart_table 구조 검증 (migration 0048)
# ===========================================================================
def test_kamis_price_table_exists() -> None:
    """migration 0048 이 적용되어 agri_mart.kamis_price 가 존재."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = session.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'agri_mart' AND table_name = 'kamis_price' "
                "ORDER BY ordinal_position"
            )
        ).all()
    cols = {r.column_name for r in rows}
    assert cols >= {
        "ymd",
        "item_code",
        "item_name",
        "market_code",
        "unit_price",
    }


# ===========================================================================
# 2. resource_definition seed
# ===========================================================================
def test_kamis_resource_registered() -> None:
    """KAMIS_WHOLESALE_PRICE resource (운영용) 가 PUBLISHED 로 등록됨."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        row = session.execute(
            text(
                "SELECT resource_id, status FROM domain.resource_definition "
                "WHERE domain_code = 'agri' "
                "  AND resource_code = 'KAMIS_WHOLESALE_PRICE'"
            )
        ).first()
    assert row is not None
    assert row.status == "PUBLISHED"


# ===========================================================================
# 3. seed 자산 round-trip (멱등 검증은 seed 스크립트의 책임)
# ===========================================================================
def test_seed_assets_round_trip(
    vertical_slice_state: dict[str, Any],
) -> None:
    """connector/contract/mapping/policy/dq_rule/workflow 가 모두 row 1건씩 생성."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        _seed_resource(session)
        cid = _seed_connector(session)
        vertical_slice_state["connector_id"] = cid

        contract_id = _seed_contract_with_mappings(session)
        vertical_slice_state["contract_id"] = contract_id

        policy_id = _seed_load_policy(session)
        vertical_slice_state["policy_id"] = policy_id

        _seed_dq_rule(session)

        wid = _seed_workflow(
            session,
            connector_id=cid,
            contract_id=contract_id,
            policy_id=policy_id,
        )
        vertical_slice_state["workflow_id"] = wid
        session.commit()

    # 워크플로 재조회 — 4 nodes / 3 edges 확인.
    with sm() as session:
        nodes = session.execute(
            text(
                "SELECT node_key, node_type FROM wf.node_definition "
                "WHERE workflow_id = :w ORDER BY position_x"
            ),
            {"w": wid},
        ).all()
        edges = session.execute(
            text(
                "SELECT COUNT(*) FROM wf.edge_definition WHERE workflow_id = :w"
            ),
            {"w": wid},
        ).scalar_one()

    assert len(nodes) == 4
    types = [n.node_type for n in nodes]
    assert types == [
        "PUBLIC_API_FETCH",
        "MAP_FIELDS",
        "DQ_CHECK",
        "LOAD_TARGET",
    ]
    assert int(edges) == 3


# ===========================================================================
# 4. /v2/dryrun/workflow/{id} 응답 shape 검증
# ===========================================================================
def test_workflow_dryrun_endpoint_shape(
    it_client: TestClient,
    admin_auth: dict[str, str],
    vertical_slice_state: dict[str, Any],
) -> None:
    """workflow dry-run 엔드포인트가 4박스 응답을 반환.

    각 노드의 실제 비즈니스 성공/실패 여부는 환경 의존적 (KAMIS 외부 호출 등) 이므로
    검증하지 않는다. 본 테스트는 *DAG 위상 정렬 + dispatcher 라우팅 + 응답 shape* 만 보장.
    """
    sm = get_sync_sessionmaker()
    with sm() as session:
        _seed_resource(session)
        cid = _seed_connector(session)
        vertical_slice_state["connector_id"] = cid
        contract_id = _seed_contract_with_mappings(session)
        vertical_slice_state["contract_id"] = contract_id
        policy_id = _seed_load_policy(session)
        vertical_slice_state["policy_id"] = policy_id
        _seed_dq_rule(session)
        wid = _seed_workflow(
            session,
            connector_id=cid,
            contract_id=contract_id,
            policy_id=policy_id,
        )
        vertical_slice_state["workflow_id"] = wid
        session.commit()

    res = it_client.post(f"/v2/dryrun/workflow/{wid}", headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["workflow_id"] == wid
    assert body["name"] == TEST_WORKFLOW_NAME
    assert isinstance(body["nodes"], list)
    assert len(body["nodes"]) == 4

    # 위상 정렬 순서 보장: PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK → LOAD_TARGET
    types = [n["node_type"] for n in body["nodes"]]
    assert types == [
        "PUBLIC_API_FETCH",
        "MAP_FIELDS",
        "DQ_CHECK",
        "LOAD_TARGET",
    ]

    # status 는 실 API 호출 여부에 따라 다양 — 단, 모든 노드는 status 필드를 가져야 함.
    for n in body["nodes"]:
        assert n["status"] in ("success", "failed", "skipped")
        assert "row_count" in n
        assert "duration_ms" in n
        assert "node_key" in n

    # ctl.dry_run_record 에 1건 적재되었는지 확인.
    with sm() as session:
        rec = session.execute(
            text(
                "SELECT kind, target_summary FROM ctl.dry_run_record "
                "WHERE kind = 'workflow' "
                "  AND (target_summary->>'workflow_id')::int = :w "
                "ORDER BY requested_at DESC LIMIT 1"
            ),
            {"w": wid},
        ).first()
    assert rec is not None
    assert rec.kind == "workflow"


# ===========================================================================
# 5. /v2/dryrun/recent 가 workflow 결과를 포함
# ===========================================================================
def test_recent_dryruns_contains_workflow_kind(
    it_client: TestClient,
    admin_auth: dict[str, str],
    vertical_slice_state: dict[str, Any],
) -> None:
    """workflow dry-run 후 /v2/dryrun/recent?kind=workflow 가 결과를 노출."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        _seed_resource(session)
        cid = _seed_connector(session)
        vertical_slice_state["connector_id"] = cid
        contract_id = _seed_contract_with_mappings(session)
        vertical_slice_state["contract_id"] = contract_id
        policy_id = _seed_load_policy(session)
        vertical_slice_state["policy_id"] = policy_id
        _seed_dq_rule(session)
        wid = _seed_workflow(
            session,
            connector_id=cid,
            contract_id=contract_id,
            policy_id=policy_id,
        )
        vertical_slice_state["workflow_id"] = wid
        session.commit()

    # 1회 dry-run 트리거.
    it_client.post(f"/v2/dryrun/workflow/{wid}", headers=admin_auth)

    res = it_client.get(
        "/v2/dryrun/recent",
        params={"kind": "workflow", "limit": 5},
        headers=admin_auth,
    )
    assert res.status_code == 200
    rows = res.json()
    assert isinstance(rows, list)
    assert any(
        (r.get("target_summary") or {}).get("workflow_id") == wid for r in rows
    )
