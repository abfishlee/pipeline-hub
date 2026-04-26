"""Phase 5.2.2 STEP 5 — v2 generic 노드 카탈로그 통합 테스트.

검증:
  1. function registry — 카테고리별 spot check + allowlist 강제 + mini-DSL
  2. dispatcher — get_v2_runner / list_v2_node_types / 미지원 type 거부
  3. MAP_FIELDS — sandbox source → sandbox target, transform_expr (allowlist 적용)
  4. SQL_INLINE_TRANSFORM — happy + guard 거부 (mart 직접 write 차단)
  5. SQL_ASSET_TRANSFORM — DRAFT 거부 / APPROVED 실행
  6. FUNCTION_TRANSFORM — expressions row 단위 적용 + skip_row 모드
  7. LOAD_TARGET — append_only + upsert (sandbox→mart) + DRAFT policy 거부
  8. HTTP_TRANSFORM dry_run — 실 호출 없이 입력 row 수만
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.functions import (
    FUNCTION_REGISTRY,
    FunctionCallError,
    apply_expression,
    call_function,
)
from app.domain.nodes_v2 import (
    NodeV2Context,
    NodeV2Error,
    NodeV2Output,
    get_v2_runner,
    list_v2_node_types,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cleanup_tables() -> Iterator[list[str]]:
    """sandbox/mart/source 보조 테이블 정리."""
    tables: list[str] = []
    yield tables
    if not tables:
        dispose_sync_engine()
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in tables:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        session.commit()
    dispose_sync_engine()


@pytest.fixture
def cleanup_domain_meta() -> Iterator[dict[str, list[Any]]]:
    """domain.* 메타 테이블 정리."""
    state: dict[str, list[Any]] = {
        "domain_codes": [],
        "contract_ids": [],
        "asset_ids": [],
        "policy_ids": [],
        "resource_ids": [],
    }
    yield state
    if not any(state.values()):
        dispose_sync_engine()
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        if state["asset_ids"]:
            session.execute(
                text("DELETE FROM domain.sql_asset WHERE asset_id = ANY(:ids)"),
                {"ids": state["asset_ids"]},
            )
        if state["policy_ids"]:
            session.execute(
                text("DELETE FROM domain.load_policy WHERE policy_id = ANY(:ids)"),
                {"ids": state["policy_ids"]},
            )
        if state["resource_ids"]:
            session.execute(
                text(
                    "DELETE FROM domain.field_mapping "
                    "WHERE contract_id = ANY(:cids)"
                ),
                {"cids": state["contract_ids"]},
            )
            session.execute(
                text("DELETE FROM domain.resource_definition WHERE resource_id = ANY(:ids)"),
                {"ids": state["resource_ids"]},
            )
        if state["contract_ids"]:
            session.execute(
                text("DELETE FROM domain.field_mapping WHERE contract_id = ANY(:ids)"),
                {"ids": state["contract_ids"]},
            )
            session.execute(
                text("DELETE FROM domain.source_contract WHERE contract_id = ANY(:ids)"),
                {"ids": state["contract_ids"]},
            )
        if state["domain_codes"]:
            session.execute(
                text("DELETE FROM domain.domain_definition WHERE domain_code = ANY(:codes)"),
                {"codes": state["domain_codes"]},
            )
        session.commit()
    dispose_sync_engine()


def _ensure_domain(session: Any, code: str) -> None:
    session.execute(
        text(
            "INSERT INTO domain.domain_definition "
            "(domain_code, name, description, schema_yaml, status, version) "
            "VALUES (:c, :n, :d, '{}'::jsonb, 'PUBLISHED', 1) "
            "ON CONFLICT (domain_code) DO NOTHING"
        ),
        {"c": code, "n": f"IT domain {code}", "d": "v2 nodes IT"},
    )


def _ensure_source(session: Any) -> int:
    """테스트 시 contract.source_id FK 충족용 — 1건만 확보."""
    sid = session.execute(
        text("SELECT source_id FROM ctl.data_source ORDER BY source_id LIMIT 1")
    ).scalar_one_or_none()
    if sid is not None:
        return int(sid)
    code = f"IT_NODES_V2_{secrets.token_hex(3).upper()}"
    sid = session.execute(
        text(
            "INSERT INTO ctl.data_source (source_code, source_name, source_type, "
            " is_active, config_json) "
            "VALUES (:c, 'nodes-v2-it', 'API', TRUE, '{}'::jsonb) RETURNING source_id"
        ),
        {"c": code},
    ).scalar_one()
    return int(sid)


def _new_domain_code() -> str:
    return f"itd_{secrets.token_hex(3).lower()}"


def _ctx(
    session: Any,
    *,
    domain_code: str,
    node_key: str = "T",
    pipeline_run_id: int = 9_999_500,
    contract_id: int | None = None,
    source_id: int | None = None,
) -> NodeV2Context:
    return NodeV2Context(
        session=session,
        pipeline_run_id=pipeline_run_id,
        node_run_id=pipeline_run_id,
        node_key=node_key,
        domain_code=domain_code,
        contract_id=contract_id,
        source_id=source_id,
        user_id=None,
    )


# ===========================================================================
# 1. function registry
# ===========================================================================
def test_function_registry_size() -> None:
    """Q4 답변 — 25 ± 일부 함수 (확장 시 변경)."""
    assert len(FUNCTION_REGISTRY) >= 25
    categories = {spec.category for spec in FUNCTION_REGISTRY.values()}
    assert categories == {"text", "number", "date", "phone", "address", "json", "hash", "id"}


def test_text_functions_basic() -> None:
    assert call_function("text.trim", "  hi  ") == "hi"
    assert call_function("text.upper", "abc") == "ABC"
    assert call_function("text.normalize_unicode_nfc", "가") == "가"
    assert call_function("text.replace", "a-b-c", "-", "_") == "a_b_c"
    assert call_function("text.regex_extract", "price=1500won", r"price=(\d+)", 1) == "1500"
    assert call_function("text.starts_with", "hello", "he") is True
    assert call_function("text.length", "한글") == 2


def test_number_functions() -> None:
    from decimal import Decimal

    assert call_function("number.parse_decimal", "1,500.50") == Decimal("1500.50")
    assert call_function("number.parse_decimal", "") is None
    assert call_function("number.round_n", "3.14159", 2) == Decimal("3.14")
    assert call_function("number.abs", "-42.0") == Decimal("42.0")
    assert call_function("number.clamp", 100, 0, 50) == Decimal("50")


def test_date_functions() -> None:
    from datetime import datetime

    parsed = call_function("date.parse", "2026-04-27")
    assert isinstance(parsed, datetime)
    assert parsed.year == 2026
    kst = call_function("date.to_kst", "2026-04-27T00:00:00")
    assert kst.utcoffset().total_seconds() == 9 * 3600
    iso = call_function("date.to_iso", "2026-04-27")
    assert iso.startswith("2026-04-27")
    formatted = call_function("date.format", "2026-04-27", "%Y/%m/%d")
    assert formatted == "2026/04/27"


def test_phone_address_id() -> None:
    assert call_function("phone.normalize_kr", "010-1234-5678") == "010-1234-5678"
    assert call_function("phone.normalize_kr", "+82 10 1234 5678") == "010-1234-5678"
    with pytest.raises(FunctionCallError):
        call_function("phone.normalize_kr", "123")
    assert call_function("address.extract_sido", "서울특별시 강남구 테헤란로 1") == "서울특별시"
    assert call_function("address.extract_sigungu", "경기도 수원시 영통구 광교로 100") == "수원시"
    assert call_function("hash.sha256", "abc").startswith("ba7816")
    h = call_function("id.make_content_hash", "src", 42, "2026-04-27")
    assert len(h) == 64
    assert call_function("id.slugify", "한글 ABC 123").startswith("abc-123") or \
           call_function("id.slugify", "한글 ABC 123") == "abc-123"


def test_function_allowlist_enforcement() -> None:
    with pytest.raises(FunctionCallError):
        call_function("eval", "1+1")
    with pytest.raises(FunctionCallError):
        call_function("os.system", "echo")


def test_apply_expression_mini_dsl() -> None:
    row = {"price": "1,500", "name": "  Apple  "}
    assert apply_expression("number.parse_decimal($price)", row=row) == 1500
    assert apply_expression("text.trim($name)", row=row) == "Apple"
    # 중첩 호출 미지원 — 평탄 호출만 (Phase 5 MVP).
    with pytest.raises(FunctionCallError):
        apply_expression("text.upper(text.trim($name))", row=row)
    # bare $col → 그대로 반환.
    assert apply_expression("$price", row=row) == "1,500"
    # literal 만 — None row 도 OK.
    assert apply_expression("'hello'") == "hello"
    assert apply_expression("42") == 42
    # 미등록 함수 거부.
    with pytest.raises(FunctionCallError):
        apply_expression("os.system('rm -rf /')")


# ===========================================================================
# 2. dispatcher
# ===========================================================================
def test_dispatcher_lists_six_generic_types() -> None:
    types = list_v2_node_types()
    assert set(types) == {
        "MAP_FIELDS",
        "SQL_INLINE_TRANSFORM",
        "SQL_ASSET_TRANSFORM",
        "HTTP_TRANSFORM",
        "FUNCTION_TRANSFORM",
        "LOAD_TARGET",
    }
    for t in types:
        runner = get_v2_runner(t)
        assert runner.node_type == t


def test_dispatcher_rejects_unknown_type() -> None:
    with pytest.raises(NodeV2Error):
        get_v2_runner("DOES_NOT_EXIST")


# ===========================================================================
# 3. MAP_FIELDS
# ===========================================================================
def test_map_fields_happy_path(
    cleanup_tables: list[str],
    cleanup_domain_meta: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    domain_code = _new_domain_code()
    src = "wf.tmp_it_map_src"
    tgt = "wf.tmp_it_map_tgt"
    cleanup_tables.extend([src, tgt])

    with sm() as session:
        _ensure_domain(session, domain_code)
        cleanup_domain_meta["domain_codes"].append(domain_code)

        # source sandbox 준비.
        session.execute(text(f"DROP TABLE IF EXISTS {src} CASCADE"))
        session.execute(text(f"CREATE TABLE {src} (raw_price TEXT, raw_name TEXT)"))
        session.execute(
            text(f"INSERT INTO {src} (raw_price, raw_name) VALUES "
                 "('1,500', '  Apple  '), ('2,300', 'Banana')")
        )

        sid = _ensure_source(session)
        contract_id = session.execute(
            text(
                "INSERT INTO domain.source_contract "
                "(source_id, domain_code, resource_code, schema_version, schema_json, "
                " compatibility_mode, resource_selector_json, status) "
                "VALUES (:sid, :dom, 'item', 1, '{}'::jsonb, 'backward', '{}'::jsonb, "
                "        'PUBLISHED') "
                "RETURNING contract_id"
            ),
            {"sid": sid, "dom": domain_code},
        ).scalar_one()
        cleanup_domain_meta["contract_ids"].append(int(contract_id))

        # field_mapping 2종 — APPROVED.
        for src_col, tgt_col, expr in (
            ("raw_price", "price", "number.parse_decimal($raw_price)"),
            ("raw_name", "name", "text.trim($raw_name)"),
        ):
            session.execute(
                text(
                    "INSERT INTO domain.field_mapping "
                    "(contract_id, source_path, target_table, target_column, "
                    " transform_expr, status) "
                    "VALUES (:cid, :sp, :tt, :tc, :ex, 'APPROVED')"
                ),
                {"cid": contract_id, "sp": src_col, "tt": tgt, "tc": tgt_col, "ex": expr},
            )
        session.commit()

    # 실행.
    with sm() as session:
        ctx = _ctx(session, domain_code=domain_code, contract_id=int(contract_id), node_key="map")
        runner = get_v2_runner("MAP_FIELDS")
        out: NodeV2Output = runner.run(
            ctx,
            {
                "contract_id": int(contract_id),
                "source_table": src,
                "target_table": tgt,
            },
        )
        session.commit()

    assert out.status == "success", out.error_message
    assert out.row_count == 2

    with sm() as session:
        rows = session.execute(text(f"SELECT price, name FROM {tgt} ORDER BY name")).all()
    assert [(r.price, r.name) for r in rows] == [("1500", "Apple"), ("2300", "Banana")]


def test_map_fields_no_mapping_returns_failed(
    cleanup_tables: list[str],
    cleanup_domain_meta: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    domain_code = _new_domain_code()
    src = "wf.tmp_it_map_empty_src"
    cleanup_tables.append(src)
    with sm() as session:
        _ensure_domain(session, domain_code)
        cleanup_domain_meta["domain_codes"].append(domain_code)
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (a TEXT)"))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code=domain_code, contract_id=99_999_999)
        runner = get_v2_runner("MAP_FIELDS")
        out = runner.run(ctx, {"contract_id": 99_999_999, "source_table": src})
    assert out.status == "failed"
    assert out.payload["reason"] == "empty_mapping"


# ===========================================================================
# 4. SQL_INLINE_TRANSFORM
# ===========================================================================
def test_sql_inline_transform_sandbox_only(cleanup_tables: list[str]) -> None:
    sm = get_sync_sessionmaker()
    src = "wf.tmp_it_inline_src"
    tgt = "wf.tmp_it_inline_tgt"
    cleanup_tables.extend([src, tgt])

    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (val INTEGER)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1),(2),(3)"))
        session.commit()

    with sm() as session:
        ctx = _ctx(session, domain_code="agri", node_key="inline")
        runner = get_v2_runner("SQL_INLINE_TRANSFORM")
        out = runner.run(
            ctx,
            {"sql": f"SELECT val * 10 AS v FROM {src}", "output_table": tgt},
        )
        session.commit()
    assert out.status == "success", out.error_message
    assert out.row_count == 3


def test_sql_inline_transform_blocks_mart_write() -> None:
    """INLINE 의 output_table 이 mart.* 면 거부 (Q2)."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri")
        runner = get_v2_runner("SQL_INLINE_TRANSFORM")
        with pytest.raises(NodeV2Error):
            runner.run(
                ctx,
                {
                    "sql": "SELECT 1 AS v",
                    "output_table": "mart.price_fact",  # 금지.
                },
            )


def test_sql_inline_transform_blocks_dangerous_keyword() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri")
        runner = get_v2_runner("SQL_INLINE_TRANSFORM")
        out = runner.run(ctx, {"sql": "DROP TABLE mart.price_fact", "materialize": False})
    assert out.status == "failed"
    assert out.payload["reason"] == "sql_guard"


# ===========================================================================
# 5. SQL_ASSET_TRANSFORM
# ===========================================================================
def test_sql_asset_transform_draft_rejected(
    cleanup_tables: list[str],
    cleanup_domain_meta: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    domain_code = _new_domain_code()
    code = f"it_asset_{secrets.token_hex(3).lower()}"
    with sm() as session:
        _ensure_domain(session, domain_code)
        cleanup_domain_meta["domain_codes"].append(domain_code)
        asset_id = session.execute(
            text(
                "INSERT INTO domain.sql_asset "
                "(asset_code, domain_code, version, sql_text, checksum, status) "
                "VALUES (:c, :d, 1, 'SELECT 1', 'cs', 'DRAFT') "
                "RETURNING asset_id"
            ),
            {"c": code, "d": domain_code},
        ).scalar_one()
        cleanup_domain_meta["asset_ids"].append(int(asset_id))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code=domain_code)
        runner = get_v2_runner("SQL_ASSET_TRANSFORM")
        out = runner.run(ctx, {"asset_code": code})
    assert out.status == "failed"
    assert out.payload["reason"] == "asset_not_found"  # APPROVED/PUBLISHED 만 검색됨.


def test_sql_asset_transform_approved_runs(
    cleanup_tables: list[str],
    cleanup_domain_meta: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    domain_code = _new_domain_code()
    code = f"it_asset_{secrets.token_hex(3).lower()}"
    src = "wf.tmp_it_asset_src"
    tgt = "wf.tmp_it_asset_tgt"
    cleanup_tables.extend([src, tgt])
    with sm() as session:
        _ensure_domain(session, domain_code)
        cleanup_domain_meta["domain_codes"].append(domain_code)
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (n INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (10),(20)"))
        asset_id = session.execute(
            text(
                "INSERT INTO domain.sql_asset "
                "(asset_code, domain_code, version, sql_text, checksum, output_table, status) "
                f"VALUES (:c, :d, 1, 'SELECT n FROM {src}', 'cs', :ot, 'APPROVED') "
                "RETURNING asset_id"
            ),
            {"c": code, "d": domain_code, "ot": tgt},
        ).scalar_one()
        cleanup_domain_meta["asset_ids"].append(int(asset_id))
        session.commit()

    with sm() as session:
        ctx = _ctx(session, domain_code=domain_code, node_key="asset")
        runner = get_v2_runner("SQL_ASSET_TRANSFORM")
        out = runner.run(ctx, {"asset_code": code})
        session.commit()
    assert out.status == "success", out.error_message
    assert out.payload["asset_status"] == "APPROVED"
    assert out.row_count == 2


# ===========================================================================
# 6. FUNCTION_TRANSFORM
# ===========================================================================
def test_function_transform_basic(cleanup_tables: list[str]) -> None:
    sm = get_sync_sessionmaker()
    src = "wf.tmp_it_fn_src"
    tgt = "wf.tmp_it_fn_tgt"
    cleanup_tables.extend([src, tgt])
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (price TEXT, addr TEXT)"))
        session.execute(
            text(
                f"INSERT INTO {src} (price, addr) VALUES "
                "('1,500', '서울특별시 강남구 테헤란로'), "
                "('800', '경기도 성남시 분당구')"
            )
        )
        session.commit()

    with sm() as session:
        ctx = _ctx(session, domain_code="agri", node_key="fn")
        runner = get_v2_runner("FUNCTION_TRANSFORM")
        out = runner.run(
            ctx,
            {
                "source_table": src,
                "output_table": tgt,
                "expressions": {
                    "price_clean": "number.parse_decimal($price)",
                    "sido": "address.extract_sido($addr)",
                },
            },
        )
        session.commit()
    assert out.status == "success", out.error_message
    assert out.row_count == 2

    with sm() as session:
        rows = session.execute(text(f"SELECT price_clean, sido FROM {tgt} ORDER BY sido")).all()
    # 결과는 TEXT 컬럼으로 저장 — Decimal('1500') → '1500'.
    assert [(r.price_clean, r.sido) for r in rows] == [
        ("800", "경기도"),
        ("1500", "서울특별시"),
    ]


def test_function_transform_skip_row_on_error(cleanup_tables: list[str]) -> None:
    sm = get_sync_sessionmaker()
    src = "wf.tmp_it_fn_skip_src"
    tgt = "wf.tmp_it_fn_skip_tgt"
    cleanup_tables.extend([src, tgt])
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (price TEXT)"))
        session.execute(text(f"INSERT INTO {src} VALUES ('1500'),('not-a-number'),('200')"))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", node_key="skip")
        runner = get_v2_runner("FUNCTION_TRANSFORM")
        out = runner.run(
            ctx,
            {
                "source_table": src,
                "output_table": tgt,
                "expressions": {"v": "number.parse_decimal($price)"},
                "on_function_error": "skip_row",
            },
        )
        session.commit()
    assert out.status == "success"
    assert out.row_count == 2  # 'not-a-number' skip
    assert out.payload["skipped_rows"] == 1


# ===========================================================================
# 7. LOAD_TARGET
# ===========================================================================
def test_load_target_append_only(
    cleanup_tables: list[str],
    cleanup_domain_meta: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    domain_code = _new_domain_code()
    src = "wf.tmp_it_lt_src"
    tgt = f"mart.it_lt_tgt_{secrets.token_hex(3).lower()}"
    cleanup_tables.extend([src, tgt])
    with sm() as session:
        _ensure_domain(session, domain_code)
        cleanup_domain_meta["domain_codes"].append(domain_code)

        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (k TEXT, v INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES ('a',1),('b',2)"))
        session.execute(text(f"DROP TABLE IF EXISTS {tgt}"))
        session.execute(text(f"CREATE TABLE {tgt} (k TEXT, v INT)"))

        # resource + APPROVED policy.
        rid = session.execute(
            text(
                "INSERT INTO domain.resource_definition "
                "(domain_code, resource_code, fact_table, status, version) "
                "VALUES (:d, 'res', :ft, 'PUBLISHED', 1) "
                "RETURNING resource_id"
            ),
            {"d": domain_code, "ft": tgt},
        ).scalar_one()
        cleanup_domain_meta["resource_ids"].append(int(rid))
        pid = session.execute(
            text(
                "INSERT INTO domain.load_policy "
                "(resource_id, mode, key_columns, status, version) "
                "VALUES (:rid, 'append_only', '{}', 'APPROVED', 1) "
                "RETURNING policy_id"
            ),
            {"rid": rid},
        ).scalar_one()
        cleanup_domain_meta["policy_ids"].append(int(pid))
        session.commit()

    with sm() as session:
        ctx = _ctx(session, domain_code=domain_code, node_key="load")
        runner = get_v2_runner("LOAD_TARGET")
        out = runner.run(ctx, {"source_table": src, "policy_id": int(pid)})
        session.commit()
    assert out.status == "success", out.error_message
    assert out.payload["mode"] == "append_only"
    assert out.payload["rows_affected"] == 2


def test_load_target_draft_policy_rejected(
    cleanup_tables: list[str],
    cleanup_domain_meta: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    domain_code = _new_domain_code()
    tgt = f"mart.it_lt_draft_{secrets.token_hex(3).lower()}"
    cleanup_tables.append(tgt)
    with sm() as session:
        _ensure_domain(session, domain_code)
        cleanup_domain_meta["domain_codes"].append(domain_code)
        session.execute(text(f"DROP TABLE IF EXISTS {tgt}"))
        session.execute(text(f"CREATE TABLE {tgt} (k TEXT)"))
        rid = session.execute(
            text(
                "INSERT INTO domain.resource_definition "
                "(domain_code, resource_code, fact_table, status, version) "
                "VALUES (:d, 'res2', :ft, 'PUBLISHED', 1) RETURNING resource_id"
            ),
            {"d": domain_code, "ft": tgt},
        ).scalar_one()
        cleanup_domain_meta["resource_ids"].append(int(rid))
        pid = session.execute(
            text(
                "INSERT INTO domain.load_policy "
                "(resource_id, mode, key_columns, status, version) "
                "VALUES (:rid, 'append_only', '{}', 'DRAFT', 1) RETURNING policy_id"
            ),
            {"rid": rid},
        ).scalar_one()
        cleanup_domain_meta["policy_ids"].append(int(pid))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code=domain_code)
        runner = get_v2_runner("LOAD_TARGET")
        out = runner.run(ctx, {"source_table": "wf.does_not_matter", "policy_id": int(pid)})
    assert out.status == "failed"
    assert out.payload["reason"] == "policy_not_approved"


# ===========================================================================
# 8. HTTP_TRANSFORM dry_run
# ===========================================================================
def test_http_transform_dry_run_no_real_call(cleanup_tables: list[str]) -> None:
    sm = get_sync_sessionmaker()
    src = "wf.tmp_it_http_src"
    cleanup_tables.append(src)
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (addr TEXT)"))
        session.execute(text(f"INSERT INTO {src} VALUES ('서울'),('부산'),('대구')"))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", node_key="http")
        runner = get_v2_runner("HTTP_TRANSFORM")
        out = runner.run(
            ctx,
            {
                "provider_code": "generic_http",
                "endpoint": "https://example.invalid/never-called",
                "source_table": src,
                "request_template": {"address": "${addr}"},
                "dry_run": True,
                "chunk_size": 2,
            },
        )
    assert out.status == "success"
    assert out.payload["dry_run"] is True
    assert out.payload["input_rows"] == 3
    assert out.payload["estimated_calls"] == 2  # ceil(3/2)
