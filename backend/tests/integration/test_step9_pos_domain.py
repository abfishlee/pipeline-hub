"""Phase 5.2.6 STEP 9 — POS 도메인 e2e 통합 테스트 (추상화 검증).

검증 가설: yaml + migration + seed 만으로 새 도메인이 동작.

테스트 시나리오:
  1. domain.* registry 에 'pos' 도메인이 PUBLISHED 로 등록됨.
  2. 'pos' 의 3 resource (TRANSACTION/STORE/TERMINAL) + 2 namespace 등록.
  3. payment_method 7 std_code + 22 alias 시드 검증.
  4. alias_lookup — 한국어/영어 raw → std_code 매핑.
  5. standardize_column_in_table — bulk UPDATE 후 모든 row 의
     payment_method_std 가 채워짐.
  6. cutover_flag — pos 의 3 resource 가 active='v2' + v1_write_disabled=TRUE.
  7. SQL_INLINE_TRANSFORM 노드를 pos_mart.pos_transaction → wf.tmp 로 동작 검증.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.nodes_v2 import NodeV2Context, get_v2_runner
from app.domain.std_alias import (
    AliasMatch,
    lookup_alias,
    standardize_column_in_table,
)


@pytest.fixture
def cleanup_sandbox() -> Iterator[list[str]]:
    tables: list[str] = []
    yield tables
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in tables:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        session.commit()
    dispose_sync_engine()


# ===========================================================================
# 1. registry seed 검증
# ===========================================================================
def test_pos_domain_registered() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        row = session.execute(
            text(
                "SELECT domain_code, status FROM domain.domain_definition "
                "WHERE domain_code = 'pos'"
            )
        ).first()
        assert row is not None
        assert row.status == "PUBLISHED"


def test_pos_resources_registered() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = session.execute(
            text(
                "SELECT resource_code, fact_table, canonical_table "
                "FROM domain.resource_definition WHERE domain_code = 'pos' "
                "ORDER BY resource_code"
            )
        ).all()
    codes = {r.resource_code for r in rows}
    assert codes == {"STORE", "TERMINAL", "TRANSACTION"}


def test_pos_namespaces_registered() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = session.execute(
            text(
                "SELECT name, std_code_table FROM domain.standard_code_namespace "
                "WHERE domain_code = 'pos' ORDER BY name"
            )
        ).all()
    assert {r.name for r in rows} == {"PAYMENT_METHOD", "STORE_CHANNEL"}


def test_payment_method_seed_present() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = session.execute(
            text(
                "SELECT std_code FROM pos_mart.std_payment_method "
                "WHERE is_active = TRUE ORDER BY sort_order"
            )
        ).all()
        std_codes = {r.std_code for r in rows}
    assert std_codes == {
        "CARD",
        "CASH",
        "MOBILE_PAY",
        "POINT",
        "VOUCHER",
        "COUPON",
        "OTHER",
    }
    with sm() as session:
        alias_count = session.execute(
            text("SELECT COUNT(*) FROM pos_mart.std_payment_method_alias")
        ).scalar_one()
    assert int(alias_count) >= 15


# ===========================================================================
# 2. alias_lookup
# ===========================================================================
def test_alias_lookup_korean_aliases() -> None:
    sm = get_sync_sessionmaker()
    expected = {
        "신용카드": "CARD",
        "카드": "CARD",
        "현금": "CASH",
        "카카오페이": "MOBILE_PAY",
        "네이버페이": "MOBILE_PAY",
        "OK캐쉬백": "POINT",
        "쿠폰": "COUPON",
        "상품권": "VOUCHER",
    }
    with sm() as session:
        for raw, std in expected.items():
            match: AliasMatch = lookup_alias(
                session,
                domain_code="pos",
                namespace="PAYMENT_METHOD",
                raw_value=raw,
            )
            assert match.std_code == std, f"{raw!r} → {match.std_code} (expected {std})"
            assert match.matched_via in ("alias", "std_code")


def test_alias_lookup_unknown_falls_back_to_other() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        match = lookup_alias(
            session,
            domain_code="pos",
            namespace="PAYMENT_METHOD",
            raw_value="비트코인-결제",
        )
    assert match.std_code == "OTHER"
    assert match.matched_via == "fallback_other"


# ===========================================================================
# 3. bulk standardize on mock data
# ===========================================================================
def test_standardize_pos_transaction_mock_data() -> None:
    sm = get_sync_sessionmaker()
    # 1) std 컬럼 reset (멱등 검증) — 이전 실행이 채웠을 수 있음.
    with sm() as session:
        session.execute(
            text("UPDATE pos_mart.pos_transaction SET payment_method_std = NULL")
        )
        session.commit()
    with sm() as session:
        cnt_total = session.execute(
            text("SELECT COUNT(*) FROM pos_mart.pos_transaction")
        ).scalar_one()
        cnt_unfilled = session.execute(
            text(
                "SELECT COUNT(*) FROM pos_mart.pos_transaction "
                "WHERE payment_method_std IS NULL"
            )
        ).scalar_one()
        assert cnt_total >= 50
        assert cnt_unfilled == cnt_total  # reset 직후 모두 NULL.

    # 2) bulk standardize.
    with sm() as session:
        counts = standardize_column_in_table(
            session,
            domain_code="pos",
            namespace="PAYMENT_METHOD",
            target_table="pos_mart.pos_transaction",
            raw_column="payment_method_raw",
            std_column="payment_method_std",
        )
        session.commit()

    assert counts["matched_via_alias"] >= 1
    assert counts["fallback"] == 0  # mock 5종 모두 alias 사전에 있음.

    # 3) 모든 row 가 std 를 가짐.
    with sm() as session:
        leftover = session.execute(
            text(
                "SELECT COUNT(*) FROM pos_mart.pos_transaction "
                "WHERE payment_method_std IS NULL"
            )
        ).scalar_one()
    assert leftover == 0


# ===========================================================================
# 4. cutover_flag — pos 는 v2-only baseline
# ===========================================================================
def test_pos_cutover_flag_is_v2_only() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = session.execute(
            text(
                "SELECT resource_code, active_path, v2_read_enabled, "
                "       v1_write_disabled FROM ctl.cutover_flag "
                "WHERE domain_code = 'pos' ORDER BY resource_code"
            )
        ).all()
    assert len(rows) == 3
    for r in rows:
        assert r.active_path == "v2"
        assert r.v2_read_enabled is True
        assert r.v1_write_disabled is True


# ===========================================================================
# 5. SQL_INLINE_TRANSFORM — pos_mart 도메인 인지 sql_guard 통과
# ===========================================================================
def test_sql_inline_transform_on_pos(cleanup_sandbox: list[str]) -> None:
    sm = get_sync_sessionmaker()
    out_table = f"wf.tmp_pos_e2e_{secrets.token_hex(3).lower()}"
    cleanup_sandbox.append(out_table)
    with sm() as session:
        ctx = NodeV2Context(
            session=session,
            pipeline_run_id=9_999_900,
            node_run_id=9_999_900,
            node_key="pos_e2e",
            domain_code="pos",
            user_id=None,
        )
        runner = get_v2_runner("SQL_INLINE_TRANSFORM")
        out = runner.run(
            ctx,
            {
                "sql": (
                    "SELECT payment_method_std AS pm, COUNT(*) AS c "
                    "FROM pos_mart.pos_transaction "
                    "WHERE payment_method_std IS NOT NULL "
                    "GROUP BY payment_method_std"
                ),
                "output_table": out_table,
            },
        )
        session.commit()
    assert out.status == "success", out.error_message
    assert out.row_count >= 1


# ===========================================================================
# 6. yaml 자체 형식 검증 (정적 — 코드 수정 0 가설 보장)
# ===========================================================================
def test_pos_yaml_is_loadable() -> None:
    """domains/pos.yaml 이 yaml.safe_load 통과 + 핵심 키 존재."""
    import pathlib

    import yaml

    here = pathlib.Path(__file__).resolve()
    repo_root = here.parents[3]
    yaml_path = repo_root / "domains" / "pos.yaml"
    assert yaml_path.exists(), f"missing pos.yaml at {yaml_path}"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["domain_code"] == "pos"
    assert {r["resource_code"] for r in data["resources"]} == {
        "TRANSACTION",
        "STORE",
        "TERMINAL",
    }
    namespaces = {ns["name"] for ns in data["standard_code_namespaces"]}
    assert namespaces == {"PAYMENT_METHOD", "STORE_CHANNEL"}
