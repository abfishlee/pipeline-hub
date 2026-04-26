"""Phase 8 — 전체 화면에 데이터가 보이도록 풀 e2e 시드.

phase8_seed_synthetic_data.py 가 service_mart 만 시드한 것과 달리, 본 스크립트는
*모든 화면이 의미있는 데이터를 보여주도록* 자산 + 워크플로 + 실행 이력 + raw +
inbound event + 검수 큐 까지 모두 시드.

각 화면별 채워질 테이블:
  - Public API Connector       → domain.public_api_connector (4건)
  - Inbound Channel            → domain.inbound_channel (3건)
  - Field Mapping Designer     → domain.source_contract + field_mapping (4 + 30+)
  - Transform Designer (SQL)   → domain.sql_asset (3건)
  - Quality Workbench (DQ)     → domain.dq_rule (12건)
  - Quality Workbench (Std)    → domain.standard_code_namespace (1건)
  - Mart Workbench (Mart)      → domain.mart_design_draft (5건)
  - Mart Workbench (Policy)    → domain.load_policy (5건)
  - ETL Canvas                 → wf.workflow_definition (5건) + node + edge
  - Releases                   → wf.pipeline_release (4건)
  - Pipeline Runs              → run.pipeline_run (24건) + node_run (~120)
  - Operations Dashboard       → 위 모든 것 활용
  - Raw Objects                → raw.raw_object (40+ 건)
  - Collection Jobs            → ctl.ingest_job (24건)
  - Review Queue               → ctl.crowd_task (5건)
  - Inbound Events (audit)     → audit.inbound_event (15건)

멱등성: 같은 식별자로 INSERT 시도 시 ON CONFLICT DO NOTHING.
실행: cd backend && PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python ../scripts/phase8_seed_full_e2e.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker

if sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

NOW = datetime.now(UTC)
TODAY = date.today()

# 4 retailers 메타.
RETAILERS = [
    {
        "code": "emart",
        "name": "이마트",
        "url": "https://api.emart.example.com/v1/products",
        "resource": "PRICE",
        "target": "emart_mart.product_price",
    },
    {
        "code": "homeplus",
        "name": "홈플러스",
        "url": "https://api.homeplus.example.com/v2/promotions",
        "resource": "PROMO",
        "target": "homeplus_mart.product_promo",
    },
    {
        "code": "lottemart",
        "name": "롯데마트",
        "url": "https://api.lottemart.example.com/api/goods",
        "resource": "CANON",
        "target": "lottemart_mart.product_canon",
    },
    {
        "code": "hanaro",
        "name": "하나로마트",
        "url": "https://api.nh.example.com/agri/v1",
        "resource": "AGRI",
        "target": "hanaro_mart.agri_product",
    },
]


def _ensure_partition_for_today(session: Session) -> None:
    """run.pipeline_run 의 오늘 기준 ±7일 partition 보장 (없으면 생성)."""
    # 월별 partition — 현재 월 + 직전 월 모두 보장
    for delta_days in (-30, 0, 30):
        d = TODAY + timedelta(days=delta_days)
        ym = d.strftime("%Y_%m")
        first = d.replace(day=1)
        # 다음 달 1일
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1)
        else:
            next_first = first.replace(month=first.month + 1)
        try:
            session.execute(
                text(
                    f'CREATE TABLE IF NOT EXISTS run."pipeline_run_{ym}" '
                    f"PARTITION OF run.pipeline_run "
                    f"FOR VALUES FROM (:f) TO (:t)"
                ),
                {"f": first, "t": next_first},
            )
        except Exception:
            pass  # 이미 있을 수 있음
    session.commit()


# ============================================================================
# 1. Public API Connector (4 retailers)
# ============================================================================
def seed_connectors(session: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in RETAILERS:
        existing = session.execute(
            text(
                "SELECT connector_id FROM domain.public_api_connector "
                "WHERE domain_code = :d AND name = :n"
            ),
            {"d": r["code"], "n": f"{r['name']} {r['resource']} API"},
        ).scalar_one_or_none()
        if existing:
            out[r["code"]] = int(existing)
            continue
        cid = session.execute(
            text(
                "INSERT INTO domain.public_api_connector "
                "(domain_code, resource_code, name, description, "
                " endpoint_url, http_method, auth_method, auth_param_name, "
                " secret_ref, request_headers, query_template, "
                " pagination_kind, pagination_config, response_format, "
                " response_path, timeout_sec, retry_max, rate_limit_per_min, "
                " schedule_cron, schedule_enabled, status, is_active) "
                "VALUES (:d, :r, :n, :desc, :url, 'GET', 'header', "
                "        'X-Api-Key', :sr, '{}'::jsonb, "
                "        CAST(:qt AS JSONB), 'page_number', "
                "        CAST(:pc AS JSONB), 'json', :rp, 30, 3, 60, "
                "        :cron, true, 'PUBLISHED', true) "
                "RETURNING connector_id"
            ),
            {
                "d": r["code"],
                "r": r["resource"],
                "n": f"{r['name']} {r['resource']} API",
                "desc": f"가상 채널 — {r['name']} {r['resource']} 수집 (Phase 8 시드)",
                "url": r["url"],
                "sr": f"{r['code'].upper()}_API_KEY",
                "qt": json.dumps(
                    {"category": "agri", "page": "{page}"}, ensure_ascii=False
                ),
                "pc": json.dumps(
                    {"page_param_name": "page", "page_size": 100}
                ),
                "rp": "$.data.items",
                "cron": "0 9 * * *",
            },
        ).scalar_one()
        out[r["code"]] = int(cid)
    print(f"[connectors] count={len(out)}")
    return out


# ============================================================================
# 2. Inbound Channels (Crawler + OCR + SmbUpload)
# ============================================================================
INBOUND_CHANNELS = [
    {
        "code": "vendor_a_crawler",
        "domain": "emart",
        "kind": "CRAWLER_RESULT",
        "name": "외부 크롤링 업체 A — 온라인 가격 push",
        "secret_ref": "VENDOR_A_HMAC_SECRET",
    },
    {
        "code": "ocr_partner_b",
        "domain": "homeplus",
        "kind": "OCR_RESULT",
        "name": "외부 OCR 업체 B — 전단/영수증 결과 push",
        "secret_ref": "OCR_PARTNER_B_HMAC",
    },
    {
        "code": "smb_uploads",
        "domain": "lottemart",
        "kind": "FILE_UPLOAD",
        "name": "소상공인 가격 업로드 (CSV/Excel)",
        "secret_ref": "SMB_UPLOAD_HMAC",
    },
]


def seed_inbound_channels(session: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for ch in INBOUND_CHANNELS:
        existing = session.execute(
            text(
                "SELECT channel_id FROM domain.inbound_channel "
                "WHERE channel_code = :c"
            ),
            {"c": ch["code"]},
        ).scalar_one_or_none()
        if existing:
            out[ch["code"]] = int(existing)
            continue
        cid = session.execute(
            text(
                "INSERT INTO domain.inbound_channel "
                "(channel_code, domain_code, name, description, channel_kind, "
                " secret_ref, auth_method, expected_content_type, "
                " status, is_active) "
                "VALUES (:c, :d, :n, :desc, :k, :sr, 'hmac_sha256', "
                "        'application/json', 'PUBLISHED', true) "
                "RETURNING channel_id"
            ),
            {
                "c": ch["code"],
                "d": ch["domain"],
                "n": ch["name"],
                "desc": "Phase 8 시드 — 외부 push 채널",
                "k": ch["kind"],
                "sr": ch["secret_ref"],
            },
        ).scalar_one()
        out[ch["code"]] = int(cid)
    print(f"[inbound_channels] count={len(out)}")
    return out


# ============================================================================
# 3. Source Contracts + Field Mappings (4 retailers)
# ============================================================================
RETAILER_MAPPINGS = {
    "emart": [
        ("$.retailer_product_code", "retailer_product_code", "TEXT", True),
        ("$.product_name", "product_name", "TEXT", True),
        ("$.price", "price", "NUMERIC", True),
        ("$.discount_price", "discount_price", "NUMERIC", False),
        ("$.stock_qty", "stock_qty", "INTEGER", True),
    ],
    "homeplus": [
        ("$.item_id", "item_id", "TEXT", True),
        ("$.item_title", "item_title", "TEXT", True),
        ("$.sale_price", "sale_price", "NUMERIC", True),
        ("$.promo_type", "promo_type", "TEXT", False),
        ("$.promo_start", "promo_start", "DATE", False),
        ("$.promo_end", "promo_end", "DATE", False),
    ],
    "lottemart": [
        ("$.goods_no", "goods_no", "TEXT", True),
        ("$.display_name", "display_name", "TEXT", True),
        ("$.current_amt", "current_amt", "NUMERIC", True),
        ("$.unit_text", "unit_text", "TEXT", False),
    ],
    "hanaro": [
        ("$.product_cd", "product_cd", "TEXT", True),
        ("$.name", "name", "TEXT", True),
        ("$.origin", "origin", "TEXT", False),
        ("$.grade", "grade", "TEXT", False),
        ("$.unit", "unit", "TEXT", False),
        ("$.price", "price", "NUMERIC", True),
    ],
}


def seed_contracts_and_mappings(session: Session) -> dict[str, int]:
    """4 source_contract + field_mapping rows."""
    out: dict[str, int] = {}
    for r in RETAILERS:
        # source_id 가 NOT NULL FK — ctl.data_source upsert
        sid = session.execute(
            text(
                "INSERT INTO ctl.data_source "
                "(source_code, source_name, source_type, is_active) "
                "VALUES (:c, :n, 'API', true) "
                "ON CONFLICT (source_code) DO UPDATE SET source_name = EXCLUDED.source_name "
                "RETURNING source_id"
            ),
            {"c": f"{r['code']}_src", "n": f"{r['name']} 가상 source"},
        ).scalar_one()

        contract_id = session.execute(
            text(
                "SELECT contract_id FROM domain.source_contract "
                "WHERE domain_code = :d AND resource_code = :r"
            ),
            {"d": r["code"], "r": r["resource"]},
        ).scalar_one_or_none()
        if not contract_id:
            contract_id = session.execute(
                text(
                    "INSERT INTO domain.source_contract "
                    "(source_id, domain_code, resource_code, schema_version, "
                    " schema_json, description, status) "
                    "VALUES (:sid, :d, :r, 1, '{}'::jsonb, :desc, 'PUBLISHED') "
                    "RETURNING contract_id"
                ),
                {
                    "sid": int(sid),
                    "d": r["code"],
                    "r": r["resource"],
                    "desc": f"{r['name']} {r['resource']} contract v1",
                },
            ).scalar_one()
        contract_id = int(contract_id)
        out[r["code"]] = contract_id

        # field_mapping rows — 멱등 (이미 있으면 skip)
        existing = session.execute(
            text(
                "SELECT COUNT(*) FROM domain.field_mapping "
                "WHERE contract_id = :cid"
            ),
            {"cid": contract_id},
        ).scalar_one()
        if existing and int(existing) > 0:
            continue
        mappings = RETAILER_MAPPINGS.get(r["code"], [])
        for ord_no, (sp, tc, dt, req) in enumerate(mappings, start=1):
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
                    "tt": r["target"],
                    "tc": tc,
                    "dt": dt,
                    "req": req,
                    "o": ord_no,
                },
            )
    print(f"[contracts] count={len(out)} + mappings")
    return out


# ============================================================================
# 4. SQL Assets (3건 — 데이터 품질 / 통합 / 리포트)
# ============================================================================
def seed_sql_assets(session: Session) -> int:
    assets = [
        (
            "service_mart_unified_query",
            "service",  # domain_code = 'service' 가 없으니 'agri' 또는 'emart' 로 대체
            "agri",
            "SELECT std_product_code, retailer_code, AVG(price_normal) AS avg_price\n"
            "FROM service_mart.product_price\n"
            "WHERE collected_at >= NOW() - INTERVAL '7 days'\n"
            "GROUP BY std_product_code, retailer_code",
            "PUBLISHED",
            "service_mart 7일 평균 가격 조회",
        ),
        (
            "low_confidence_review_queue",
            "agri",
            "agri",
            "SELECT * FROM lottemart_mart.product_canon\n"
            "WHERE standardize_confidence < 0.75",
            "PUBLISHED",
            "롯데마트 낮은 confidence 검수 큐",
        ),
        (
            "promo_period_validator",
            "agri",
            "agri",
            "SELECT item_id, promo_start, promo_end FROM homeplus_mart.product_promo\n"
            "WHERE promo_end < promo_start",
            "DRAFT",
            "홈플러스 행사 기간 역순 감지 (DRAFT)",
        ),
    ]
    inserted = 0
    for code, _domain_unused, real_domain, sql, status, desc in assets:
        existing = session.execute(
            text(
                "SELECT asset_id FROM domain.sql_asset "
                "WHERE asset_code = :c AND version = 1"
            ),
            {"c": code},
        ).scalar_one_or_none()
        if existing:
            continue
        try:
            session.execute(
                text(
                    "INSERT INTO domain.sql_asset "
                    "(asset_code, domain_code, version, sql_text, checksum, "
                    " status, description) "
                    "VALUES (:c, :d, 1, :s, :ck, :st, :desc)"
                ),
                {
                    "c": code,
                    "d": real_domain,
                    "s": sql,
                    "ck": f"sha256:{abs(hash(sql))}",
                    "st": status,
                    "desc": desc,
                },
            )
            inserted += 1
        except Exception as e:
            print(f"[sql_asset] skip {code}: {e!r}")
    print(f"[sql_assets] inserted={inserted}")
    return inserted


# ============================================================================
# 5. DQ Rules (12건)
# ============================================================================
DQ_RULES = [
    # (domain, target_table, rule_kind, rule_json, severity, desc)
    ("emart", "emart_mart.product_price", "row_count_min", {"min": 1}, "ERROR", "최소 1행"),
    ("emart", "emart_mart.product_price", "null_pct_max", {"column": "price", "max_pct": 5.0}, "ERROR", "price NULL ≤ 5%"),
    ("emart", "emart_mart.product_price", "range", {"column": "price", "min": 0, "max": 1000000}, "WARN", "price 정상 범위"),
    ("emart", "emart_mart.product_price", "range", {"column": "stock_qty", "min": 0, "max": 100000}, "ERROR", "재고 음수 차단"),
    ("homeplus", "homeplus_mart.product_promo", "row_count_min", {"min": 1}, "ERROR", "최소 1행"),
    ("homeplus", "homeplus_mart.product_promo", "custom_sql", {"sql": "SELECT COUNT(*) FROM homeplus_mart.product_promo WHERE promo_end < promo_start"}, "BLOCK", "행사 기간 역순"),
    ("lottemart", "lottemart_mart.product_canon", "range", {"column": "standardize_confidence", "min": 0.5, "max": 1.0}, "WARN", "confidence 0.5 미만 차단"),
    ("lottemart", "lottemart_mart.product_canon", "row_count_min", {"min": 1}, "ERROR", "최소 1행"),
    ("hanaro", "hanaro_mart.agri_product", "row_count_min", {"min": 1}, "ERROR", "최소 1행"),
    ("hanaro", "hanaro_mart.agri_product", "null_pct_max", {"column": "origin", "max_pct": 10.0}, "WARN", "산지 NULL ≤ 10%"),
    ("agri", "service_mart.product_price", "row_count_min", {"min": 1}, "ERROR", "통합 마트 최소 1행"),
    ("agri", "service_mart.product_price", "freshness", {"max_age_minutes": 1440}, "WARN", "24h 내 데이터 도착"),
]


def seed_dq_rules(session: Session) -> int:
    inserted = 0
    for d, t, kind, rj, sev, desc in DQ_RULES:
        existing = session.execute(
            text(
                "SELECT COUNT(*) FROM domain.dq_rule "
                "WHERE domain_code = :d AND target_table = :t AND rule_kind = :k "
                "  AND description = :desc"
            ),
            {"d": d, "t": t, "k": kind, "desc": desc},
        ).scalar_one()
        if existing and int(existing) > 0:
            continue
        try:
            session.execute(
                text(
                    "INSERT INTO domain.dq_rule "
                    "(domain_code, target_table, rule_kind, rule_json, severity, "
                    " timeout_ms, sample_limit, status, version, description) "
                    "VALUES (:d, :t, :k, CAST(:rj AS JSONB), :sev, "
                    "        30000, 10, 'PUBLISHED', 1, :desc)"
                ),
                {
                    "d": d,
                    "t": t,
                    "k": kind,
                    "rj": json.dumps(rj),
                    "sev": sev,
                    "desc": desc,
                },
            )
            inserted += 1
        except Exception as e:
            print(f"[dq_rule] skip {kind}@{t}: {e!r}")
    print(f"[dq_rules] inserted={inserted}")
    return inserted


# ============================================================================
# 6. Standard Code Namespace (1건)
# ============================================================================
def seed_namespaces(session: Session) -> int:
    existing = session.execute(
        text(
            "SELECT namespace_id FROM domain.standard_code_namespace "
            "WHERE domain_code = 'agri' AND name = 'STANDARD_PRODUCT'"
        )
    ).scalar_one_or_none()
    if existing:
        return 0
    session.execute(
        text(
            "INSERT INTO domain.standard_code_namespace "
            "(domain_code, name, description, std_code_table) "
            "VALUES ('agri', 'STANDARD_PRODUCT', "
            "        '농축수산물 표준 품목코드 (사과/양파/한우 등 10종)', "
            "        'service_mart.std_product')"
        )
    )
    print("[namespace] inserted=1 (STANDARD_PRODUCT)")
    return 1


# ============================================================================
# 7. Mart Drafts + Load Policies (5건씩)
# ============================================================================
def seed_mart_drafts_and_policies(session: Session) -> dict[str, int]:
    drafts: dict[str, int] = {}
    policies: dict[str, int] = {}

    targets = [
        ("emart", "PRICE", "emart_mart.product_price"),
        ("homeplus", "PROMO", "homeplus_mart.product_promo"),
        ("lottemart", "CANON", "lottemart_mart.product_canon"),
        ("hanaro", "AGRI", "hanaro_mart.agri_product"),
        # service_mart 통합 mart 는 'agri' 도메인 산하로 등록
        ("agri", "SERVICE_PRICE", "service_mart.product_price"),
    ]

    for domain, resource, target in targets:
        # mart_design_draft 1건씩
        existing = session.execute(
            text(
                "SELECT draft_id FROM domain.mart_design_draft "
                "WHERE domain_code = :d AND target_table = :t"
            ),
            {"d": domain, "t": target},
        ).scalar_one_or_none()
        if not existing:
            ddl = (
                f"-- {target}\n"
                f"-- Phase 8 가상 시드 — 마이그레이션 0051 으로 이미 적용됨"
            )
            existing = session.execute(
                text(
                    "INSERT INTO domain.mart_design_draft "
                    "(domain_code, target_table, ddl_text, diff_summary, "
                    " status) "
                    "VALUES (:d, :t, :ddl, "
                    "        CAST(:diff AS JSONB), 'PUBLISHED') "
                    "RETURNING draft_id"
                ),
                {
                    "d": domain,
                    "t": target,
                    "ddl": ddl,
                    "diff": json.dumps({"kind": "create_idempotent", "table": target}),
                },
            ).scalar_one()
        drafts[target] = int(existing)

        # resource 보장 — domain 'agri' 의 SERVICE_PRICE 는 별도 등록 필요
        if domain == "agri" and resource == "SERVICE_PRICE":
            session.execute(
                text(
                    "INSERT INTO domain.resource_definition "
                    "(domain_code, resource_code, fact_table, status, version) "
                    "VALUES (:d, :r, :t, 'PUBLISHED', 1) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"d": domain, "r": resource, "t": target},
            )

        rid = session.execute(
            text(
                "SELECT resource_id FROM domain.resource_definition "
                "WHERE domain_code = :d AND resource_code = :r"
            ),
            {"d": domain, "r": resource},
        ).scalar_one_or_none()
        if not rid:
            continue

        # load_policy 1건씩
        pid = session.execute(
            text(
                "SELECT policy_id FROM domain.load_policy "
                "WHERE resource_id = :rid"
            ),
            {"rid": int(rid)},
        ).scalar_one_or_none()
        if not pid:
            mode = "upsert" if domain != "agri" else "upsert"
            keys = (
                "['retailer_product_code']" if domain != "agri"
                else "['retailer_code', 'retailer_product_code']"
            )
            pid = session.execute(
                text(
                    f"INSERT INTO domain.load_policy "
                    f"(resource_id, mode, key_columns, partition_expr, "
                    f" scd_options_json, chunk_size, statement_timeout_ms, "
                    f" status, version) "
                    f"VALUES (:rid, :m, ARRAY{keys}::TEXT[], "
                    f"        'collected_at', '{{}}'::jsonb, 1000, 60000, "
                    f"        'PUBLISHED', 1) "
                    f"RETURNING policy_id"
                ),
                {"rid": int(rid), "m": mode},
            ).scalar_one()
        policies[target] = int(pid)

    print(f"[mart_drafts] count={len(drafts)} / [load_policies] count={len(policies)}")
    return policies


# ============================================================================
# 8. Workflows + Nodes + Edges (5 workflow)
# ============================================================================
def seed_workflows(
    session: Session,
    *,
    connector_ids: dict[str, int],
    contract_ids: dict[str, int],
    policy_ids: dict[str, int],
) -> dict[str, int]:
    """4 retailer workflow + 1 service unification workflow."""
    workflows: dict[str, int] = {}

    for r in RETAILERS:
        wf_name = f"{r['code']}_{r['resource'].lower()}_daily"
        existing = session.execute(
            text(
                "SELECT workflow_id FROM wf.workflow_definition "
                "WHERE name = :n AND status IN ('PUBLISHED','DRAFT')"
            ),
            {"n": wf_name},
        ).scalar_one_or_none()
        if existing:
            workflows[r["code"]] = int(existing)
            continue
        wid = session.execute(
            text(
                "INSERT INTO wf.workflow_definition "
                "(name, version, description, status, schedule_cron, "
                " schedule_enabled, published_at) "
                "VALUES (:n, 1, :d, 'PUBLISHED', '0 9 * * *', true, NOW()) "
                "RETURNING workflow_id"
            ),
            {
                "n": wf_name,
                "d": (
                    f"Phase 8 가상 시드 — {r['name']} {r['resource']} 일별 "
                    "수집 파이프라인"
                ),
            },
        ).scalar_one()
        wid = int(wid)
        workflows[r["code"]] = wid

        # 4 박스 DAG: PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK → LOAD_TARGET
        connector_id = connector_ids[r["code"]]
        contract_id = contract_ids[r["code"]]
        policy_id = policy_ids.get(r["target"], 1)

        node_ids: dict[str, int] = {}

        def _add_node(key: str, ntype: str, cfg: dict[str, Any], x: int) -> int:
            nid = session.execute(
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
                    "c": json.dumps(cfg, ensure_ascii=False),
                    "x": x,
                },
            ).scalar_one()
            return int(nid)

        node_ids["fetch"] = _add_node(
            "fetch_api", "PUBLIC_API_FETCH",
            {"connector_id": connector_id, "max_pages": 10}, 100,
        )
        node_ids["map"] = _add_node(
            "map_fields", "MAP_FIELDS",
            {"contract_id": contract_id, "source_table": f"{r['code']}_stg.raw"}, 300,
        )
        node_ids["dq"] = _add_node(
            "dq_check", "DQ_CHECK",
            {"rules": [{"type": "row_count_min", "value": 1}]}, 500,
        )
        node_ids["load"] = _add_node(
            "load_target", "LOAD_TARGET",
            {"policy_id": policy_id, "source_table": f"{r['code']}_stg.cleaned"}, 700,
        )

        for src, dst in (("fetch", "map"), ("map", "dq"), ("dq", "load")):
            session.execute(
                text(
                    "INSERT INTO wf.edge_definition "
                    "(workflow_id, from_node_id, to_node_id) "
                    "VALUES (:w, :f, :t)"
                ),
                {"w": wid, "f": node_ids[src], "t": node_ids[dst]},
            )

    # service_mart 통합 workflow (다른 4 workflow 결과를 합산)
    service_wf_name = "service_mart_unification_daily"
    existing = session.execute(
        text(
            "SELECT workflow_id FROM wf.workflow_definition "
            "WHERE name = :n"
        ),
        {"n": service_wf_name},
    ).scalar_one_or_none()
    if not existing:
        wid = session.execute(
            text(
                "INSERT INTO wf.workflow_definition "
                "(name, version, description, status, schedule_cron, "
                " schedule_enabled, published_at) "
                "VALUES (:n, 1, :d, 'PUBLISHED', '0 10 * * *', true, NOW()) "
                "RETURNING workflow_id"
            ),
            {
                "n": service_wf_name,
                "d": "4 유통사 데이터를 service_mart 로 통합 (Phase 8 시드)",
            },
        ).scalar_one()
        wid = int(wid)
        workflows["service"] = wid
        # 단순 1 박스: SQL_ASSET_TRANSFORM
        session.execute(
            text(
                "INSERT INTO wf.node_definition "
                "(workflow_id, node_key, node_type, config_json, "
                " position_x, position_y) "
                "VALUES (:w, 'unify_sql', 'SQL_ASSET_TRANSFORM', "
                "        CAST(:c AS JSONB), 100, 100)"
            ),
            {
                "w": wid,
                "c": json.dumps({"asset_code": "service_mart_unified_query"}),
            },
        )
    else:
        workflows["service"] = int(existing)

    print(f"[workflows] count={len(workflows)} (4 retailer + 1 service)")
    return workflows


# ============================================================================
# 9. Pipeline Releases (4 retailer)
# ============================================================================
def seed_releases(session: Session, workflows: dict[str, int]) -> int:
    inserted = 0
    for r in RETAILERS:
        wid = workflows.get(r["code"])
        if not wid:
            continue
        existing = session.execute(
            text(
                "SELECT release_id FROM wf.pipeline_release "
                "WHERE workflow_name = :n AND version_no = 1"
            ),
            {"n": f"{r['code']}_{r['resource'].lower()}_daily"},
        ).scalar_one_or_none()
        if existing:
            continue
        # nodes_snapshot / edges_snapshot 간단하게
        nodes = session.execute(
            text(
                "SELECT node_key, node_type, config_json "
                "FROM wf.node_definition WHERE workflow_id = :w"
            ),
            {"w": wid},
        ).all()
        nodes_snap = [
            {"node_key": str(n.node_key), "node_type": str(n.node_type), "config_json": n.config_json}
            for n in nodes
        ]
        session.execute(
            text(
                "INSERT INTO wf.pipeline_release "
                "(workflow_name, version_no, source_workflow_id, "
                " released_workflow_id, change_summary, nodes_snapshot, "
                " edges_snapshot) "
                "VALUES (:n, 1, :swf, :rwf, "
                "        CAST(:cs AS JSONB), "
                "        CAST(:ns AS JSONB), '[]'::jsonb)"
            ),
            {
                "n": f"{r['code']}_{r['resource'].lower()}_daily",
                "swf": wid,
                "rwf": wid,
                "cs": json.dumps(
                    {"reason": "Phase 8 시드 release", "wave": "phase8"}
                ),
                "ns": json.dumps(nodes_snap),
            },
        )
        inserted += 1
    print(f"[releases] inserted={inserted}")
    return inserted


# ============================================================================
# 10. Pipeline Runs + Node Runs (24 runs over last 7 days)
# ============================================================================
def seed_runs(session: Session, workflows: dict[str, int]) -> int:
    """각 retailer workflow 별로 7일치 일별 run 생성. 일부 fail / skip 섞기."""
    total_runs = 0
    for r in RETAILERS:
        wid = workflows.get(r["code"])
        if not wid:
            continue
        node_defs = session.execute(
            text(
                "SELECT node_id, node_key, node_type FROM wf.node_definition "
                "WHERE workflow_id = :w ORDER BY position_x"
            ),
            {"w": wid},
        ).all()
        if not node_defs:
            continue

        for day_offset in range(7, 0, -1):
            run_date = TODAY - timedelta(days=day_offset - 1)
            started = NOW - timedelta(days=day_offset - 1, hours=random.randint(0, 5))
            duration_sec = random.randint(30, 180)
            finished = started + timedelta(seconds=duration_sec)

            # 의도적 일부 실패 — 약 15% 확률
            run_status = "SUCCESS"
            if r["code"] == "lottemart" and day_offset == 3:
                run_status = "FAILED"
            elif r["code"] == "homeplus" and day_offset == 5:
                run_status = "FAILED"
            elif day_offset == 7 and r["code"] == "emart":
                run_status = "FAILED"

            run_id = session.execute(
                text(
                    "INSERT INTO run.pipeline_run "
                    "(workflow_id, run_date, status, started_at, finished_at, "
                    " error_message) "
                    "VALUES (:w, :d, :s, :st, :ft, :err) "
                    "RETURNING pipeline_run_id"
                ),
                {
                    "w": wid,
                    "d": run_date,
                    "s": run_status,
                    "st": started,
                    "ft": finished,
                    "err": (
                        "DQ_CHECK 실패: row_count_min < 1"
                        if run_status == "FAILED" else None
                    ),
                },
            ).scalar_one()
            run_id = int(run_id)

            # node_run 4 rows
            current = started
            failed_at_box: int | None = None
            for idx, nd in enumerate(node_defs):
                box_started = current
                box_dur = random.randint(2, 30)
                box_finished = box_started + timedelta(seconds=box_dur)
                if run_status == "FAILED":
                    if failed_at_box is None and idx == random.randint(1, len(node_defs) - 1):
                        node_status = "FAILED"
                        failed_at_box = idx
                    elif failed_at_box is not None and idx > failed_at_box:
                        node_status = "SKIPPED"
                    else:
                        node_status = "SUCCESS"
                else:
                    node_status = "SUCCESS"

                row_count = (
                    random.randint(80, 500)
                    if node_status == "SUCCESS" else 0
                )

                session.execute(
                    text(
                        "INSERT INTO run.node_run "
                        "(pipeline_run_id, run_date, node_definition_id, "
                        " node_key, node_type, status, attempt_no, "
                        " started_at, finished_at, error_message, output_json) "
                        "VALUES (:rid, :d, :nid, :k, :t, :s, 1, "
                        "        :st, :ft, :err, CAST(:o AS JSONB))"
                    ),
                    {
                        "rid": run_id,
                        "d": run_date,
                        "nid": int(nd.node_id),
                        "k": str(nd.node_key),
                        "t": str(nd.node_type),
                        "s": node_status,
                        "st": box_started,
                        "ft": box_finished if node_status != "SKIPPED" else None,
                        "err": (
                            "DQ rule failed (row_count_min)"
                            if node_status == "FAILED" else None
                        ),
                        "o": json.dumps({"row_count": row_count}),
                    },
                )
                current = box_finished
            total_runs += 1
    print(f"[runs] inserted={total_runs} (4 retailer × 7 days)")
    return total_runs


# ============================================================================
# 11. Ingest Jobs (24 jobs)
# ============================================================================
def seed_ingest_jobs(session: Session) -> int:
    inserted = 0
    for r in RETAILERS:
        sid = session.execute(
            text(
                "SELECT source_id FROM ctl.data_source WHERE source_code = :c"
            ),
            {"c": f"{r['code']}_src"},
        ).scalar_one()
        for day_offset in range(7, 0, -1):
            started = NOW - timedelta(days=day_offset - 1, hours=random.randint(1, 6))
            duration = random.randint(20, 60)
            finished = started + timedelta(seconds=duration)
            session.execute(
                text(
                    "INSERT INTO run.ingest_job "
                    "(source_id, job_type, status, started_at, finished_at, "
                    " input_count, output_count, error_count) "
                    "VALUES (:sid, 'SCHEDULED', 'SUCCESS', :st, :ft, "
                    "        :ic, :oc, 0)"
                ),
                {
                    "sid": int(sid),
                    "st": started,
                    "ft": finished,
                    "ic": random.randint(80, 500),
                    "oc": random.randint(80, 500),
                },
            )
            inserted += 1
    print(f"[ingest_jobs] inserted={inserted}")
    return inserted


# ============================================================================
# 12. Raw Objects (~40 rows)
# ============================================================================
def seed_raw_objects(session: Session) -> int:
    """raw.raw_object — partition by partition_date. 컬럼: content_hash, received_at."""
    # raw partition 보장
    for delta_days in (-30, 0, 30):
        d = TODAY + timedelta(days=delta_days)
        ym = d.strftime("%Y_%m")
        first = d.replace(day=1)
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1)
        else:
            next_first = first.replace(month=first.month + 1)
        try:
            session.execute(
                text(
                    f'CREATE TABLE IF NOT EXISTS raw."raw_object_{ym}" '
                    f"PARTITION OF raw.raw_object "
                    f"FOR VALUES FROM (:f) TO (:t)"
                ),
                {"f": first, "t": next_first},
            )
        except Exception:
            pass
    session.commit()

    inserted = 0
    for r in RETAILERS:
        sid = session.execute(
            text(
                "SELECT source_id FROM ctl.data_source WHERE source_code = :c"
            ),
            {"c": f"{r['code']}_src"},
        ).scalar_one()
        for i in range(10):
            received = NOW - timedelta(hours=random.randint(0, 168))
            partition_date = received.date()
            sample = {
                "retailer": r["code"],
                "page": i + 1,
                "items_count": random.randint(50, 200),
                "checksum": f"sha256_{i}_{r['code']}",
            }
            content_hash = f"sha256_phase8_{r['code']}_{i}"
            try:
                session.execute(
                    text(
                        "INSERT INTO raw.raw_object "
                        "(source_id, object_type, idempotency_key, "
                        " content_hash, payload_json, received_at, "
                        " partition_date, status) "
                        "VALUES (:sid, 'JSON', :ik, :ch, "
                        "        CAST(:p AS JSONB), :rt, :pd, 'PROCESSED')"
                    ),
                    {
                        "sid": int(sid),
                        "ik": f"phase8_{r['code']}_{i}_{int(received.timestamp())}",
                        "ch": content_hash,
                        "p": json.dumps(sample),
                        "rt": received,
                        "pd": partition_date,
                    },
                )
                inserted += 1
            except Exception:
                # idempotency 또는 content_hash UNIQUE 충돌 — skip
                pass
    print(f"[raw_objects] inserted={inserted}")
    return inserted


# ============================================================================
# 13. Inbound Events (15 events)
# ============================================================================
def seed_inbound_events(session: Session, channels: dict[str, int]) -> int:
    inserted = 0
    samples = [
        # Crawler push
        ("vendor_a_crawler", {
            "crawler_provider_code": "vendor_a",
            "source_site": "coupang.com",
            "crawled_at": NOW.isoformat(),
            "items": [
                {"product_name": "사과 1.5kg", "price": 12900, "url": "https://..."},
                {"product_name": "양파 2kg", "price": 5980, "url": "https://..."},
            ],
        }),
        # OCR push
        ("ocr_partner_b", {
            "ocr_provider_code": "vendor_b",
            "image_object_key": "raw/ocr/2026/04/27/abc123.jpg",
            "items": [
                {"text": "사과 1봉 5,000원", "confidence": 0.92,
                 "candidate_product_name": "사과 1봉", "candidate_price": 5000},
                {"text": "양파 2kg 5,980", "confidence": 0.88,
                 "candidate_product_name": "양파 2kg", "candidate_price": 5980},
                {"text": "사 과 1 봉", "confidence": 0.62,
                 "candidate_product_name": None, "candidate_price": None},
            ],
        }),
        # SMB upload
        ("smb_uploads", {
            "store_name": "행복마트",
            "items": [
                {"product": "사과", "price": 5500, "stock": 20},
                {"product": "양파", "price": 3500, "stock": 50},
            ],
        }),
    ]
    for ch_code, payload in samples:
        ch_id = channels.get(ch_code)
        if not ch_id:
            continue
        # 5 events per channel
        for i in range(5):
            try:
                received = NOW - timedelta(hours=random.randint(0, 48))
                # 마지막 1건은 의도적 FAILED 상태
                status = "FAILED" if i == 4 else random.choice(["DONE", "DONE", "PROCESSING", "RECEIVED"])
                session.execute(
                    text(
                        "INSERT INTO audit.inbound_event "
                        "(channel_code, channel_id, idempotency_key, "
                        " request_id, content_type, payload_size_bytes, "
                        " payload_inline, status, received_at, processed_at, "
                        " error_message) "
                        "VALUES (:cc, :cid, :ik, :rid, 'application/json', "
                        "        :sz, CAST(:p AS JSONB), :s, :rcv, :pa, :err)"
                    ),
                    {
                        "cc": ch_code,
                        "cid": ch_id,
                        "ik": f"phase8_{ch_code}_{i}_{int(received.timestamp())}",
                        "rid": f"req_{ch_code}_{i}",
                        "sz": len(json.dumps(payload)),
                        "p": json.dumps(payload, ensure_ascii=False),
                        "s": status,
                        "rcv": received,
                        "pa": (
                            received + timedelta(seconds=random.randint(1, 60))
                            if status in ("DONE", "FAILED", "PROCESSING") else None
                        ),
                        "err": "schema mismatch" if status == "FAILED" else None,
                    },
                )
                inserted += 1
            except Exception as exc:
                print(f"[inbound_event] skip {ch_code}#{i}: {exc!r}")
    print(f"[inbound_events] inserted={inserted}")
    return inserted


# ============================================================================
# 14. Crowd Tasks (5 review queue items)
# ============================================================================
def seed_crowd_tasks(session: Session) -> int:
    """롯데마트의 low confidence 데이터를 검수 큐로 (run.crowd_task)."""
    low_conf_items = session.execute(
        text(
            "SELECT id, goods_no, display_name, standardize_confidence "
            "FROM lottemart_mart.product_canon "
            "WHERE standardize_confidence < 0.75 "
            "LIMIT 5"
        )
    ).all()
    if not low_conf_items:
        print("[crowd_tasks] no low-confidence items found")
        return 0

    # raw_object_id 가 NOT NULL FK — 임의 raw_object 1건 사용
    raw_id_row = session.execute(
        text(
            "SELECT raw_object_id, partition_date FROM raw.raw_object LIMIT 1"
        )
    ).first()
    if not raw_id_row:
        print("[crowd_tasks] no raw_object — seed raw first")
        return 0
    raw_object_id = int(raw_id_row.raw_object_id)
    partition_date = raw_id_row.partition_date

    inserted = 0
    for item in low_conf_items:
        try:
            session.execute(
                text(
                    "INSERT INTO crowd.task "
                    "(task_kind, priority, raw_object_id, partition_date, "
                    " payload, status, created_at) "
                    "VALUES ('std_low_confidence', 5, :roid, :pd, "
                    "        CAST(:p AS JSONB), 'PENDING', :c)"
                ),
                {
                    "roid": raw_object_id,
                    "pd": partition_date,
                    "p": json.dumps(
                        {
                            "source_table": "lottemart_mart.product_canon",
                            "source_row_id": int(item.id),
                            "display_name": str(item.display_name),
                            "confidence": float(item.standardize_confidence),
                            "candidates": ["사과", "배", "포도"],
                            "reason": (
                                f"롯데마트 표준화 confidence "
                                f"{float(item.standardize_confidence):.2f} 미달"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    "c": NOW - timedelta(hours=random.randint(1, 12)),
                },
            )
            inserted += 1
        except Exception as exc:
            session.rollback()
            print(f"[crowd_task] skip: {str(exc)[:200]}")
    print(f"[crowd_tasks] inserted={inserted}")
    return inserted


def main() -> int:
    sm = get_sync_sessionmaker()
    print("=" * 70)
    print("Phase 8 Full e2e Seed - 모든 화면에 데이터 채우기")
    print("=" * 70)
    try:
        with sm() as session:
            _ensure_partition_for_today(session)

            connectors = seed_connectors(session)
            channels = seed_inbound_channels(session)
            contracts = seed_contracts_and_mappings(session)
            seed_sql_assets(session)
            seed_dq_rules(session)
            seed_namespaces(session)
            policies = seed_mart_drafts_and_policies(session)
            workflows = seed_workflows(
                session,
                connector_ids=connectors,
                contract_ids=contracts,
                policy_ids=policies,
            )
            session.commit()

        # runs/jobs/raw 는 각 함수마다 새 session — rollback 격리
        for fn, args in [
            (seed_releases, (workflows,)),
            (seed_runs, (workflows,)),
            (seed_ingest_jobs, ()),
            (seed_raw_objects, ()),
            (seed_inbound_events, (channels,)),
            (seed_crowd_tasks, ()),
        ]:
            try:
                with sm() as session:
                    fn(session, *args)
                    session.commit()
            except Exception as exc:
                print(f"[{fn.__name__}] outer error: {str(exc)[:200]}")

        print("\n[done] 모든 화면에 시드 데이터 채워짐.")
        print("\n다음 화면에서 데이터 확인:")
        print("  - /v2/connectors/public-api    (4 connectors)")
        print("  - /v2/inbound-channels/designer (3 channels)")
        print("  - /v2/mappings/designer         (4 contracts + 21 mappings)")
        print("  - /v2/transforms/designer       (3 SQL assets)")
        print("  - /v2/quality/designer          (12 DQ rules)")
        print("  - /v2/marts/designer            (5 mart drafts + 5 load policies)")
        print("  - /v2/pipelines/designer        (5 workflows)")
        print("  - /v2/operations/dashboard      (24 runs / 96 node runs)")
        print("  - /v2/service-mart              (40 통합 mart rows)")
        print("  - /pipelines/runs               (24 runs)")
        print("  - /pipelines/releases           (4 releases)")
        print("  - /raw-objects                  (40 raw)")
        print("  - /jobs                         (24 ingest jobs)")
        print("  - /crowd-tasks                  (5 review tasks)")
    finally:
        dispose_sync_engine()
    return 0


if __name__ == "__main__":
    main()
