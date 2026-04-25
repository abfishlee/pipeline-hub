"""HTTP 경계 — `/v1/raw-objects` (원천 데이터 조회).

권한: ADMIN 또는 OPERATOR. 상세 조회 시 object_uri 가 있으면 presigned GET URL 발급.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query

from app.core import errors as app_errors
from app.deps import SessionDep, require_roles
from app.integrations.object_storage import ObjectStorage, get_object_storage
from app.models.raw import RawObject
from app.repositories import raw as raw_repo
from app.schemas.raw_objects import (
    ObjectType,
    RawObjectDetail,
    RawObjectSummary,
    RawStatus,
)


def _storage_dep() -> ObjectStorage:
    return get_object_storage()


StorageDep = Annotated[ObjectStorage, Depends(_storage_dep)]


router = APIRouter(
    prefix="/v1/raw-objects",
    tags=["raw-objects"],
    dependencies=[Depends(require_roles("ADMIN", "OPERATOR"))],
)


# Presigned URL 기본 만료 시간.
_PRESIGNED_GET_TTL_SEC = 300


def _summary(row: RawObject) -> RawObjectSummary:
    return RawObjectSummary(
        raw_object_id=row.raw_object_id,
        source_id=row.source_id,
        job_id=row.job_id,
        object_type=row.object_type,
        status=row.status,
        received_at=row.received_at,
        partition_date=row.partition_date,
        has_inline_payload=row.payload_json is not None,
        object_uri_present=row.object_uri is not None,
    )


def _key_from_uri(object_uri: str, expected_bucket: str) -> str | None:
    """`s3://bucket/key` 또는 `nos://bucket/key` → `key` 추출.

    bucket 이 일치하지 않으면 None (다른 환경 출처) — presigned 발급 안 함.
    """
    parsed = urlparse(object_uri)
    if parsed.scheme not in ("s3", "nos"):
        return None
    if parsed.netloc != expected_bucket:
        return None
    return parsed.path.lstrip("/")


@router.get("", response_model=list[RawObjectSummary])
async def list_raw(
    session: SessionDep,
    source_id: Annotated[int | None, Query(ge=1)] = None,
    status: RawStatus | None = Query(default=None),
    object_type: ObjectType | None = Query(default=None),
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RawObjectSummary]:
    rows = await raw_repo.list_raw_objects(
        session,
        source_id=source_id,
        status=status,
        object_type=object_type,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        offset=offset,
    )
    return [_summary(r) for r in rows]


@router.get("/{raw_object_id}", response_model=RawObjectDetail)
async def get_raw_detail(
    raw_object_id: int,
    session: SessionDep,
    storage: StorageDep,
    partition_date: Annotated[
        date | None,
        Query(description="조회할 파티션 일자 (YYYY-MM-DD). 미지정 시 모든 파티션 스캔."),
    ] = None,
) -> RawObjectDetail:
    row = await raw_repo.get_raw_object_detail(session, raw_object_id, partition_date)
    if row is None:
        raise app_errors.NotFoundError(f"raw_object {raw_object_id} not found")

    download_url: str | None = None
    if row.object_uri:
        key = _key_from_uri(row.object_uri, storage.bucket)
        if key is not None:
            download_url = await storage.presigned_get(key, expires_sec=_PRESIGNED_GET_TTL_SEC)

    return RawObjectDetail(
        raw_object_id=row.raw_object_id,
        source_id=row.source_id,
        job_id=row.job_id,
        object_type=row.object_type,
        status=row.status,
        content_hash=row.content_hash,
        idempotency_key=row.idempotency_key,
        received_at=row.received_at,
        partition_date=row.partition_date,
        payload_json=row.payload_json,
        object_uri=row.object_uri,
        download_url=download_url,
    )
