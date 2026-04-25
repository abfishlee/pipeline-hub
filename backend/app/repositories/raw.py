"""Repository — `raw.raw_object` / `raw.content_hash_index` / `run.ingest_job` /
`run.event_outbox`.

수집 API 가 단일 트랜잭션 안에서 호출하는 DB 연산 모음. commit 은 호출자(domain) 책임.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw import ContentHashIndex, RawObject
from app.models.run import EventOutbox, IngestJob


@dataclass(frozen=True)
class ExistingRawObject:
    """dedup 조회 결과 — raw_object 복원 시 필요한 최소 필드만."""

    raw_object_id: int
    job_id: int | None
    object_uri: str | None
    partition_date: date


# ---------------------------------------------------------------------------
# Dedup lookup
# ---------------------------------------------------------------------------
async def get_by_content_hash(session: AsyncSession, content_hash: str) -> ExistingRawObject | None:
    """전역 content_hash_index → raw_object 조회. 가장 빠른 dedup 경로 (PK 조회)."""
    idx_stmt = select(ContentHashIndex.raw_object_id, ContentHashIndex.partition_date).where(
        ContentHashIndex.content_hash == content_hash
    )
    idx_row = (await session.execute(idx_stmt)).first()
    if idx_row is None:
        return None
    raw_object_id, partition_date = idx_row

    # 실제 row 에서 job_id / object_uri 회수 (파티션 프루닝을 위해 partition_date 지정).
    raw_stmt = select(RawObject.job_id, RawObject.object_uri).where(
        RawObject.raw_object_id == raw_object_id,
        RawObject.partition_date == partition_date,
    )
    row = (await session.execute(raw_stmt)).first()
    if row is None:
        # 드문 경합 — index 는 있으나 row 미확인. None 취급.
        return None
    job_id, object_uri = row
    return ExistingRawObject(
        raw_object_id=raw_object_id,
        job_id=job_id,
        object_uri=object_uri,
        partition_date=partition_date,
    )


async def get_by_idempotency_key(
    session: AsyncSession, source_id: int, idempotency_key: str
) -> ExistingRawObject | None:
    """`(source_id, idempotency_key)` 중복 조회. 부분 인덱스 (0009) 사용."""
    stmt = (
        select(
            RawObject.raw_object_id,
            RawObject.job_id,
            RawObject.object_uri,
            RawObject.partition_date,
        )
        .where(
            RawObject.source_id == source_id,
            RawObject.idempotency_key == idempotency_key,
        )
        .order_by(RawObject.received_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return ExistingRawObject(
        raw_object_id=row[0],
        job_id=row[1],
        object_uri=row[2],
        partition_date=row[3],
    )


# ---------------------------------------------------------------------------
# Insert helpers — 단일 트랜잭션 안에서 연쇄 호출
# ---------------------------------------------------------------------------
async def insert_ingest_job(
    session: AsyncSession,
    *,
    source_id: int,
    job_type: str = "ON_DEMAND",
    status: str = "SUCCESS",
    requested_by: int | None = None,
    parameters: dict[str, Any] | None = None,
    input_count: int = 1,
    output_count: int = 1,
    error_count: int = 0,
) -> int:
    """수집 job 1건. 단일 이벤트 수집은 `SUCCESS + started=finished=now()` 로 즉시 마감.

    배치성(backfill) 수집은 별도로 PENDING→RUNNING→... 전이를 사용 (Phase 2).
    """
    now = datetime.now(UTC)
    job = IngestJob(
        source_id=source_id,
        job_type=job_type,
        status=status,
        requested_by=requested_by,
        parameters=parameters or {},
        started_at=now,
        finished_at=now,
        input_count=input_count,
        output_count=output_count,
        error_count=error_count,
    )
    session.add(job)
    await session.flush()
    return job.job_id


async def insert_raw_object(
    session: AsyncSession,
    *,
    source_id: int,
    job_id: int | None,
    object_type: str,
    content_hash: str,
    partition_date: date,
    payload_json: dict[str, Any] | None = None,
    object_uri: str | None = None,
    idempotency_key: str | None = None,
    status: str = "RECEIVED",
) -> int:
    """`raw.raw_object` insert. 파티션 라우팅은 PG 가 처리.

    pk 는 `(raw_object_id, partition_date)` — flush 후 ORM 이 raw_object_id 를 채워준다.
    """
    obj = RawObject(
        source_id=source_id,
        job_id=job_id,
        object_type=object_type,
        object_uri=object_uri,
        payload_json=payload_json,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        partition_date=partition_date,
        status=status,
    )
    session.add(obj)
    await session.flush()
    return obj.raw_object_id


async def insert_content_hash_index(
    session: AsyncSession,
    *,
    content_hash: str,
    raw_object_id: int,
    partition_date: date,
    source_id: int,
) -> None:
    """전역 unique — 동일 content_hash 동시 insert 는 PK 충돌로 실패 (트랜잭션 재시도 대상).

    Phase 1.2.7 에서는 단일 요청이 이 함수를 호출 전 `get_by_content_hash` 로
    선조회하므로 충돌은 드물다. 동시성 race 는 PK violation 을 ConflictError 로 변환.
    """
    session.add(
        ContentHashIndex(
            content_hash=content_hash,
            raw_object_id=raw_object_id,
            partition_date=partition_date,
            source_id=source_id,
        )
    )
    await session.flush()


async def insert_event_outbox(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload_json: dict[str, Any],
) -> int:
    """Outbox — 트랜잭션 정합 이벤트 발행. Phase 2 publisher 가 Redis Streams 로 이송."""
    ev = EventOutbox(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload_json=payload_json,
    )
    session.add(ev)
    await session.flush()
    return ev.event_id


# ---------------------------------------------------------------------------
# Read queries — 운영 조회용 (Phase 1.2.8)
# ---------------------------------------------------------------------------
async def get_ingest_job(session: AsyncSession, job_id: int) -> IngestJob | None:
    stmt = select(IngestJob).where(IngestJob.job_id == job_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_ingest_jobs(
    session: AsyncSession,
    *,
    source_id: int | None = None,
    status: str | None = None,
    job_type: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[IngestJob]:
    stmt = (
        select(IngestJob)
        .order_by(IngestJob.created_at.desc(), IngestJob.job_id.desc())
        .limit(limit)
        .offset(offset)
    )
    conditions = []
    if source_id is not None:
        conditions.append(IngestJob.source_id == source_id)
    if status is not None:
        conditions.append(IngestJob.status == status)
    if job_type is not None:
        conditions.append(IngestJob.job_type == job_type)
    if from_ts is not None:
        conditions.append(IngestJob.created_at >= from_ts)
    if to_ts is not None:
        conditions.append(IngestJob.created_at <= to_ts)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return list((await session.execute(stmt)).scalars().all())


async def list_raw_objects(
    session: AsyncSession,
    *,
    source_id: int | None = None,
    status: str | None = None,
    object_type: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[RawObject]:
    stmt = (
        select(RawObject)
        .order_by(RawObject.received_at.desc(), RawObject.raw_object_id.desc())
        .limit(limit)
        .offset(offset)
    )
    conditions = []
    if source_id is not None:
        conditions.append(RawObject.source_id == source_id)
    if status is not None:
        conditions.append(RawObject.status == status)
    if object_type is not None:
        conditions.append(RawObject.object_type == object_type)
    if from_ts is not None:
        conditions.append(RawObject.received_at >= from_ts)
    if to_ts is not None:
        conditions.append(RawObject.received_at <= to_ts)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return list((await session.execute(stmt)).scalars().all())


async def get_raw_object_detail(
    session: AsyncSession, raw_object_id: int, partition_date: date | None = None
) -> RawObject | None:
    """`raw_object_id` (+ 선택적 partition_date) 로 단건 조회.

    partition_date 가 주어지면 PG 가 해당 파티션만 스캔(빠름). 없으면 모든 파티션 스캔.
    PK 가 (raw_object_id, partition_date) 인 점에 주의.
    """
    stmt = select(RawObject).where(RawObject.raw_object_id == raw_object_id)
    if partition_date is not None:
        stmt = stmt.where(RawObject.partition_date == partition_date)
    stmt = stmt.limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


__all__ = [
    "ExistingRawObject",
    "get_by_content_hash",
    "get_by_idempotency_key",
    "get_ingest_job",
    "get_raw_object_detail",
    "insert_content_hash_index",
    "insert_event_outbox",
    "insert_ingest_job",
    "insert_raw_object",
    "list_ingest_jobs",
    "list_raw_objects",
]
