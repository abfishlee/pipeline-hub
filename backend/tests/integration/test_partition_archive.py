"""Phase 4.2.7 — Partition archive 라운드트립 (archive → drop → restore).

가짜 partition 을 wf 스키마에 만들고 본 모듈의 도메인 함수를 직접 호출. Object
Storage 는 in-memory mock 사용 (S3CompatibleStorage 의 put/get 시뮬).
"""

from __future__ import annotations

import gzip
import hashlib
import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.partition_archive import (
    PartitionRef,
    archive_partition,
    find_aged_partitions,
    restore_partition,
)
from app.models.ctl import PartitionArchiveLog


class _FakeStorage:
    """asyncio-친화 in-memory object storage. archive_partition 가 asyncio.run 으로 호출."""

    def __init__(self) -> None:
        self.bucket = "fake"
        self._data: dict[str, bytes] = {}

    @property
    def uri_scheme(self) -> str:
        return "fake"

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._data[key] = data
        return self.object_uri(key)

    async def get_bytes(self, key: str) -> bytes:
        return self._data[key]

    def object_uri(self, key: str) -> str:
        return f"{self.uri_scheme}://{self.bucket}/{key}"


@pytest.fixture
def fake_storage() -> _FakeStorage:
    return _FakeStorage()


@pytest.fixture
def fake_partition() -> Iterator[PartitionRef]:
    """wf 스키마에 가짜 parent + child partition 생성. 정리 시 child + parent 모두 DROP."""
    sm = get_sync_sessionmaker()
    suffix = secrets.token_hex(3)
    # 13 개월 이전인 YYYY_MM 사용 — 자동 detect 도 검증.
    parent = f"tmp_pa_{suffix}"
    partition = f"{parent}_2024_05"
    schema = "wf"
    parent_qualified = f'"{schema}"."{parent}"'
    partition_qualified = f'"{schema}"."{partition}"'
    with sm() as session:
        session.execute(
            text(
                f"CREATE TABLE {parent_qualified} ("
                f"  id BIGSERIAL, "
                f"  partition_date DATE NOT NULL, "
                f"  payload TEXT NOT NULL, "
                f"  PRIMARY KEY (id, partition_date)"
                f") PARTITION BY RANGE (partition_date)"
            )
        )
        session.execute(
            text(
                f"CREATE TABLE {partition_qualified} PARTITION OF {parent_qualified} "
                f"FOR VALUES FROM ('2024-05-01') TO ('2024-06-01')"
            )
        )
        for i in range(5):
            session.execute(
                text(f"INSERT INTO {partition_qualified} (partition_date, payload) "
                     "VALUES ('2024-05-15', :p)"),
                {"p": f"row-{i}"},
            )
        session.commit()
    yield PartitionRef(schema_name=schema, table_name=parent, partition_name=partition)
    # cleanup — 어떤 단계에서 끝났든 가능한 한 DROP. partition 이 이미 detached 면
    # standalone DROP, 아니면 parent CASCADE.
    with sm() as session:
        session.execute(text(f"DROP TABLE IF EXISTS {partition_qualified} CASCADE"))
        session.execute(
            text(f'DROP TABLE IF EXISTS "{schema}"."{partition}_restored" CASCADE')
        )
        session.execute(text(f"DROP TABLE IF EXISTS {parent_qualified} CASCADE"))
        session.execute(
            delete(PartitionArchiveLog).where(
                PartitionArchiveLog.partition_name == partition
            )
        )
        session.commit()
    dispose_sync_engine()


# ---------------------------------------------------------------------------
# 1. find_aged_partitions — wf 의 자식 detect (parent 가 raw/run/mart/audit 가 아니라
#    skip되어야 함).
# ---------------------------------------------------------------------------
def test_find_aged_partitions_skips_unknown_parents(
    fake_partition: PartitionRef,
) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        # default parent_tables 에 'wf.<parent>' 가 없으므로 발견되지 않아야 함.
        out = find_aged_partitions(
            session, cutoff=__import__("datetime").datetime(2026, 4, 1)
        )
        # raw/run/mart/audit 의 partition 만 — 본 fixture 의 partition 은 미포함.
        assert all(p.partition_name != fake_partition.partition_name for p in out)


def test_find_aged_partitions_with_custom_parent(
    fake_partition: PartitionRef,
) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        from datetime import datetime as _dt

        out = find_aged_partitions(
            session,
            cutoff=_dt(2026, 4, 1),
            parent_tables=((fake_partition.schema_name, fake_partition.table_name),),
        )
        names = [p.partition_name for p in out]
        assert fake_partition.partition_name in names


# ---------------------------------------------------------------------------
# 2. archive_partition — copy → DETACH → DROP + log + checksum
# ---------------------------------------------------------------------------
def test_archive_partition_roundtrip(
    fake_partition: PartitionRef, fake_storage: _FakeStorage
) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        stats = archive_partition(
            session,
            ref=fake_partition,
            object_storage=fake_storage,
        )
    # log row.
    sm2 = get_sync_sessionmaker()
    with sm2() as session:
        log = (
            session.query(PartitionArchiveLog)
            .filter(PartitionArchiveLog.archive_id == stats.archive_id)
            .one()
        )
        assert log.status == "DROPPED"
        assert log.row_count == 5
        assert log.byte_size > 0
        assert log.checksum
        assert log.object_uri.startswith("fake://fake/archive/2024/05/")
        # partition 실제로 사라졌는지 — pg_class lookup.
        gone = session.execute(
            text(
                "SELECT COUNT(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :ns AND c.relname = :rel"
            ),
            {"ns": fake_partition.schema_name, "rel": fake_partition.partition_name},
        ).scalar_one()
        assert gone == 0

    # Object Storage payload 가 5 row.
    payload_key = stats.object_uri.split("//", 1)[1].split("/", 1)[1]
    payload = fake_storage._data[payload_key]
    assert hashlib.sha256(payload).hexdigest() == stats.checksum
    decompressed = gzip.decompress(payload).splitlines()
    assert len(decompressed) == 5


# ---------------------------------------------------------------------------
# 3. restore_partition — Object Storage → 복원 테이블 + 같은 row count
# ---------------------------------------------------------------------------
def test_restore_partition_creates_restored_table(
    fake_partition: PartitionRef, fake_storage: _FakeStorage
) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        stats = archive_partition(
            session, ref=fake_partition, object_storage=fake_storage
        )
    with sm() as session:
        target = restore_partition(
            session, archive_id=stats.archive_id, object_storage=fake_storage
        )
    expected = f'"{fake_partition.schema_name}"."{fake_partition.partition_name}_restored"'
    assert target == expected
    with sm() as session:
        count = session.execute(text(f"SELECT COUNT(*) FROM {target}")).scalar_one()
        assert count == 5
        log = (
            session.query(PartitionArchiveLog)
            .filter(PartitionArchiveLog.archive_id == stats.archive_id)
            .one()
        )
        assert log.status == "RESTORED"
        assert log.restored_at is not None
        assert log.restored_to == target


# ---------------------------------------------------------------------------
# 4. checksum mismatch 시 restore 거부
# ---------------------------------------------------------------------------
def test_restore_rejects_on_checksum_mismatch(
    fake_partition: PartitionRef, fake_storage: _FakeStorage
) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        stats = archive_partition(
            session, ref=fake_partition, object_storage=fake_storage
        )
    # 페이로드를 변조 — 같은 key 의 데이터 임의 변경.
    payload_key = stats.object_uri.split("//", 1)[1].split("/", 1)[1]
    fake_storage._data[payload_key] = b"corrupted"

    with sm() as session, pytest.raises(ValueError, match="checksum mismatch"):
        restore_partition(
            session, archive_id=stats.archive_id, object_storage=fake_storage
        )
