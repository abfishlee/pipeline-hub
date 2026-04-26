"""Phase 5.2.5 STEP 8 — Shadow Run + T0 Checksum + Cutover 통합 테스트.

검증:
  1. T0 checksum — 같은 데이터 → 같은 sha256.
  2. T0 checksum — partition 분할 후 sum row_count 일치.
  3. record_shadow_diff — identical 은 skip, mismatch 는 적재.
  4. diff_kind_for — value/row_count/schema/v1_only/v2_only 분기.
  5. apply_cutover — block (>= 1%), warning (0.01%~1%), 통과.
  6. /v2/cutover/start + /apply + /diff-report endpoint.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.v1_to_v2 import (
    CutoverError,
    apply_cutover,
    capture_table_snapshot,
    compute_partition_checksum,
    diff_kind_for,
    record_shadow_diff,
    upsert_cutover_flag,
)


@pytest.fixture
def cleanup_state() -> Iterator[dict[str, list[Any]]]:
    state: dict[str, list[Any]] = {
        "tables": [],
        "domains": [],
        "diff_domains": [],  # for cleanup of audit.shadow_diff
    }
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in state["tables"]:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        if state["diff_domains"]:
            session.execute(
                text(
                    "DELETE FROM audit.shadow_diff WHERE domain_code = ANY(:d)"
                ),
                {"d": state["diff_domains"]},
            )
            session.execute(
                text(
                    "DELETE FROM audit.t0_snapshot WHERE domain_code = ANY(:d)"
                ),
                {"d": state["diff_domains"]},
            )
            session.execute(
                text(
                    "DELETE FROM ctl.cutover_flag WHERE domain_code = ANY(:d)"
                ),
                {"d": state["diff_domains"]},
            )
        if state["domains"]:
            session.execute(
                text(
                    "DELETE FROM domain.domain_definition WHERE domain_code = ANY(:c)"
                ),
                {"c": state["domains"]},
            )
        session.commit()
    dispose_sync_engine()


def _ensure_domain(session: Any, code: str) -> None:
    session.execute(
        text(
            "INSERT INTO domain.domain_definition "
            "(domain_code, name, schema_yaml, status, version) "
            "VALUES (:c, :n, '{}'::jsonb, 'PUBLISHED', 1) "
            "ON CONFLICT (domain_code) DO NOTHING"
        ),
        {"c": code, "n": f"step8 {code}"},
    )


# ===========================================================================
# 1. T0 checksum
# ===========================================================================
def test_t0_checksum_identical_table(cleanup_state: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    a = f"mart.it_t0_a_{secrets.token_hex(3).lower()}"
    b = f"mart.it_t0_b_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].extend([a, b])
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {a}"))
        session.execute(text(f"DROP TABLE IF EXISTS {b}"))
        session.execute(text(f"CREATE TABLE {a} (id INT, name TEXT, ymd TEXT)"))
        session.execute(text(f"CREATE TABLE {b} (id INT, name TEXT, ymd TEXT)"))
        for t in (a, b):
            session.execute(
                text(
                    f"INSERT INTO {t} VALUES "
                    "(1,'apple','2026-04'),(2,'banana','2026-04'),(3,'cherry','2026-05')"
                )
            )
        session.commit()
    with sm() as session:
        ck_a = compute_partition_checksum(
            session, target_table=a, stable_columns=["id", "name", "ymd"]
        )
        ck_b = compute_partition_checksum(
            session, target_table=b, stable_columns=["id", "name", "ymd"]
        )
    assert ck_a.row_count == ck_b.row_count == 3
    assert ck_a.checksum == ck_b.checksum


def test_t0_checksum_detects_difference(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    a = f"mart.it_t0_diff_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(a)
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {a}"))
        session.execute(text(f"CREATE TABLE {a} (id INT, name TEXT)"))
        session.execute(text(f"INSERT INTO {a} VALUES (1,'a'),(2,'b')"))
        session.commit()
    with sm() as session:
        ck1 = compute_partition_checksum(
            session, target_table=a, stable_columns=["id", "name"]
        )
    with sm() as session:
        session.execute(text(f"UPDATE {a} SET name = 'x' WHERE id = 2"))
        session.commit()
    with sm() as session:
        ck2 = compute_partition_checksum(
            session, target_table=a, stable_columns=["id", "name"]
        )
    assert ck1.row_count == ck2.row_count == 2
    assert ck1.checksum != ck2.checksum


def test_t0_snapshot_partitioned(cleanup_state: dict[str, list[Any]]) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    cleanup_state["diff_domains"].append(code)
    table = f"mart.it_t0_p_{secrets.token_hex(3).lower()}"
    cleanup_state["tables"].append(table)
    with sm() as session:
        _ensure_domain(session, code)
        session.execute(text(f"DROP TABLE IF EXISTS {table}"))
        session.execute(text(f"CREATE TABLE {table} (id INT, ymd TEXT)"))
        session.execute(
            text(
                f"INSERT INTO {table} VALUES "
                "(1,'2026-04'),(2,'2026-04'),(3,'2026-05'),(4,'2026-06')"
            )
        )
        session.commit()
    with sm() as session:
        result = capture_table_snapshot(
            session,
            domain_code=code,
            resource_code="IT_RES",
            target_table=table,
            stable_columns=["id"],
            partition_key="ymd",
        )
        session.commit()
    # 3 partitions (2026-04 / 2026-05 / 2026-06), total rows 4.
    assert len(result.partitions) == 3
    assert result.total_rows == 4
    assert all(p.row_count >= 1 for p in result.partitions)


# ===========================================================================
# 2. Shadow Run diff
# ===========================================================================
def test_diff_kind_for_basic() -> None:
    assert diff_kind_for([1, 2], [1, 2]) == "identical_skipped"
    assert diff_kind_for([1, 2], [1, 2, 3]) == "row_count_mismatch"
    assert diff_kind_for({"a": 1}, {"a": 2}) == "value_mismatch"
    assert diff_kind_for({"a": 1}, {"b": 1}) == "schema_mismatch"
    assert diff_kind_for(None, [1]) == "v2_only"
    assert diff_kind_for([1], None) == "v1_only"


def test_record_shadow_diff_skip_identical(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8d_{secrets.token_hex(3).lower()}"
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        out = record_shadow_diff(
            session,
            domain_code=code,
            resource_code="R",
            request_kind="GET /v1/test",
            request_key="k1",
            v1_payload={"a": 1},
            v2_payload={"a": 1},
        )
        session.commit()
    assert out.diff_kind == "identical_skipped"
    assert out.inserted is False


def test_record_shadow_diff_mismatch(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8d_{secrets.token_hex(3).lower()}"
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        out = record_shadow_diff(
            session,
            domain_code=code,
            resource_code="R",
            request_kind="GET /v1/test",
            request_key="k2",
            v1_payload={"a": 1},
            v2_payload={"a": 2},
        )
        session.commit()
    assert out.diff_kind == "value_mismatch"
    assert out.inserted is True
    assert out.diff_id is not None


# ===========================================================================
# 3. Cutover gate
# ===========================================================================
def test_cutover_block_on_high_mismatch(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        upsert_cutover_flag(
            session,
            domain_code=code,
            resource_code="R",
            active_path="v1",
            v2_read_enabled=True,
        )
        # 50 rows, 5 mismatch = 10% > 1%.
        for i in range(50):
            v1 = {"x": 1}
            v2 = {"x": 1} if i >= 5 else {"x": 2}
            record_shadow_diff(
                session,
                domain_code=code,
                resource_code="R",
                request_kind="test",
                request_key=str(i),
                v1_payload=v1,
                v2_payload=v2,
                skip_identical=False,  # 통계용 — 모두 적재.
            )
        session.commit()

    with sm() as session, pytest.raises(CutoverError) as exc_info:
        apply_cutover(
            session,
            domain_code=code,
            resource_code="R",
            target_path="v2",
            approver_user_id=1,
            window_hours=24,
        )
    assert "BLOCKED" in str(exc_info.value)


def test_cutover_warning_requires_acknowledge(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        upsert_cutover_flag(
            session,
            domain_code=code,
            resource_code="R",
            active_path="v1",
            v2_read_enabled=True,
        )
        # 1000 rows, 5 mismatch = 0.5% (warning band).
        for i in range(1000):
            v1 = {"x": 1}
            v2 = {"x": 1} if i >= 5 else {"x": 2}
            record_shadow_diff(
                session,
                domain_code=code,
                resource_code="R",
                request_kind="test",
                request_key=str(i),
                v1_payload=v1,
                v2_payload=v2,
                skip_identical=False,
            )
        session.commit()

    with sm() as session, pytest.raises(CutoverError) as exc_info:
        apply_cutover(
            session,
            domain_code=code,
            resource_code="R",
            target_path="v2",
            approver_user_id=1,
            acknowledge_warning=False,
            window_hours=24,
        )
    assert "warning" in str(exc_info.value).lower() or "block" in str(exc_info.value).lower()

    # acknowledge=True 면 통과.
    with sm() as session:
        flag = apply_cutover(
            session,
            domain_code=code,
            resource_code="R",
            target_path="v2",
            approver_user_id=1,
            acknowledge_warning=True,
            window_hours=24,
        )
        session.commit()
    assert flag.active_path == "v2"
    assert flag.v1_write_disabled is True
    assert flag.cutover_at is not None


def test_cutover_clean_path_passes(
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8d_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        upsert_cutover_flag(
            session,
            domain_code=code,
            resource_code="R",
            active_path="v1",
            v2_read_enabled=True,
        )
        # 100 rows, all identical → mismatch_ratio=0.
        for i in range(100):
            record_shadow_diff(
                session,
                domain_code=code,
                resource_code="R",
                request_kind="test",
                request_key=str(i),
                v1_payload={"x": 1},
                v2_payload={"x": 1},
                skip_identical=False,
            )
        session.commit()

    with sm() as session:
        flag = apply_cutover(
            session,
            domain_code=code,
            resource_code="R",
            target_path="v2",
            approver_user_id=1,
            window_hours=24,
        )
        session.commit()
    assert flag.active_path == "v2"


# ===========================================================================
# 4. /v2/cutover endpoint
# ===========================================================================
def test_cutover_endpoint_diff_report(
    it_client,  # type: ignore[no-untyped-def]
    admin_auth,
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8api_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        upsert_cutover_flag(
            session,
            domain_code=code,
            resource_code="EP",
            active_path="v1",
        )
        for i in range(10):
            v2 = {"v": 1} if i < 8 else {"v": 2}
            record_shadow_diff(
                session,
                domain_code=code,
                resource_code="EP",
                request_kind="t",
                request_key=str(i),
                v1_payload={"v": 1},
                v2_payload=v2,
                skip_identical=False,
            )
        session.commit()

    r = it_client.get(
        "/v2/cutover/diff-report",
        params={"domain_code": code, "resource_code": "EP", "window_hours": 24},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 10
    assert body["mismatch_count"] == 2
    assert 0.19 < body["mismatch_ratio"] < 0.21


def test_cutover_endpoint_start_and_get(
    it_client,  # type: ignore[no-untyped-def]
    admin_auth,
    cleanup_state: dict[str, list[Any]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"step8api_{secrets.token_hex(3).lower()}"
    cleanup_state["domains"].append(code)
    cleanup_state["diff_domains"].append(code)
    with sm() as session:
        _ensure_domain(session, code)
        session.commit()
    r = it_client.post(
        "/v2/cutover/start",
        json={"domain_code": code, "resource_code": "RES1", "notes": "step8 it"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    flag = r.json()
    assert flag["v2_read_enabled"] is True
    assert flag["active_path"] == "v1"
    assert flag["shadow_started_at"] is not None

    r2 = it_client.get(
        f"/v2/cutover/{code}/RES1",
        headers=admin_auth,
    )
    assert r2.status_code == 200
    assert r2.json()["domain_code"] == code
