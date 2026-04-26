"""Phase 5.2.0 — 가드레일 인프라 통합 테스트.

검증:
  1. state_machine — DRAFT → REVIEW → APPROVED → PUBLISHED 전이 + ADMIN 필요한 전이 차단
  2. state_machine — 잘못된 전이 (DRAFT → APPROVED 직접) 거부
  3. state_machine — REJECT 시 to_status=DRAFT 강제
  4. sql_guard — 위험 키워드 7종 차단 (DROP/DELETE/TRUNCATE/ALTER/...)
  5. sql_guard — DQ_CHECK 는 SELECT only
  6. sql_guard — SQL_INLINE_TRANSFORM 는 stg/wf temp write 만
  7. sql_guard — LOAD_TARGET 는 allowed_load_targets 만
  8. sql_guard — 도메인 인지 ALLOWED_SCHEMAS (pos_mart 허용 vs 차단)
  9. dry_run — 트랜잭션 rollback 후 실 mart 변경 0
 10. publish_checklist — composable runner + 기본 체크 2종

실 PG 의존.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.guardrails import (
    EntityType,
    SqlGuardError,
    SqlNodeContext,
    Status,
    guard_sql,
    request_transition,
    resolve_request,
    valid_transitions,
)
from app.domain.guardrails.dry_run import run_dry
from app.domain.guardrails.publish_checklist import (
    HasStatusApproved,
    PublishChecklist,
    RequiredFieldsPresent,
)
from app.domain.guardrails.sql_guard import NodeKind
from app.domain.guardrails.state_machine import TransitionError
from app.domain.sql_studio import _v1_guard_then_validate


@pytest.fixture
def cleanup_approval() -> Iterator[None]:
    yield
    sm = get_sync_sessionmaker()
    with sm() as session:
        # 본 테스트 전용 entity_id (9_999_xxx) 만 정리.
        session.execute(
            text("DELETE FROM ctl.approval_request WHERE entity_id BETWEEN 9999000 AND 9999999")
        )
        session.commit()
    dispose_sync_engine()


# ===========================================================================
# 1. state_machine — 정상 흐름
# ===========================================================================
def test_state_machine_full_flow(cleanup_approval: None) -> None:
    sm = get_sync_sessionmaker()
    entity_id = 9_999_001
    with sm() as session:
        # DRAFT → REVIEW (요청자 본인, 즉시 결재)
        r1 = request_transition(
            session,
            entity_type=EntityType.SOURCE_CONTRACT,
            entity_id=entity_id, entity_version=1,
            from_status=Status.DRAFT, to_status=Status.REVIEW,
            requester_user_id=1,
        )
        assert r1.is_admin_required is False
        assert r1.decision == "APPROVE"

        # REVIEW → APPROVED (ADMIN 결재 필요 — pending 상태로 적재)
        r2 = request_transition(
            session,
            entity_type=EntityType.SOURCE_CONTRACT,
            entity_id=entity_id, entity_version=1,
            from_status=Status.REVIEW, to_status=Status.APPROVED,
            requester_user_id=1,
        )
        assert r2.is_admin_required is True
        assert r2.decision == "PENDING"

        # ADMIN 이 APPROVE
        r2_resolved = resolve_request(
            session,
            request_id=r2.request_id,
            decision="APPROVE",
            approver_user_id=2,
            is_admin=True,
        )
        assert r2_resolved.decision == "APPROVE"
        assert r2_resolved.to_status == Status.APPROVED

        # APPROVED → PUBLISHED (ADMIN)
        r3 = request_transition(
            session,
            entity_type=EntityType.SOURCE_CONTRACT,
            entity_id=entity_id, entity_version=1,
            from_status=Status.APPROVED, to_status=Status.PUBLISHED,
            requester_user_id=1,
        )
        resolve_request(
            session,
            request_id=r3.request_id,
            decision="APPROVE",
            approver_user_id=2,
            is_admin=True,
        )
        session.commit()


# ===========================================================================
# 2. state_machine — 잘못된 전이 차단
# ===========================================================================
def test_state_machine_invalid_transition_blocked(cleanup_approval: None) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session, pytest.raises(TransitionError, match="not allowed"):
        request_transition(
            session,
            entity_type=EntityType.DQ_RULE,
            entity_id=9_999_002, entity_version=1,
            from_status=Status.DRAFT,
            to_status=Status.APPROVED,  # DRAFT → APPROVED 직접 X
            requester_user_id=1,
        )


# ===========================================================================
# 3. state_machine — REJECT 는 to_status=DRAFT 강제
# ===========================================================================
def test_state_machine_reject_forces_draft(cleanup_approval: None) -> None:
    sm = get_sync_sessionmaker()
    entity_id = 9_999_003
    with sm() as session:
        r = request_transition(
            session,
            entity_type=EntityType.MART_LOAD_POLICY,
            entity_id=entity_id, entity_version=1,
            from_status=Status.REVIEW, to_status=Status.APPROVED,
            requester_user_id=1,
        )
        resolved = resolve_request(
            session,
            request_id=r.request_id,
            decision="REJECT",
            approver_user_id=2,
            is_admin=True,
            reason="incomplete",
        )
        assert resolved.decision == "REJECT"
        assert resolved.to_status == Status.DRAFT
        session.commit()


# ===========================================================================
# 4. state_machine — non-admin 이 admin 전이 시도 차단
# ===========================================================================
def test_state_machine_non_admin_blocked(cleanup_approval: None) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        r = request_transition(
            session,
            entity_type=EntityType.SQL_ASSET,
            entity_id=9_999_004, entity_version=1,
            from_status=Status.REVIEW, to_status=Status.APPROVED,
            requester_user_id=1,
        )
        with pytest.raises(TransitionError, match="requires ADMIN"):
            resolve_request(
                session,
                request_id=r.request_id,
                decision="APPROVE",
                approver_user_id=99,
                is_admin=False,
            )


# ===========================================================================
# 5. state_machine — valid_transitions 헬퍼
# ===========================================================================
def test_valid_transitions_lookup() -> None:
    assert Status.REVIEW in valid_transitions(Status.DRAFT)
    assert Status.APPROVED in valid_transitions(Status.REVIEW)
    assert Status.DRAFT in valid_transitions(Status.REVIEW)  # REJECT path
    assert Status.PUBLISHED in valid_transitions(Status.APPROVED)
    assert Status.DRAFT in valid_transitions(Status.PUBLISHED)  # revise


# ===========================================================================
# 6. sql_guard — 위험 키워드 7종 차단
# ===========================================================================
@pytest.mark.parametrize(
    "bad_sql",
    [
        "DROP TABLE mart.price_fact",
        "DELETE FROM mart.price_fact WHERE 1=1",
        "TRUNCATE mart.price_fact",
        "ALTER TABLE mart.price_fact DROP COLUMN price_krw",
        "CREATE EXTENSION pg_trgm",
        "GRANT SELECT ON mart.price_fact TO public",
        "REVOKE SELECT ON mart.price_fact FROM public",
        "COPY mart.price_fact TO PROGRAM '/bin/cat'",
        "VACUUM mart.price_fact",
        "REINDEX TABLE mart.price_fact",
    ],
)
def test_sql_guard_blocks_dangerous_keywords(bad_sql: str) -> None:
    ctx = SqlNodeContext(node_kind=NodeKind.SQL_INLINE_TRANSFORM)
    with pytest.raises(SqlGuardError):
        guard_sql(bad_sql, ctx=ctx)


# ===========================================================================
# 7. sql_guard — DQ_CHECK 는 SELECT only
# ===========================================================================
def test_sql_guard_dq_check_select_only() -> None:
    ctx = SqlNodeContext(node_kind=NodeKind.DQ_CHECK)
    # SELECT 통과
    guard_sql("SELECT COUNT(*) FROM mart.price_fact", ctx=ctx)
    # INSERT 차단
    with pytest.raises(SqlGuardError, match="DQ_CHECK only allows SELECT"):
        guard_sql(
            "INSERT INTO stg.tmp_dq SELECT * FROM mart.price_fact LIMIT 0",
            ctx=ctx,
        )


# ===========================================================================
# 8. sql_guard — SQL_INLINE_TRANSFORM write target 정책
# ===========================================================================
def test_sql_guard_inline_transform_write_only_to_stg() -> None:
    ctx = SqlNodeContext(node_kind=NodeKind.SQL_INLINE_TRANSFORM)

    # SELECT 는 mart 도 허용.
    guard_sql("SELECT * FROM mart.price_fact LIMIT 10", ctx=ctx)

    # stg 로 INSERT 는 허용.
    guard_sql(
        "INSERT INTO stg.tmp_x (id, val) SELECT product_id, price_krw FROM mart.price_fact",
        ctx=ctx,
    )

    # mart 로 직접 INSERT 차단.
    with pytest.raises(SqlGuardError, match="staging/temp"):
        guard_sql(
            "INSERT INTO mart.price_fact (product_id, price_krw) "
            "SELECT 1, 1000",
            ctx=ctx,
        )


# ===========================================================================
# 9. sql_guard — LOAD_TARGET 는 allowed_load_targets 만
# ===========================================================================
def test_sql_guard_load_target_whitelist() -> None:
    ctx_allowed = SqlNodeContext(
        node_kind=NodeKind.LOAD_TARGET,
        allowed_load_targets=frozenset({"mart.price_fact"}),
    )
    guard_sql(
        "INSERT INTO mart.price_fact (product_id, price_krw) SELECT 1, 1000",
        ctx=ctx_allowed,
    )

    ctx_denied = SqlNodeContext(
        node_kind=NodeKind.LOAD_TARGET,
        allowed_load_targets=frozenset({"mart.product_master"}),
    )
    with pytest.raises(SqlGuardError, match="cannot write to"):
        guard_sql(
            "INSERT INTO mart.price_fact (product_id, price_krw) SELECT 1, 1000",
            ctx=ctx_denied,
        )


# ===========================================================================
# 10. sql_guard — 도메인 인지 ALLOWED_SCHEMAS
# ===========================================================================
def test_sql_guard_domain_aware_schemas() -> None:
    # pos 도메인 컨텍스트 — pos_mart 허용.
    ctx_pos = SqlNodeContext(
        node_kind=NodeKind.SQL_INLINE_TRANSFORM,
        domain_code="pos",
        allowed_extra_schemas=frozenset({"pos_mart", "pos_stg"}),
    )
    guard_sql("SELECT * FROM pos_mart.txn_v1 LIMIT 10", ctx=ctx_pos)

    # agri 컨텍스트 — pos_mart 차단.
    ctx_agri = SqlNodeContext(node_kind=NodeKind.SQL_INLINE_TRANSFORM)
    with pytest.raises(SqlGuardError, match="not allowed"):
        guard_sql("SELECT * FROM pos_mart.txn_v1 LIMIT 10", ctx=ctx_agri)


# ===========================================================================
# 11. dry_run — rollback 후 실 mart 변경 0
# ===========================================================================
def test_dry_run_rolls_back_changes() -> None:
    from app.db.sync_session import get_sync_engine

    eng = get_sync_engine()
    suffix = secrets.token_hex(4)
    table = f"wf.tmp_dryrun_{suffix}"

    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {table} (id INT, val TEXT)"))
        session.commit()
    try:
        # dry-run 안에서 INSERT
        result = run_dry(
            engine=eng,
            queries=[
                f"INSERT INTO {table} (id, val) VALUES (1, 'a')",
                f"INSERT INTO {table} (id, val) VALUES (2, 'b')",
            ],
            fetch_after=[f"SELECT COUNT(*) FROM {table}"],
        )
        assert result.errors == []
        assert result.rows_affected == [1, 1]
        assert result.row_counts == [2]  # rollback 전 측정
        assert result.rolled_back is True

        # rollback 후 실제 row 수 = 0.
        with sm() as session:
            count = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            assert count == 0
    finally:
        with sm() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table}"))
            session.commit()


# ===========================================================================
# 12. publish_checklist — composable runner
# ===========================================================================
def test_publish_checklist_composable() -> None:
    cl = PublishChecklist()
    cl.add(HasStatusApproved(entity_status="APPROVED"))
    cl.add(
        RequiredFieldsPresent(
            fields=frozenset({"target_table", "load_policy"}),
            payload={"target_table": "mart.price_fact", "load_policy": "append_only"},
        )
    )
    result = cl.run()
    assert result.is_pass
    assert len(result.results) == 2

    # 실패 케이스.
    cl2 = PublishChecklist(
        checks=[
            HasStatusApproved(entity_status="DRAFT"),
            RequiredFieldsPresent(
                fields=frozenset({"target_table"}),
                payload={},
            ),
        ]
    )
    result2 = cl2.run()
    assert not result2.is_pass
    assert len(result2.failed) == 2


# ===========================================================================
# 13. v1 SQL Studio 강화 — 신규 strict 가드 적용
# ===========================================================================
def test_v1_sql_studio_blocks_drop_and_delete() -> None:
    from app.integrations.sqlglot_validator import SqlValidationError

    # 정상 SELECT 통과
    _v1_guard_then_validate("SELECT * FROM mart.product_master LIMIT 10")

    # DROP 차단
    with pytest.raises(SqlValidationError):
        _v1_guard_then_validate("DROP TABLE mart.price_fact")

    # DELETE 차단
    with pytest.raises(SqlValidationError):
        _v1_guard_then_validate("DELETE FROM mart.price_fact WHERE 1=1")

    # ALTER 차단
    with pytest.raises(SqlValidationError):
        _v1_guard_then_validate("ALTER TABLE mart.price_fact DROP COLUMN price_krw")
