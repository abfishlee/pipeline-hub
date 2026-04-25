"""각 노드 happy-path + edge cases (Phase 3.2.2).

실 PG 의존. 미가동 시 skip. 6 노드 + sql_transform 위험 SQL 거부 + dq_check 실패 분기.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import delete, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.nodes import NodeContext, get_node_runner
from app.models.ctl import DataSource
from app.models.dq import QualityResult
from app.models.raw import RawObject
from app.models.run import EventOutbox

EXT_SCHEMA = "wf"


@pytest.fixture
def cleanup_sandbox() -> Iterator[list[str]]:
    """생성한 sandbox 테이블 (`wf.tmp_*`) DROP."""
    tables: list[str] = []
    yield tables
    if not tables:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in tables:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        session.commit()
    dispose_sync_engine()


@pytest.fixture
def cleanup_quality_results() -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(QualityResult).where(QualityResult.quality_result_id.in_(ids)))
        session.commit()


def _ctx(session: object, *, node_key: str = "T", pipeline_run_id: int = 9_999_001) -> NodeContext:
    return NodeContext(
        session=session,  # type: ignore[arg-type]
        pipeline_run_id=pipeline_run_id,
        node_run_id=pipeline_run_id,  # 테스트에선 동일 값 OK.
        node_key=node_key,
        user_id=None,
    )


# ---------------------------------------------------------------------------
# 1. SOURCE_API
# ---------------------------------------------------------------------------
def test_source_api_reads_recent_raw_objects() -> None:
    sm = get_sync_sessionmaker()
    code = f"IT-NDA-{secrets.token_hex(4).upper()}"
    pdate = date(2026, 4, 25)

    with sm() as session:
        # source 시드.
        ds = DataSource(
            source_code=code,
            source_name="node IT",
            source_type="API",
            is_active=True,
            config_json={},
        )
        session.add(ds)
        session.commit()
        # raw_object 3건 시드.
        raw_ids: list[int] = []
        for i in range(3):
            ro = RawObject(
                source_id=ds.source_id,
                object_type="JSON",
                payload_json={"i": i, "name": f"row-{i}"},
                content_hash=f"h-{secrets.token_hex(8)}",
                partition_date=pdate,
                status="RECEIVED",
            )
            session.add(ro)
            session.flush()
            raw_ids.append(ro.raw_object_id)
        session.commit()

    runner = get_node_runner("SOURCE_API")
    with sm() as session:
        out = runner.run(_ctx(session), {"source_code": code, "limit": 10})
    assert out.status == "success"
    assert out.row_count == 3
    assert all("payload_json" in r for r in out.payload["rows"])

    # cleanup
    with sm() as session:
        session.execute(delete(RawObject).where(RawObject.raw_object_id.in_(raw_ids)))
        session.execute(delete(DataSource).where(DataSource.source_code == code))
        session.commit()


# ---------------------------------------------------------------------------
# 2. SQL_TRANSFORM happy path — sandbox 테이블 생성
# ---------------------------------------------------------------------------
def test_sql_transform_creates_sandbox_table_with_count(
    cleanup_sandbox: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    runner = get_node_runner("SQL_TRANSFORM")
    safe = secrets.token_hex(4)
    output = f"wf.tmp_run_99999_test_{safe}"
    cleanup_sandbox.append(output)

    with sm() as session:
        out = runner.run(
            _ctx(session, node_key=f"sql_{safe}"),
            {
                "sql": "SELECT 1 AS x, 'a' AS y",  # FROM 없는 SELECT 는 막혀야 — 다른 케이스로
            },
        )
    # FROM 이 없으니 fail (validator) → status='failed'
    assert out.status == "failed"
    assert "validation" in (out.error_message or "")

    # 정상 SELECT — mart.standard_code 가 비어 있을 수 있어 wf.workflow_definition 사용.
    with sm() as session:
        out2 = runner.run(
            _ctx(session, node_key=f"sql_ok_{safe}"),
            {
                "sql": "SELECT workflow_id, name FROM wf.workflow_definition LIMIT 5",
                "output_table": output,
            },
        )
        session.commit()
    assert out2.status == "success"
    assert out2.payload["output_table"] == output

    # 테이블 존재 확인.
    with sm() as session:
        exists = (
            session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": "wf", "t": output.split(".", 1)[1]},
            ).first()
            is not None
        )
    assert exists


# ---------------------------------------------------------------------------
# 3. SQL_TRANSFORM 위험 SQL 거부
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_sql",
    [
        "DROP TABLE mart.standard_code",
        "SELECT pg_read_file('/etc/passwd') FROM mart.standard_code LIMIT 1",
        "SELECT * FROM pg_catalog.pg_tables",
        "DELETE FROM mart.standard_code WHERE std_code = 'X'",
        "COPY mart.standard_code TO '/tmp/x.csv'",
    ],
)
def test_sql_transform_rejects_dangerous_sql(bad_sql: str) -> None:
    sm = get_sync_sessionmaker()
    runner = get_node_runner("SQL_TRANSFORM")
    with sm() as session:
        out = runner.run(_ctx(session), {"sql": bad_sql, "materialize": False})
    assert out.status == "failed"
    assert (out.error_message or "").startswith("sql validation failed")


# ---------------------------------------------------------------------------
# 4. DEDUP — 같은 key 그룹 1행만 보존
# ---------------------------------------------------------------------------
def test_dedup_creates_table_keeping_first_per_key(
    cleanup_sandbox: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dedup_src_{safe}"
    out_table = f"wf.tmp_run_99999_dedup_{safe}"
    cleanup_sandbox.extend([src, out_table])

    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (k INT, v TEXT)"))
        session.execute(
            text(f"INSERT INTO {src} VALUES (1,'a'), (1,'b'), (2,'c'), (2,'d'), (3,'e')")
        )
        session.commit()

    runner = get_node_runner("DEDUP")
    with sm() as session:
        out = runner.run(
            _ctx(session, node_key=f"dedup_{safe}"),
            {
                "input_table": src,
                "key_columns": ["k"],
                "output_table": out_table,
            },
        )
        session.commit()

    assert out.status == "success"
    assert out.row_count == 3  # k 값 3개

    with sm() as session:
        unique_keys = session.execute(
            text(f"SELECT COUNT(DISTINCT k) FROM {out_table}")
        ).scalar_one()
    assert unique_keys == 3


# ---------------------------------------------------------------------------
# 5. DQ_CHECK happy + failure
# ---------------------------------------------------------------------------
def test_dq_check_passes_when_assertions_satisfied(
    cleanup_sandbox: list[str],
    cleanup_quality_results: list[int],
) -> None:
    sm = get_sync_sessionmaker()
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dq_pass_{safe}"
    cleanup_sandbox.append(src)

    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT, name TEXT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1,'a'), (2,'b'), (3,'c')"))
        session.commit()

    runner = get_node_runner("DQ_CHECK")
    with sm() as session:
        out = runner.run(
            _ctx(session, node_key=f"dq_{safe}"),
            {
                "input_table": src,
                "assertions": [
                    {"kind": "row_count_min", "min": 2},
                    {"kind": "null_pct_max", "column": "name", "max_pct": 10.0},
                    {"kind": "unique_columns", "columns": ["id"]},
                ],
                "severity": "ERROR",
            },
        )
        session.commit()

        # quality_result 적재 — 3건, 모두 passed.
        rows = session.execute(
            text("SELECT * FROM dq.quality_result WHERE target_table = :t"),
            {"t": src},
        ).all()
        for r in rows:
            cleanup_quality_results.append(r.quality_result_id)
    assert out.status == "success"
    assert out.row_count == 3
    assert len(rows) == 3
    assert all(r.passed for r in rows)


def test_dq_check_fails_when_row_count_too_low(
    cleanup_sandbox: list[str],
    cleanup_quality_results: list[int],
) -> None:
    sm = get_sync_sessionmaker()
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dq_fail_{safe}"
    cleanup_sandbox.append(src)

    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1), (2)"))
        session.commit()

    runner = get_node_runner("DQ_CHECK")
    with sm() as session:
        out = runner.run(
            _ctx(session, node_key=f"dq_fail_{safe}"),
            {
                "input_table": src,
                "assertions": [{"kind": "row_count_min", "min": 100}],
                "severity": "ERROR",
            },
        )
        session.commit()
        rows = session.execute(
            text("SELECT * FROM dq.quality_result WHERE target_table = :t"),
            {"t": src},
        ).all()
        for r in rows:
            cleanup_quality_results.append(r.quality_result_id)
    assert out.status == "failed"
    assert out.payload["failed_count"] == 1
    assert len(rows) == 1
    assert rows[0].passed is False


# ---------------------------------------------------------------------------
# 6. LOAD_MASTER — sandbox → mart.standard_code UPSERT
# ---------------------------------------------------------------------------
def test_load_master_upserts_into_mart(
    cleanup_sandbox: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    safe = secrets.token_hex(4)
    src = f"wf.tmp_lm_{safe}"
    cleanup_sandbox.append(src)

    code = f"IT-LM-{safe.upper()}"

    with sm() as session:
        session.execute(
            text(
                f"CREATE TABLE {src} ("
                f"  std_code TEXT, "
                f"  category_lv1 TEXT, "
                f"  item_name_ko TEXT"
                f")"
            )
        )
        session.execute(
            text(f"INSERT INTO {src} VALUES " f"(:c, '과일', '테스트사과')"),
            {"c": code},
        )
        session.commit()

    runner = get_node_runner("LOAD_MASTER")
    with sm() as session:
        out = runner.run(
            _ctx(session, node_key=f"lm_{safe}"),
            {
                "source_table": src,
                "target_table": "mart.standard_code",
                "key_columns": ["std_code"],
                "update_columns": ["category_lv1", "item_name_ko"],
            },
        )
        session.commit()

    assert out.status == "success"
    assert out.row_count >= 1

    # 정리: 적재된 std_code 제거.
    with sm() as session:
        session.execute(
            text("DELETE FROM mart.standard_code WHERE std_code = :c"),
            {"c": code},
        )
        session.commit()


# ---------------------------------------------------------------------------
# 7. NOTIFY — outbox 적재만
# ---------------------------------------------------------------------------
def test_notify_inserts_outbox_only() -> None:
    sm = get_sync_sessionmaker()
    runner = get_node_runner("NOTIFY")
    safe = secrets.token_hex(4)

    with sm() as session:
        out = runner.run(
            _ctx(session, node_key=f"notify_{safe}", pipeline_run_id=9_999_888),
            {
                "channel": "slack",
                "target": "#alerts-it",
                "level": "WARN",
                "subject": f"IT {safe}",
                "body": "test body",
            },
        )
        session.commit()

    assert out.status == "success"
    assert out.payload["queued"] is True

    with sm() as session:
        rows = (
            session.execute(
                delete(EventOutbox)
                .where(EventOutbox.event_type == "notify.requested")
                .where(EventOutbox.aggregate_id == "9999888")
                .returning(EventOutbox.event_id)
            )
            .scalars()
            .all()
        )
        session.commit()
    assert len(list(rows)) >= 1


# ---------------------------------------------------------------------------
# 8. NOOP (등록 회귀 — Phase 3.2.1 가 등록되어 있는지)
# ---------------------------------------------------------------------------
def test_noop_runner_is_registered() -> None:
    runner = get_node_runner("NOOP")
    sm = get_sync_sessionmaker()
    with sm() as session:
        out = runner.run(_ctx(session), {})
    assert out.status == "success"
    assert out.payload.get("noop") is True
