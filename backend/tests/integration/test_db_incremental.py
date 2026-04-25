"""DB-to-DB 증분 수집 통합 테스트 — 실 PG, 같은 클러스터 다른 schema 를 외부 DB 로 시뮬.

같은 PG 의 `ext_test` schema 에 임시 source 테이블을 만들고, `pull_incremental` 가
그 테이블에서 incremental 하게 raw_object 적재 + watermark 전진하는 흐름을 검증.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text

from app.config import get_settings
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.db_incremental import pull_incremental
from app.integrations.sourcedb import SourceDbConfig, SqlAlchemySourceDb
from app.models.ctl import DataSource
from app.models.raw import ContentHashIndex, RawObject
from app.models.run import EventOutbox, IngestJob

EXT_SCHEMA = "ext_test_db_incremental"


def _parse_pg_url(database_url: str) -> dict[str, str | int]:
    """`postgresql+(asyncpg|psycopg)://user:pw@host:port/db` → host/port/db/user/pw."""
    # 단순 파싱 — 운영 URL 모양에만 맞춤. tests/integration/conftest 의 _sync_url 와 같은 가정.
    rest = database_url.split("://", 1)[1]
    auth, host_db = rest.split("@", 1)
    user, pw = auth.split(":", 1)
    host_port, db = host_db.split("/", 1)
    host, port = host_port.split(":")
    return {
        "user": user,
        "password": pw,
        "host": host,
        "port": int(port),
        "database": db.split("?")[0],
    }


@pytest.fixture
def ext_table() -> Iterator[str]:
    """외부 source 테이블 시뮬 — 같은 PG 의 별도 schema. 테스트 종료 시 통째로 DROP."""
    sm = get_sync_sessionmaker()
    table_name = f"src_{secrets.token_hex(4)}"
    qualified = f'"{EXT_SCHEMA}"."{table_name}"'
    with sm() as session:
        session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{EXT_SCHEMA}"'))
        session.execute(
            text(
                f"CREATE TABLE {qualified} ("
                f"  id BIGINT PRIMARY KEY,"
                f"  payload TEXT NOT NULL,"
                f"  observed_at TIMESTAMPTZ NOT NULL"
                f")"
            )
        )
        session.commit()
    yield table_name
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {qualified} CASCADE"))
        session.commit()
    dispose_sync_engine()


def _seed_ext_rows(table_name: str, n: int, *, base_dt: datetime) -> None:
    sm = get_sync_sessionmaker()
    qualified = f'"{EXT_SCHEMA}"."{table_name}"'
    with sm() as session:
        for i in range(n):
            session.execute(
                text(
                    f"INSERT INTO {qualified} (id, payload, observed_at) "
                    f"VALUES (:id, :payload, :ts)"
                ),
                {
                    "id": i + 1,
                    "payload": f"row-{i + 1}",
                    "ts": base_dt + timedelta(seconds=i),
                },
            )
        session.commit()


@pytest.fixture
def ext_source(ext_table: str) -> Iterator[DataSource]:
    """ctl.data_source 등록 — config_json 에 외부 DB 접속 정보."""
    settings = get_settings()
    pg = _parse_pg_url(settings.database_url)
    code = f"IT-DB-{secrets.token_hex(4).upper()}"
    sm = get_sync_sessionmaker()
    with sm() as session:
        ds = DataSource(
            source_code=code,
            source_name="db_incremental IT",
            source_type="DB",
            is_active=True,
            config_json={
                "driver": "postgresql",
                "host": pg["host"],
                "port": pg["port"],
                "database": pg["database"],
                "schema": EXT_SCHEMA,
                "table": ext_table,
                "cursor_column": "id",
                "user": pg["user"],
                "password": pg["password"],
            },
            watermark={},
        )
        session.add(ds)
        session.commit()
        session.refresh(ds)
        source_id = ds.source_id
    yield ds
    # cleanup — raw 이력 + outbox + job + source.
    with sm() as session:
        session.execute(
            delete(EventOutbox).where(EventOutbox.payload_json["source_code"].astext == code)
        )
        session.execute(delete(ContentHashIndex).where(ContentHashIndex.source_id == source_id))
        session.execute(delete(RawObject).where(RawObject.source_id == source_id))
        session.execute(delete(IngestJob).where(IngestJob.source_id == source_id))
        session.execute(delete(DataSource).where(DataSource.source_id == source_id))
        session.commit()


# ---------------------------------------------------------------------------
# 1. 첫 fetch — 모든 row 를 raw_object 로 적재 + watermark 전진
# ---------------------------------------------------------------------------
def test_initial_pull_inserts_all_and_advances_watermark(
    ext_source: DataSource, ext_table: str
) -> None:
    base_dt = datetime.now(UTC) - timedelta(minutes=5)
    _seed_ext_rows(ext_table, n=3, base_dt=base_dt)

    sm = get_sync_sessionmaker()
    with sm() as session:
        outcome = pull_incremental(session, source_code=ext_source.source_code, batch_size=100)
        session.commit()

    assert outcome.pulled_count == 3
    assert outcome.inserted_count == 3
    assert outcome.deduped_count == 0

    with sm() as session:
        raws = (
            session.execute(select(RawObject).where(RawObject.source_id == ext_source.source_id))
            .scalars()
            .all()
        )
        assert len(raws) == 3
        assert all(r.object_type == "DB_ROW" for r in raws)
        assert all(r.payload_json is not None and "payload" in r.payload_json for r in raws)

        events = (
            session.execute(
                select(EventOutbox).where(
                    EventOutbox.payload_json["source_code"].astext == ext_source.source_code
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 3
        assert all(e.event_type == "ingest.api.received" for e in events)
        assert all(e.payload_json.get("kind") == "db" for e in events)

        ds = session.execute(
            select(DataSource).where(DataSource.source_id == ext_source.source_id)
        ).scalar_one()
        assert ds.watermark.get("last_cursor") == "3"
        assert ds.watermark.get("last_count") == 3
        assert ds.watermark.get("last_run_at")


# ---------------------------------------------------------------------------
# 2. 두 번째 호출 (새 row 없음) — 0 fetch, watermark 그대로
# ---------------------------------------------------------------------------
def test_second_pull_with_no_new_rows_is_noop(ext_source: DataSource, ext_table: str) -> None:
    _seed_ext_rows(ext_table, n=2, base_dt=datetime.now(UTC) - timedelta(minutes=5))
    sm = get_sync_sessionmaker()

    with sm() as session:
        first = pull_incremental(session, source_code=ext_source.source_code, batch_size=100)
        session.commit()
    assert first.inserted_count == 2

    # 두 번째 — 새 row 없음.
    with sm() as session:
        second = pull_incremental(session, source_code=ext_source.source_code, batch_size=100)
        session.commit()

    assert second.pulled_count == 0
    assert second.inserted_count == 0
    assert second.deduped_count == 0

    with sm() as session:
        raws = (
            session.execute(select(RawObject).where(RawObject.source_id == ext_source.source_id))
            .scalars()
            .all()
        )
        assert len(raws) == 2  # 첫 호출분 그대로.


# ---------------------------------------------------------------------------
# 3. 새 row 추가 후 호출 — 신규만 적재 (incremental 정확성)
# ---------------------------------------------------------------------------
def test_third_pull_after_insert_picks_up_only_new_rows(
    ext_source: DataSource, ext_table: str
) -> None:
    base = datetime.now(UTC) - timedelta(minutes=10)
    _seed_ext_rows(ext_table, n=2, base_dt=base)

    sm = get_sync_sessionmaker()
    with sm() as session:
        pull_incremental(session, source_code=ext_source.source_code, batch_size=100)
        session.commit()

    # 외부 DB 에 새 row 2건 INSERT.
    qualified = f'"{EXT_SCHEMA}"."{ext_table}"'
    with sm() as session:
        for new_id in (10, 11):
            session.execute(
                text(
                    f"INSERT INTO {qualified} (id, payload, observed_at) "
                    f"VALUES (:id, :payload, :ts)"
                ),
                {
                    "id": new_id,
                    "payload": f"row-{new_id}",
                    "ts": datetime.now(UTC),
                },
            )
        session.commit()

    with sm() as session:
        outcome = pull_incremental(session, source_code=ext_source.source_code, batch_size=100)
        session.commit()

    assert outcome.pulled_count == 2
    assert outcome.inserted_count == 2

    with sm() as session:
        ds = session.execute(
            select(DataSource).where(DataSource.source_id == ext_source.source_id)
        ).scalar_one()
        assert ds.watermark.get("last_cursor") == "11"
        raws = (
            session.execute(select(RawObject).where(RawObject.source_id == ext_source.source_id))
            .scalars()
            .all()
        )
        assert len(raws) == 4  # 2(first) + 2(new)


# ---------------------------------------------------------------------------
# 4. SqlAlchemySourceDb 단독 호출 — adapter 자체 회귀
# ---------------------------------------------------------------------------
def test_sqlalchemy_source_db_returns_rows_in_cursor_order(
    ext_source: DataSource, ext_table: str
) -> None:
    _seed_ext_rows(ext_table, n=5, base_dt=datetime.now(UTC) - timedelta(minutes=1))

    config = SourceDbConfig(**ext_source.config_json)  # type: ignore[arg-type]
    connector = SqlAlchemySourceDb(config)
    try:
        batch = connector.fetch_incremental(cursor_value=None, batch_size=3)
    finally:
        connector.close()

    assert len(batch.rows) == 3
    assert [r["id"] for r in batch.rows] == [1, 2, 3]
    assert batch.max_cursor == 3
