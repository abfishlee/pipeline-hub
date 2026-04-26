"""Partition archive 도메인 (Phase 4.2.7).

흐름 (`run_archive_for_partition` 1건 단위):
  1. ctl.partition_archive_log INSERT (status=PENDING).
  2. partition row → JSONL → Object Storage `archive/<yyyy>/<mm>/<schema>.<table>.<part>.jsonl.gz`.
     row_count / byte_size / checksum (sha256) 기록 → status=COPIED.
  3. ALTER TABLE parent DETACH PARTITION → status=DETACHED.
  4. DROP TABLE partition → status=DROPPED.

복원 (`restore_partition`):
  - Object Storage 의 jsonl.gz → 임시 테이블 (`<schema>.<part_name>_restored`) 로 적재.
  - status=RESTORED + restored_at + restored_to 기록.

Phase 4.2.7 PoC 한정:
  - 파티션 row 가 *수억* 단위로 늘어나면 single jsonl 압축은 메모리 부담. 운영 시
    chunk 단위 streaming + parallel upload 검토 (ADR 후속).
  - 검증은 row_count + sha256 까지. 복원 후 row 비교는 운영자 책임.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PartitionRef:
    schema_name: str
    table_name: str  # parent table (e.g., 'raw_object')
    partition_name: str  # child (e.g., 'raw_object_2024_05')


@dataclass(slots=True, frozen=True)
class ArchiveStats:
    archive_id: int
    row_count: int
    byte_size: int
    checksum: str
    object_uri: str


def find_aged_partitions(
    session: Session,
    *,
    cutoff: datetime,
    parent_tables: tuple[tuple[str, str], ...] = (
        ("raw", "raw_object"),
        ("run", "pipeline_run"),
        ("mart", "price_fact"),
        ("audit", "access_log"),
    ),
) -> list[PartitionRef]:
    """parent_tables 의 child partition 중 *이름의 YYYY_MM 가 cutoff 이전* 인 것 반환.

    naming convention: `<parent>_YYYY_MM` (`raw_object_2024_05`).
    pg_inherits + pg_class 로 child 목록 조회.
    """
    out: list[PartitionRef] = []
    cutoff_year = cutoff.year
    cutoff_month = cutoff.month
    for schema, parent in parent_tables:
        rows = session.execute(
            text(
                "SELECT child.relname AS partition_name "
                "FROM pg_inherits i "
                "JOIN pg_class child  ON child.oid  = i.inhrelid "
                "JOIN pg_class par    ON par.oid    = i.inhparent "
                "JOIN pg_namespace n  ON n.oid      = par.relnamespace "
                "WHERE n.nspname = :ns AND par.relname = :par "
                "ORDER BY child.relname"
            ),
            {"ns": schema, "par": parent},
        ).all()
        for r in rows:
            name = str(r.partition_name)
            try:
                # parse_<parent>_YYYY_MM
                suffix = name.replace(f"{parent}_", "", 1)
                year_str, month_str = suffix.split("_", 1)
                y = int(year_str)
                m = int(month_str)
            except (ValueError, AttributeError):
                continue
            # YYYY_MM < cutoff (= year/month < cutoff). 같은 달은 보존.
            age = (cutoff_year - y) * 12 + (cutoff_month - m)
            if age >= 13:
                out.append(PartitionRef(schema, parent, name))
    return out


def _partition_qualified(ref: PartitionRef) -> str:
    return f'"{ref.schema_name}"."{ref.partition_name}"'


def _iter_rows_as_dicts(
    session: Session, *, qualified: str, chunk_size: int = 5_000
) -> Iterator[list[dict[str, Any]]]:
    """파티션의 모든 row 를 dict chunk 로 yield.

    PoC 단계는 in-memory fetchmany — server-side cursor 가 후속 INSERT/UPDATE 트랜잭션
    과 간섭. 파티션이 *수억 row* 로 커지면 별도 트랜잭션 + COPY TO STDOUT 으로 교체
    (ADR § 6 회수 조건).
    """
    res = session.execute(text(f"SELECT * FROM {qualified}"))
    while True:
        batch = res.fetchmany(chunk_size)
        if not batch:
            break
        yield [dict(r._mapping) for r in batch]


def _serialize_to_gzip_jsonl(
    rows_iter: Iterator[list[dict[str, Any]]],
) -> tuple[bytes, int, str]:
    """rows → gzipped JSONL bytes + row_count + sha256(of compressed bytes)."""
    buf = io.BytesIO()
    row_count = 0
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        for batch in rows_iter:
            for row in batch:
                gz.write((json.dumps(row, default=str) + "\n").encode("utf-8"))
                row_count += 1
    payload = buf.getvalue()
    checksum = hashlib.sha256(payload).hexdigest()
    return payload, row_count, checksum


def archive_partition(
    session: Session,
    *,
    ref: PartitionRef,
    object_storage: Any,
    bucket_prefix: str = "archive",
    archived_by: int | None = None,
) -> ArchiveStats:
    """1 partition 의 archive 전체 흐름 — copy → checksum → detach → drop.

    `object_storage` 는 sync put_bytes 인터페이스를 가진 객체. 본 함수는 sync
    session 위에서 동작 — Airflow 작업이 직접 호출.
    """
    # 1) 로그 row.
    log_id_row = session.execute(
        text(
            "INSERT INTO ctl.partition_archive_log "
            "(schema_name, table_name, partition_name, status, archived_by) "
            "VALUES (:s, :t, :p, 'PENDING', :u) "
            "ON CONFLICT (schema_name, table_name, partition_name) "
            "DO UPDATE SET status = 'PENDING', updated_at = now(), "
            "              error_message = NULL "
            "RETURNING archive_id"
        ),
        {"s": ref.schema_name, "t": ref.table_name, "p": ref.partition_name, "u": archived_by},
    ).scalar_one()
    archive_id = int(log_id_row)
    qualified = _partition_qualified(ref)

    # 2) row → gzip JSONL + checksum.
    payload, row_count, checksum = _serialize_to_gzip_jsonl(
        _iter_rows_as_dicts(session, qualified=qualified)
    )
    byte_size = len(payload)
    yyyy = ref.partition_name.split("_")[-2]
    mm = ref.partition_name.split("_")[-1]
    key = (
        f"{bucket_prefix}/{yyyy}/{mm}/{ref.schema_name}.{ref.partition_name}.jsonl.gz"
    )

    # 3) Object Storage put — protocol 의 어떤 sync helper 호출.
    object_uri = _put_bytes(object_storage, key=key, data=payload)

    # 4) 로그 업데이트.
    session.execute(
        text(
            "UPDATE ctl.partition_archive_log SET "
            "  row_count = :rc, byte_size = :bs, checksum = :cs, "
            "  object_uri = :u, status = 'COPIED', archived_at = now(), updated_at = now() "
            "WHERE archive_id = :id"
        ),
        {"rc": row_count, "bs": byte_size, "cs": checksum, "u": object_uri, "id": archive_id},
    )
    session.commit()

    # 5) DETACH PARTITION + DROP TABLE.
    try:
        session.execute(
            text(
                f'ALTER TABLE "{ref.schema_name}"."{ref.table_name}" '
                f'DETACH PARTITION "{ref.schema_name}"."{ref.partition_name}";'
            )
        )
        session.execute(
            text(
                "UPDATE ctl.partition_archive_log SET status='DETACHED', updated_at=now() "
                "WHERE archive_id=:id"
            ),
            {"id": archive_id},
        )
        session.commit()

        session.execute(
            text(f'DROP TABLE "{ref.schema_name}"."{ref.partition_name}";')
        )
        session.execute(
            text(
                "UPDATE ctl.partition_archive_log SET status='DROPPED', updated_at=now() "
                "WHERE archive_id=:id"
            ),
            {"id": archive_id},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        session.execute(
            text(
                "UPDATE ctl.partition_archive_log SET status='FAILED', "
                "error_message=:e, updated_at=now() WHERE archive_id=:id"
            ),
            {"e": f"{type(exc).__name__}: {exc}"[:2000], "id": archive_id},
        )
        session.commit()
        raise

    return ArchiveStats(
        archive_id=archive_id,
        row_count=row_count,
        byte_size=byte_size,
        checksum=checksum,
        object_uri=object_uri,
    )


def restore_partition(
    session: Session,
    *,
    archive_id: int,
    object_storage: Any,
    target_table: str | None = None,
    restored_by: int | None = None,
) -> str:
    """archive_id 의 데이터를 임시 테이블로 복원. 반환값은 복원된 테이블 이름.

    target_table 이 None 이면 `<schema>.<partition_name>_restored` 사용.
    """
    row = session.execute(
        text(
            "SELECT schema_name, table_name, partition_name, object_uri, checksum "
            "FROM ctl.partition_archive_log WHERE archive_id = :id"
        ),
        {"id": archive_id},
    ).one_or_none()
    if row is None:
        raise ValueError(f"archive {archive_id} not found")
    schema_name = row.schema_name
    partition_name = row.partition_name
    object_uri = row.object_uri
    if not object_uri:
        raise ValueError(f"archive {archive_id} has no object_uri")

    target = target_table or f'"{schema_name}"."{partition_name}_restored"'

    # 1) Object Storage 에서 다운로드.
    payload = _get_bytes(object_storage, object_uri=object_uri)
    if hashlib.sha256(payload).hexdigest() != row.checksum:
        raise ValueError("checksum mismatch on restore")

    # 2) 같은 컬럼 구조의 임시 테이블 생성 — parent (table_name) 의 컬럼을 따라 만듦.
    parent_qualified = f'"{schema_name}"."{row.table_name}"'
    session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {target} "
            f"(LIKE {parent_qualified} INCLUDING DEFAULTS INCLUDING IDENTITY)"
        )
    )

    # 3) 압축 해제 + INSERT.
    decompressed = gzip.decompress(payload)
    inserted = 0
    cols_template: list[str] = []
    placeholders: list[str] = []
    for line in decompressed.splitlines():
        if not line:
            continue
        record: dict[str, Any] = json.loads(line)
        if not cols_template:
            cols_template = list(record.keys())
            placeholders = [f":{c}" for c in cols_template]
        col_list = ", ".join(f'"{c}"' for c in cols_template)
        val_list = ", ".join(placeholders)
        session.execute(
            text(f"INSERT INTO {target} ({col_list}) VALUES ({val_list})"),
            record,
        )
        inserted += 1

    session.execute(
        text(
            "UPDATE ctl.partition_archive_log SET "
            " status='RESTORED', restored_at=now(), restored_to=:t, "
            " restored_by=:u, updated_at=now() WHERE archive_id=:id"
        ),
        {"t": target, "u": restored_by, "id": archive_id},
    )
    session.commit()
    logger.info("partition_archive.restored archive_id=%s rows=%s target=%s",
                archive_id, inserted, target)
    return target


# ---------------------------------------------------------------------------
# Object storage adapters — sync put_bytes/get_bytes by URI
# ---------------------------------------------------------------------------
def _put_bytes(object_storage: Any, *, key: str, data: bytes) -> str:
    """async put → sync wrapper (asyncio.run). 실 환경에선 sync helper 추가 권장."""
    import asyncio

    async def _do() -> str:
        await object_storage.put(key, data, content_type="application/gzip")
        return str(object_storage.object_uri(key))

    return asyncio.run(_do())


def _get_bytes(object_storage: Any, *, object_uri: str) -> bytes:
    """object_uri (s3://bucket/key 또는 nos://bucket/key) → bytes."""
    import asyncio

    # uri → key 만 추출.
    _, _, rest = object_uri.partition("://")
    _bucket, _, key = rest.partition("/")

    async def _do() -> bytes:
        return bytes(await object_storage.get_bytes(key))

    return asyncio.run(_do())


__all__ = [
    "ArchiveStats",
    "PartitionRef",
    "archive_partition",
    "find_aged_partitions",
    "restore_partition",
]
