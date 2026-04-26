"""Phase 6 Wave 3.5 — KAMIS vertical slice seed script.

Canvas 없이 backend 만으로 KAMIS OpenAPI → MAP_FIELDS → DQ_CHECK → LOAD_TARGET
파이프라인을 e2e 검증하기 위한 자산 시드.

작성:
  1. domain.public_api_connector — KAMIS 도매시장 일별가격 connector (DRAFT)
  2. domain.source_contract       — KAMIS_WHOLESALE_PRICE contract
  3. domain.field_mapping (rows)  — KAMIS XML → agri_mart.kamis_price 매핑
  4. domain.dq_rule               — row_count_min + range
  5. domain.load_policy           — upsert + key=[ymd,item_code,market_code]
  6. wf.workflow_definition       — PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK → LOAD_TARGET

멱등성: 같은 식별자가 이미 있으면 SKIP (재실행 안전).

사용:
    cd backend
    .venv/Scripts/python ../scripts/seed_kamis_vertical_slice.py
    .venv/Scripts/python ../scripts/seed_kamis_vertical_slice.py --dry-run

후속:
  POST /v2/dryrun/workflow/{workflow_id} → 4박스 dry-run 검증
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker

CONNECTOR_NAME = "KAMIS 도매시장 일별가격"
CONNECTOR_RESOURCE = "KAMIS_WHOLESALE_PRICE"
DOMAIN_CODE = "agri"
WORKFLOW_NAME = "kamis_wholesale_price_daily"
TARGET_TABLE = "agri_mart.kamis_price"


def _ensure_connector(session: Session) -> int:
    existing = session.execute(
        text(
            "SELECT connector_id FROM domain.public_api_connector "
            "WHERE domain_code = :d AND resource_code = :r AND name = :n"
        ),
        {"d": DOMAIN_CODE, "r": CONNECTOR_RESOURCE, "n": CONNECTOR_NAME},
    ).scalar_one_or_none()
    if existing:
        print(f"[skip] connector_id={existing} already exists ({CONNECTOR_NAME})")
        return int(existing)
    cid = session.execute(
        text(
            "INSERT INTO domain.public_api_connector "
            "(domain_code, resource_code, name, description, "
            " endpoint_url, http_method, auth_method, auth_param_name, secret_ref, "
            " request_headers, query_template, body_template, "
            " pagination_kind, pagination_config, "
            " response_format, response_path, "
            " timeout_sec, retry_max, rate_limit_per_min, "
            " schedule_cron, schedule_enabled, status, is_active) "
            "VALUES "
            "(:d, :r, :n, :desc, "
            " :url, 'GET', 'query_param', :auth_name, :secret_ref, "
            " '{}'::jsonb, CAST(:qt AS JSONB), NULL, "
            " 'NONE', '{}'::jsonb, "
            " 'XML', :rp, "
            " 30, 3, 30, "
            " :cron, FALSE, 'DRAFT', TRUE) "
            "RETURNING connector_id"
        ),
        {
            "d": DOMAIN_CODE,
            "r": CONNECTOR_RESOURCE,
            "n": CONNECTOR_NAME,
            "desc": "KAMIS OpenAPI 도매시장 일별가격 (Phase 6 Wave 3.5 vertical slice)",
            "url": "http://www.kamis.or.kr/service/price/xml.do",
            "auth_name": "p_cert_key",
            "secret_ref": "KAMIS_CERT_KEY",
            "qt": (
                '{"action":"daily","p_product_cls_code":"01",'
                '"p_regday":"{ymd}","p_returntype":"xml"}'
            ),
            "rp": "$.response.body.items.item",
            "cron": "0 9 * * *",
        },
    ).scalar_one()
    print(f"[create] connector_id={cid} ({CONNECTOR_NAME})")
    return int(cid)


def _ensure_contract(session: Session) -> int:
    existing = session.execute(
        text(
            "SELECT contract_id FROM domain.source_contract "
            "WHERE domain_code = :d AND resource_code = :r"
        ),
        {"d": DOMAIN_CODE, "r": CONNECTOR_RESOURCE},
    ).scalar_one_or_none()
    if existing:
        print(f"[skip] contract_id={existing} already exists")
        return int(existing)
    cid = session.execute(
        text(
            "INSERT INTO domain.source_contract "
            "(domain_code, resource_code, name, schema_yaml, status, schema_version) "
            "VALUES (:d, :r, :n, '{}'::jsonb, 'PUBLISHED', 1) "
            "RETURNING contract_id"
        ),
        {
            "d": DOMAIN_CODE,
            "r": CONNECTOR_RESOURCE,
            "n": "KAMIS 도매시장 가격 contract v1",
        },
    ).scalar_one()
    print(f"[create] contract_id={cid} ({CONNECTOR_RESOURCE})")
    return int(cid)


# (source_path, target_column, transform_expr, data_type, is_required)
MAPPINGS = [
    ("$.regday", "ymd", "date.normalize_ymd", "TEXT", True),
    ("$.itemcode", "item_code", None, "TEXT", True),
    ("$.itemname", "item_name", None, "TEXT", True),
    ("$.marketcode", "market_code", None, "TEXT", True),
    ("$.marketname", "market_name", None, "TEXT", False),
    ("$.dpr1", "unit_price", "number.parse_decimal", "NUMERIC", False),
    ("$.unit", "unit_name", None, "TEXT", False),
    ("$.kindname", "grade", None, "TEXT", False),
]


def _ensure_field_mappings(session: Session, contract_id: int) -> int:
    existing = session.execute(
        text(
            "SELECT COUNT(*) FROM domain.field_mapping WHERE contract_id = :cid"
        ),
        {"cid": contract_id},
    ).scalar_one()
    if existing and int(existing) > 0:
        print(f"[skip] field_mapping rows={existing} already exist for contract")
        return int(existing)
    inserted = 0
    for order_no, (sp, tc, expr, dtype, req) in enumerate(MAPPINGS, start=1):
        session.execute(
            text(
                "INSERT INTO domain.field_mapping "
                "(contract_id, source_path, target_table, target_column, "
                " transform_expr, data_type, is_required, order_no, status) "
                "VALUES (:cid, :sp, :tt, :tc, :expr, :dt, :req, :ord, 'PUBLISHED')"
            ),
            {
                "cid": contract_id,
                "sp": sp,
                "tt": TARGET_TABLE,
                "tc": tc,
                "expr": expr,
                "dt": dtype,
                "req": req,
                "ord": order_no,
            },
        )
        inserted += 1
    print(f"[create] field_mapping rows={inserted} for contract_id={contract_id}")
    return inserted


def _ensure_load_policy(session: Session) -> int:
    resource_id = session.execute(
        text(
            "SELECT resource_id FROM domain.resource_definition "
            "WHERE domain_code = :d AND resource_code = :r"
        ),
        {"d": DOMAIN_CODE, "r": CONNECTOR_RESOURCE},
    ).scalar_one_or_none()
    if resource_id is None:
        raise RuntimeError(
            f"resource_definition ({DOMAIN_CODE}/{CONNECTOR_RESOURCE}) 없음 — "
            "migration 0048 이 적용됐는지 확인."
        )
    existing = session.execute(
        text(
            "SELECT policy_id FROM domain.load_policy "
            "WHERE resource_id = :rid"
        ),
        {"rid": resource_id},
    ).scalar_one_or_none()
    if existing:
        print(f"[skip] load_policy policy_id={existing} already exists")
        return int(existing)
    pid = session.execute(
        text(
            "INSERT INTO domain.load_policy "
            "(resource_id, mode, key_columns, partition_expr, scd_options_json, "
            " chunk_size, statement_timeout_ms, status, version) "
            "VALUES (:rid, 'upsert', "
            "        ARRAY['ymd','item_code','market_code'], 'ymd', "
            "        '{}'::jsonb, 1000, 60000, 'PUBLISHED', 1) "
            "RETURNING policy_id"
        ),
        {"rid": int(resource_id)},
    ).scalar_one()
    print(f"[create] load_policy policy_id={pid} (upsert + 3-key)")
    return int(pid)


def _ensure_dq_rules(session: Session) -> int:
    existing = session.execute(
        text(
            "SELECT COUNT(*) FROM domain.dq_rule "
            "WHERE domain_code = :d AND target_table = :t"
        ),
        {"d": DOMAIN_CODE, "t": TARGET_TABLE},
    ).scalar_one()
    if existing and int(existing) > 0:
        print(f"[skip] dq_rule rows={existing} already exist")
        return int(existing)
    rules: list[dict[str, Any]] = [
        {
            "rule_kind": "row_count_min",
            "rule_json": {"min": 1},
            "severity": "ERROR",
            "description": "최소 1건 이상 적재되어야 한다",
        },
        {
            "rule_kind": "range",
            "rule_json": {"column": "unit_price", "min": 0, "max": 10_000_000},
            "severity": "WARN",
            "description": "단가가 음수이거나 천만원 초과면 의심",
        },
    ]
    for r in rules:
        session.execute(
            text(
                "INSERT INTO domain.dq_rule "
                "(domain_code, target_table, rule_kind, rule_json, severity, "
                " timeout_ms, sample_limit, status, version, description) "
                "VALUES (:d, :t, :kind, CAST(:rj AS JSONB), :sev, "
                "        30000, 10, 'PUBLISHED', 1, :desc)"
            ),
            {
                "d": DOMAIN_CODE,
                "t": TARGET_TABLE,
                "kind": r["rule_kind"],
                "rj": __import__("json").dumps(r["rule_json"]),
                "sev": r["severity"],
                "desc": r["description"],
            },
        )
    print(f"[create] dq_rule rows={len(rules)} (row_count_min + range)")
    return len(rules)


def _ensure_workflow(
    session: Session,
    *,
    connector_id: int,
    contract_id: int,
    policy_id: int,
) -> int:
    existing = session.execute(
        text(
            "SELECT workflow_id FROM wf.workflow_definition WHERE name = :n"
        ),
        {"n": WORKFLOW_NAME},
    ).scalar_one_or_none()
    if existing:
        print(f"[skip] workflow_id={existing} already exists ({WORKFLOW_NAME})")
        return int(existing)
    wid = session.execute(
        text(
            "INSERT INTO wf.workflow_definition "
            "(name, version, description, status, schedule_cron, schedule_enabled) "
            "VALUES (:n, 1, :d, 'DRAFT', '0 9 * * *', FALSE) "
            "RETURNING workflow_id"
        ),
        {
            "n": WORKFLOW_NAME,
            "d": (
                "Phase 6 Wave 3.5 vertical slice — KAMIS 일별가격 자동 적재 "
                "(PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK → LOAD_TARGET)"
            ),
        },
    ).scalar_one()

    json = __import__("json")

    def _add_node(
        key: str,
        ntype: str,
        cfg: dict[str, Any],
        x: int,
        y: int,
    ) -> int:
        nid = session.execute(
            text(
                "INSERT INTO wf.node_definition "
                "(workflow_id, node_key, node_type, config_json, position_x, position_y) "
                "VALUES (:wid, :k, :t, CAST(:c AS JSONB), :x, :y) "
                "RETURNING node_id"
            ),
            {
                "wid": int(wid),
                "k": key,
                "t": ntype,
                "c": json.dumps(cfg, ensure_ascii=False),
                "x": x,
                "y": y,
            },
        ).scalar_one()
        return int(nid)

    n_fetch = _add_node(
        "fetch_kamis",
        "PUBLIC_API_FETCH",
        {
            "connector_id": connector_id,
            "ymd": "{ymd}",
            "output_table": "agri_stg.kamis_raw_{run_date}",
        },
        100,
        100,
    )
    n_map = _add_node(
        "map_fields",
        "MAP_FIELDS",
        {
            "contract_id": contract_id,
            "source_table": "agri_stg.kamis_raw_{run_date}",
            "target_table": "agri_stg.kamis_clean_{run_date}",
        },
        300,
        100,
    )
    n_dq = _add_node(
        "dq_check",
        "DQ_CHECK",
        {
            "rules": [
                {"type": "row_count_min", "value": 1},
            ],
            "source_table": "agri_stg.kamis_clean_{run_date}",
        },
        500,
        100,
    )
    n_load = _add_node(
        "load_target",
        "LOAD_TARGET",
        {
            "policy_id": policy_id,
            "source_table": "agri_stg.kamis_clean_{run_date}",
            "target_table": TARGET_TABLE,
        },
        700,
        100,
    )

    def _add_edge(from_id: int, to_id: int) -> None:
        session.execute(
            text(
                "INSERT INTO wf.edge_definition "
                "(workflow_id, from_node_id, to_node_id) "
                "VALUES (:w, :f, :t)"
            ),
            {"w": int(wid), "f": from_id, "t": to_id},
        )

    _add_edge(n_fetch, n_map)
    _add_edge(n_map, n_dq)
    _add_edge(n_dq, n_load)

    print(
        f"[create] workflow_id={wid} ({WORKFLOW_NAME}) — "
        f"4 nodes ({n_fetch}/{n_map}/{n_dq}/{n_load}) + 3 edges"
    )
    return int(wid)


def main() -> int:
    parser = argparse.ArgumentParser(description="KAMIS vertical slice seed")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 변경 없이 시연만",
    )
    args = parser.parse_args()

    sm = get_sync_sessionmaker()
    print("=" * 70)
    print("Phase 6 Wave 3.5 — KAMIS vertical slice seed")
    print("=" * 70)
    try:
        with sm() as session:
            connector_id = _ensure_connector(session)
            contract_id = _ensure_contract(session)
            _ensure_field_mappings(session, contract_id)
            policy_id = _ensure_load_policy(session)
            _ensure_dq_rules(session)
            workflow_id = _ensure_workflow(
                session,
                connector_id=connector_id,
                contract_id=contract_id,
                policy_id=policy_id,
            )

            if args.dry_run:
                session.rollback()
                print("\n[dry-run] rolled back. 실제 적용은 --dry-run 없이 재실행.")
            else:
                session.commit()
                print(
                    "\n[done] e2e 검증:\n"
                    f"  curl -X POST http://localhost:8000/v2/dryrun/workflow/{workflow_id}\n"
                    f"  → 4박스 dry-run 결과 확인"
                )
    finally:
        dispose_sync_engine()
    return 0


if __name__ == "__main__":
    sys.exit(main())
