"""Phase 5.1 Wave 2+3 — v2 node catalog 13종 + STANDARDIZE generic 통합 테스트.

검증:
  1. list_v2_node_types() 가 13개 모두 반환.
  2. get_v2_runner() 가 13 type 모두 dispatch 성공.
  3. SOURCE_DATA / DEDUP / DQ_CHECK / NOTIFY = v1 compat wrapper 동작.
  4. OCR_TRANSFORM / CRAWL_FETCH = provider binding 미존재 시 failed payload.
  5. STANDARDIZE on agri (embedding_3stage) — namespace 미등록 → failed.
  6. STANDARDIZE on pos (alias_only) — payment_method 매핑 동작.
  7. LOAD_TARGET unsupported mode (scd_type_2) — 명확한 Phase 6 메시지.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.nodes_v2 import (
    NodeV2Context,
    NodeV2Error,
    get_v2_runner,
    list_v2_node_types,
)
from app.domain.standardization_registry import (
    StdStrategy,
    resolve_namespace,
)


@pytest.fixture
def cleanup_state() -> Iterator[dict[str, list[Any]]]:
    state: dict[str, list[Any]] = {"tables": [], "domain_codes": [], "policy_ids": []}
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in state["tables"]:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        if state["policy_ids"]:
            session.execute(
                text("DELETE FROM domain.load_policy WHERE policy_id = ANY(:ids)"),
                {"ids": state["policy_ids"]},
            )
        if state["domain_codes"]:
            session.execute(
                text("DELETE FROM domain.resource_definition WHERE domain_code = ANY(:c)"),
                {"c": state["domain_codes"]},
            )
            session.execute(
                text("DELETE FROM domain.domain_definition WHERE domain_code = ANY(:c)"),
                {"c": state["domain_codes"]},
            )
        session.commit()
    dispose_sync_engine()


def _ctx(
    session: Any,
    *,
    domain_code: str,
    source_id: int | None = None,
    contract_id: int | None = None,
    node_key: str = "T",
    pipeline_run_id: int = 9_999_700,
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
# 1. dispatcher
# ===========================================================================
def test_v2_catalog_lists_13_types() -> None:
    types = list_v2_node_types()
    assert len(types) == 13
    assert set(types) == {
        "MAP_FIELDS",
        "SQL_INLINE_TRANSFORM",
        "SQL_ASSET_TRANSFORM",
        "HTTP_TRANSFORM",
        "FUNCTION_TRANSFORM",
        "LOAD_TARGET",
        "OCR_TRANSFORM",
        "CRAWL_FETCH",
        "STANDARDIZE",
        "SOURCE_DATA",
        "DEDUP",
        "DQ_CHECK",
        "NOTIFY",
    }


def test_v2_dispatcher_resolves_all_13() -> None:
    for t in list_v2_node_types():
        runner = get_v2_runner(t)
        assert runner.node_type == t


def test_v2_dispatcher_rejects_unknown() -> None:
    with pytest.raises(NodeV2Error):
        get_v2_runner("UNKNOWN_NODE")


# ===========================================================================
# 2. v1 compat wrappers
# ===========================================================================
def test_dedup_wrapper_runs(cleanup_state: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    src = f"wf.tmp_p51_dedup_src_{secrets.token_hex(3).lower()}"
    out = f"wf.tmp_p51_dedup_out_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].extend([src, out])
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (k TEXT, v INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES ('a',1),('a',2),('b',3)"))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", node_key="dedup")
        runner = get_v2_runner("DEDUP")
        result = runner.run(
            ctx,
            {
                "input_table": src,
                "key_columns": ["k"],
                "output_table": out,
            },
        )
        session.commit()
    assert result.status == "success"
    assert result.row_count == 2


def test_notify_wrapper_emits_outbox() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", node_key="notify_v2")
        runner = get_v2_runner("NOTIFY")
        result = runner.run(
            ctx,
            {
                "channel": "slack",
                "target": "#test",
                "level": "INFO",
                "body": "phase 5.1 wave 2 wrapper test",
            },
        )
        session.commit()
    assert result.status == "success"
    assert result.payload["queued"] is True


# ===========================================================================
# 3. OCR / CRAWL provider registry 통합
# ===========================================================================
def test_ocr_transform_no_binding_returns_failed() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", source_id=999_999)
        runner = get_v2_runner("OCR_TRANSFORM")
        result = runner.run(
            ctx,
            {"raw_object_id": 1, "dry_run": True},
        )
    assert result.status == "failed"
    assert result.payload["reason"] == "no_binding"


def test_crawl_fetch_no_binding_returns_failed() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", source_id=999_998)
        runner = get_v2_runner("CRAWL_FETCH")
        result = runner.run(
            ctx,
            {"target_url": "https://example.invalid/page", "dry_run": True},
        )
    assert result.status == "failed"
    assert result.payload["reason"] == "no_binding"


def test_ocr_requires_source_id() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ctx = _ctx(session, domain_code="agri", source_id=None)
        runner = get_v2_runner("OCR_TRANSFORM")
        with pytest.raises(NodeV2Error):
            runner.run(ctx, {"raw_object_id": 1, "dry_run": True})


# ===========================================================================
# 4. STANDARDIZE
# ===========================================================================
def test_standardize_namespace_not_found(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"p51d_{secrets.token_hex(3).lower()}"
    cleanup_state["domain_codes"].append(code)
    with sm() as session:
        session.execute(
            text(
                "INSERT INTO domain.domain_definition "
                "(domain_code, name, schema_yaml, status, version) "
                "VALUES (:c, :n, '{}'::jsonb, 'PUBLISHED', 1) "
                "ON CONFLICT DO NOTHING"
            ),
            {"c": code, "n": f"p5.1 {code}"},
        )
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code=code)
        runner = get_v2_runner("STANDARDIZE")
        result = runner.run(
            ctx,
            {
                "namespace": "NONEXISTENT_NS",
                "target_table": "wf.fake",
                "raw_column": "raw",
                "std_column": "std",
            },
        )
    assert result.status == "failed"
    assert result.payload["reason"] == "namespace_not_found"


def test_standardize_pos_payment_method_alias(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    src = f"wf.tmp_p51_std_pos_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(src)
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (raw TEXT, std TEXT)"))
        session.execute(
            text(f"INSERT INTO {src} (raw) VALUES ('카드'),('현금'),('카카오페이')")
        )
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code="pos", node_key="std_pos")
        runner = get_v2_runner("STANDARDIZE")
        result = runner.run(
            ctx,
            {
                "namespace": "PAYMENT_METHOD",
                "target_table": src,
                "raw_column": "raw",
                "std_column": "std",
            },
        )
        session.commit()
    assert result.status == "success", result.error_message
    assert result.payload["strategy"] == "alias_only"
    with sm() as session:
        rows = session.execute(text(f"SELECT raw, std FROM {src} ORDER BY raw")).all()
    mapping = {r.raw: r.std for r in rows}
    assert mapping["카드"] == "CARD"
    assert mapping["현금"] == "CASH"
    assert mapping["카카오페이"] == "MOBILE_PAY"


def test_standardize_pos_strategy_lookup() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        spec = resolve_namespace(
            session, domain_code="pos", namespace="PAYMENT_METHOD"
        )
    assert spec is not None
    assert spec.strategy == StdStrategy.ALIAS_ONLY
    assert spec.std_code_table == "pos_mart.std_payment_method"


# ===========================================================================
# 5. LOAD_TARGET unsupported mode
# ===========================================================================
def test_load_target_scd2_returns_phase6_message(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"p51d_{secrets.token_hex(3).lower()}"
    cleanup_state["domain_codes"].append(code)
    src = f"wf.tmp_p51_lt_src_{secrets.token_hex(3).lower()}"
    tgt = f"mart.p51_lt_tgt_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].extend([src, tgt])
    with sm() as session:
        session.execute(
            text(
                "INSERT INTO domain.domain_definition "
                "(domain_code, name, schema_yaml, status, version) "
                "VALUES (:c, 'p51', '{}'::jsonb, 'PUBLISHED', 1) ON CONFLICT DO NOTHING"
            ),
            {"c": code},
        )
        session.execute(text(f"DROP TABLE IF EXISTS {src}"))
        session.execute(text(f"CREATE TABLE {src} (k TEXT, v INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES ('a',1)"))
        session.execute(text(f"DROP TABLE IF EXISTS {tgt}"))
        session.execute(text(f"CREATE TABLE {tgt} (k TEXT, v INT)"))
        # SCD2 mode policy.
        rid = session.execute(
            text(
                "INSERT INTO domain.resource_definition "
                "(domain_code, resource_code, fact_table, status, version) "
                "VALUES (:d, 'r1', :ft, 'PUBLISHED', 1) RETURNING resource_id"
            ),
            {"d": code, "ft": tgt},
        ).scalar_one()
        pid = session.execute(
            text(
                "INSERT INTO domain.load_policy "
                "(resource_id, mode, key_columns, status, version) "
                "VALUES (:r, 'scd_type_2', '{k}', 'APPROVED', 1) RETURNING policy_id"
            ),
            {"r": rid},
        ).scalar_one()
        cleanup_state["policy_ids"].append(int(pid))
        session.commit()
    with sm() as session:
        ctx = _ctx(session, domain_code=code, node_key="lt_scd")
        runner = get_v2_runner("LOAD_TARGET")
        result = runner.run(ctx, {"source_table": src, "policy_id": int(pid)})
    assert result.status == "failed"
    assert result.payload["reason"] == "mode_not_implemented"
    assert result.payload["mode"] == "scd_type_2"
    assert result.payload["recommended_modes"] == ["append_only", "upsert"]
    assert result.payload["phase"] == "6"
