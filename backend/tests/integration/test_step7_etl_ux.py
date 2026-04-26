"""Phase 5.2.4 STEP 7 — ETL UX MVP backend 통합 테스트.

검증:
  1. user × domain 권한 매트릭스 — VIEWER/EDITOR/APPROVER/ADMIN 위계
  2. 전역 ADMIN 자동 통과
  3. Mart Designer — CREATE / ALTER / 거부 케이스
  4. Mini Publish Checklist — 통과 / 실패
  5. /v2/dryrun/sql + /v2/dryrun/load-target + /v2/dryrun/mart-designer
  6. /v2/dq-rules/preview — sql_guard 차단
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.guardrails.mini_publish_checklist import run_checklist
from app.domain.mart_designer import (
    ColumnSpec,
    MartDesignError,
    MartDesignSpec,
    design_table,
)
from app.domain.permissions import (
    DomainRole,
    DomainRoleError,
    grant_domain_role,
    has_domain_role,
    list_user_domain_roles,
    require_domain_role,
)


@pytest.fixture
def cleanup_state() -> Iterator[dict[str, list[Any]]]:
    state: dict[str, list[Any]] = {
        "domains": [],
        "tables": [],
        "user_ids": [],
    }
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in state["tables"]:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        if state["domains"]:
            # FK 의존성 정리: dq_rule, field_mapping, source_contract → domain.
            session.execute(
                text("DELETE FROM domain.dq_rule WHERE domain_code = ANY(:c)"),
                {"c": state["domains"]},
            )
        if state["user_ids"]:
            session.execute(
                text(
                    "DELETE FROM ctl.approval_request "
                    "WHERE requester_user_id = ANY(:ids) OR approver_user_id = ANY(:ids)"
                ),
                {"ids": state["user_ids"]},
            )
            session.execute(
                text(
                    "DELETE FROM ctl.publish_checklist_run "
                    "WHERE requested_by = ANY(:ids)"
                ),
                {"ids": state["user_ids"]},
            )
            session.execute(
                text(
                    "DELETE FROM ctl.dry_run_record WHERE requested_by = ANY(:ids)"
                ),
                {"ids": state["user_ids"]},
            )
            session.execute(
                text("DELETE FROM ctl.user_domain_role WHERE user_id = ANY(:ids)"),
                {"ids": state["user_ids"]},
            )
            session.execute(
                text("DELETE FROM ctl.user_role WHERE user_id = ANY(:ids)"),
                {"ids": state["user_ids"]},
            )
            session.execute(
                text("DELETE FROM ctl.app_user WHERE user_id = ANY(:ids)"),
                {"ids": state["user_ids"]},
            )
        if state["domains"]:
            session.execute(
                text("DELETE FROM domain.domain_definition WHERE domain_code = ANY(:c)"),
                {"c": state["domains"]},
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
        {"c": code, "n": f"IT step7 domain {code}", "d": "step7-it"},
    )


def _new_user(session: Any, login_prefix: str) -> int:
    suffix = secrets.token_hex(3).lower()
    uid = session.execute(
        text(
            "INSERT INTO ctl.app_user "
            "(login_id, display_name, password_hash, is_active) "
            "VALUES (:l, :n, '$argon2id$test', TRUE) RETURNING user_id"
        ),
        {"l": f"{login_prefix}_{suffix}", "n": f"step7 {login_prefix}"},
    ).scalar_one()
    return int(uid)


# ===========================================================================
# 1. user × domain 권한 매트릭스
# ===========================================================================
def test_permission_role_hierarchy(cleanup_state: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    code = f"step7d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        uid = _new_user(session, "viewer")
        cleanup_state["user_ids"].append(uid)
        grant_domain_role(
            session, user_id=uid, domain_code=code, role=DomainRole.EDITOR
        )
        session.commit()

    with sm() as session:
        # EDITOR 는 EDITOR + VIEWER 통과.
        assert has_domain_role(
            session, user_id=uid, domain_code=code, required=DomainRole.VIEWER
        )
        assert has_domain_role(
            session, user_id=uid, domain_code=code, required=DomainRole.EDITOR
        )
        # APPROVER / ADMIN 은 거부.
        assert not has_domain_role(
            session, user_id=uid, domain_code=code, required=DomainRole.APPROVER
        )
        assert not has_domain_role(
            session, user_id=uid, domain_code=code, required=DomainRole.ADMIN
        )

        with pytest.raises(DomainRoleError):
            require_domain_role(
                session, user_id=uid, domain_code=code, required=DomainRole.ADMIN
            )


def test_global_admin_bypasses_per_domain(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step7d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        uid = _new_user(session, "globaladmin")
        cleanup_state["user_ids"].append(uid)
        # 전역 ADMIN role 부여 — ctl.role.role_code='ADMIN' (시드되어 있어야 함).
        admin_role_id = session.execute(
            text("SELECT role_id FROM ctl.role WHERE role_code = 'ADMIN'")
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO ctl.user_role (user_id, role_id) VALUES (:u, :r) "
                "ON CONFLICT DO NOTHING"
            ),
            {"u": uid, "r": admin_role_id},
        )
        session.commit()

    with sm() as session:
        # 전역 ADMIN 은 별도 grant 없이도 모든 도메인 ADMIN.
        assert has_domain_role(
            session, user_id=uid, domain_code=code, required=DomainRole.ADMIN
        )
        rows = list_user_domain_roles(session, user_id=uid)
        assert ("*", "ADMIN") in rows


# ===========================================================================
# 2. Mart Designer
# ===========================================================================
def test_mart_designer_create_table(cleanup_state: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    code = "agri"  # mart 스키마는 도메인 무관 mart, 또는 agri_mart.
    target = f"mart.it_md_create_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(target)
    spec = MartDesignSpec(
        domain_code=code,
        target_table=target,
        columns=[
            ColumnSpec(name="id", type="BIGINT", nullable=False),
            ColumnSpec(name="name", type="TEXT"),
            ColumnSpec(name="amount", type="NUMERIC"),
        ],
        primary_key=["id"],
    )
    with sm() as session:
        result = design_table(session, spec)
    assert result.is_alter is False
    assert "CREATE TABLE" in result.ddl_text
    assert "PRIMARY KEY" in result.ddl_text
    assert result.diff_summary["columns_added"] == ["id", "name", "amount"]


def test_mart_designer_rejects_unsafe_type() -> None:
    sm = get_sync_sessionmaker()
    spec = MartDesignSpec(
        domain_code="agri",
        target_table="mart.it_md_unsafe",
        columns=[ColumnSpec(name="x", type="DROP TABLE; --")],
    )
    with sm() as session, pytest.raises(MartDesignError):
        design_table(session, spec)


def test_mart_designer_alter_adds_nullable_column(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    target = f"mart.it_md_alter_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(target)
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {target}"))
        session.execute(text(f"CREATE TABLE {target} (id BIGINT PRIMARY KEY)"))
        session.commit()
    spec = MartDesignSpec(
        domain_code="agri",
        target_table=target,
        columns=[
            ColumnSpec(name="id", type="BIGINT", nullable=False),
            ColumnSpec(name="new_col", type="TEXT", nullable=True),
        ],
    )
    with sm() as session:
        result = design_table(session, spec)
    assert result.is_alter is True
    assert "ADD COLUMN" in result.ddl_text
    assert "new_col" in result.ddl_text


def test_mart_designer_rejects_not_null_without_default(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    target = f"mart.it_md_alter_nn_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(target)
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {target}"))
        session.execute(text(f"CREATE TABLE {target} (id BIGINT PRIMARY KEY)"))
        session.commit()
    spec = MartDesignSpec(
        domain_code="agri",
        target_table=target,
        columns=[
            ColumnSpec(name="id", type="BIGINT", nullable=False),
            ColumnSpec(name="forced", type="TEXT", nullable=False),
        ],
    )
    with sm() as session, pytest.raises(MartDesignError):
        design_table(session, spec)


# ===========================================================================
# 3. Mini Publish Checklist
# ===========================================================================
def test_checklist_status_check_only() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        outcome = run_checklist(
            session,
            entity_type="dq_rule",
            entity_id=999_999,  # 존재 안 함 — approver_signed False.
            entity_version=1,
            current_status="DRAFT",  # APPROVED 아님 → False.
        )
        session.rollback()
    # status_chain_valid + approver_signed → 둘 다 False.
    codes = {c.code: c.passed for c in outcome.checks}
    assert codes["status_chain_valid"] is False
    assert codes["approver_signed"] is False
    assert outcome.all_passed is False


def test_checklist_passes_with_approval(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step7d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    target = f"mart.it_chk_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(target)

    with sm() as session:
        _ensure_domain(session, code)
        uid = _new_user(session, "approver")
        cleanup_state["user_ids"].append(uid)
        # entity = dq_rule.
        rule_id = session.execute(
            text(
                "INSERT INTO domain.dq_rule "
                "(domain_code, target_table, rule_kind, rule_json, severity, "
                " status, version, description) "
                "VALUES (:d, :t, 'row_count_min', CAST(:rj AS JSONB), 'ERROR', "
                "        'APPROVED', 1, 'it') RETURNING rule_id"
            ),
            {"d": code, "t": target, "rj": '{"min":1}'},
        ).scalar_one()
        # APPROVE row.
        session.execute(
            text(
                "INSERT INTO ctl.approval_request "
                "(entity_type, entity_id, entity_version, from_status, to_status, "
                " requester_user_id, approver_user_id, decision, decided_at) "
                "VALUES ('dq_rule', :rid, 1, 'REVIEW', 'APPROVED', "
                "        :u, :u, 'APPROVE', now())"
            ),
            {"rid": rule_id, "u": uid},
        )
        session.commit()

    with sm() as session:
        outcome = run_checklist(
            session,
            entity_type="dq_rule",
            entity_id=int(rule_id),
            entity_version=1,
            current_status="APPROVED",
            domain_code=code,
            requested_by=uid,
        )
        session.commit()
    codes = {c.code: c.passed for c in outcome.checks}
    assert codes["status_chain_valid"] is True
    assert codes["approver_signed"] is True


# ===========================================================================
# 4. v2 dryrun + dq-rules + checklist via TestClient
# ===========================================================================
def test_dryrun_sql_endpoint(it_client, admin_auth) -> None:  # type: ignore[no-untyped-def]
    r = it_client.post(
        "/v2/dryrun/sql",
        json={
            "queries": ["SELECT 1"],
            "fetch_after": ["SELECT 1"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "custom"
    assert body["errors"] == []
    assert body["row_counts"] == [1]
    assert body["dry_run_id"] is not None


def test_mart_designer_dryrun_endpoint(it_client, admin_auth) -> None:  # type: ignore[no-untyped-def]
    target = f"mart.it_md_ep_{secrets.token_hex(3).lower()}"
    r = it_client.post(
        "/v2/dryrun/mart-designer",
        json={
            "domain_code": "agri",
            "target_table": target,
            "columns": [
                {"name": "id", "type": "BIGINT", "nullable": False},
                {"name": "v", "type": "TEXT"},
            ],
            "primary_key": ["id"],
            "save_as_draft": False,
        },
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_alter"] is False
    assert "CREATE TABLE" in body["ddl_text"]


def test_dq_rules_preview_blocks_dangerous_sql(it_client, admin_auth) -> None:  # type: ignore[no-untyped-def]
    r = it_client.post(
        "/v2/dq-rules/preview",
        json={
            "domain_code": "agri",
            "sql": "DROP TABLE mart.price_fact",
        },
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_valid"] is False
    assert "guard" in (body["error"] or "").lower() or "denied" in (body["error"] or "").lower()


def test_dq_rules_crud_via_api(it_client, admin_auth) -> None:  # type: ignore[no-untyped-def]
    sm = get_sync_sessionmaker()
    code = f"step7api_{secrets.token_hex(3).lower()}"
    target = f"mart.dq_api_{secrets.token_hex(3).lower()}"
    with sm() as session:
        _ensure_domain(session, code)
        session.commit()
    try:
        r = it_client.post(
            "/v2/dq-rules",
            json={
                "domain_code": code,
                "target_table": target,
                "rule_kind": "row_count_min",
                "rule_json": {"min": 1},
                "severity": "ERROR",
            },
            headers=admin_auth,
        )
        assert r.status_code == 201, r.text
        rule_id = r.json()["rule_id"]
        r = it_client.patch(
            f"/v2/dq-rules/{rule_id}",
            json={"status": "REVIEW"},
            headers=admin_auth,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "REVIEW"
    finally:
        with sm() as session:
            session.execute(
                text("DELETE FROM domain.dq_rule WHERE domain_code = :d"),
                {"d": code},
            )
            session.execute(
                text("DELETE FROM domain.domain_definition WHERE domain_code = :d"),
                {"d": code},
            )
            session.commit()
        dispose_sync_engine()
