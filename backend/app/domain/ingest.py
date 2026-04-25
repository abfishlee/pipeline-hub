"""도메인 — 수집 (Ingest).

설계 원칙 (docs/02_ARCHITECTURE.md 2.6 Outbox + docs/03_DATA_MODEL.md):
  1) content_hash / idempotency_key 2중 dedup
  2) 대용량 payload 는 Object Storage, 작은 JSON 은 DB inline
  3) 모든 성공 경로는 단일 트랜잭션으로 [ingest_job + raw_object + content_hash + outbox]
     insert + commit. 실패 시 rollback (Object Storage 에 올린 객체는 고아, 수명주기로 회수)
  4) 인증된 사용자(OPERATOR/ADMIN) 호출 전제 — audit 로그는 Phase 의 별도 미들웨어
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import errors as app_errors
from app.core import metrics
from app.core.hashing import (
    content_hash_of_json,
    normalize_idempotency_key,
    sha256_bytes,
)
from app.integrations.object_storage import ObjectStorage
from app.models.ctl import DataSource
from app.repositories import raw as raw_repo
from app.repositories import sources as sources_repo
from app.schemas.ingest import (
    INLINE_JSON_LIMIT_BYTES,
    MAX_FILE_BYTES,
    MAX_RECEIPT_BYTES,
    IngestResponse,
)


@dataclass(frozen=True)
class IngestOutcome:
    """Domain → API 경계 결과. 신규 / dedup 여부 + HTTP status 결정 소재."""

    response: IngestResponse
    created: bool  # True → API 201, False → 200 (dedup)


def _record_metrics(
    *,
    source_code: str,
    kind: str,
    created: bool,
    size_bytes: int,
) -> None:
    """수집 결과 메트릭 카운터 갱신.

    - 항상 ingest_requests_total{status=created|dedup} +1
    - dedup 일 때 ingest_dedup_total +1
    - 신규(created)일 때 ingest_bytes_total += size
    """
    status_label = "created" if created else "dedup"
    metrics.ingest_requests_total.labels(
        source_code=source_code, kind=kind, status=status_label
    ).inc()
    if not created:
        metrics.ingest_dedup_total.labels(source_code=source_code, kind=kind).inc()
    if created and size_bytes > 0:
        metrics.ingest_bytes_total.labels(source_code=source_code, kind=kind).inc(size_bytes)


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------
async def _resolve_active_source(session: AsyncSession, source_code: str) -> DataSource:
    source = await sources_repo.get_by_code(session, source_code)
    if source is None:
        raise app_errors.NotFoundError(f"data_source '{source_code}' not found")
    if not source.is_active:
        raise app_errors.PermissionError(f"data_source '{source_code}' is inactive")
    return source


def _existing_to_response(existing: raw_repo.ExistingRawObject) -> IngestResponse:
    return IngestResponse(
        raw_object_id=existing.raw_object_id,
        job_id=existing.job_id,
        dedup=True,
        object_uri=existing.object_uri,
    )


async def _dedup_check(
    session: AsyncSession,
    *,
    source_id: int,
    content_hash: str,
    idempotency_key: str | None,
) -> raw_repo.ExistingRawObject | None:
    """idempotency_key 우선 → content_hash 순."""
    if idempotency_key:
        hit = await raw_repo.get_by_idempotency_key(session, source_id, idempotency_key)
        if hit is not None:
            return hit
    return await raw_repo.get_by_content_hash(session, content_hash)


async def _persist_raw(
    session: AsyncSession,
    *,
    source_id: int,
    object_type: str,
    content_hash: str,
    idempotency_key: str | None,
    payload_json: dict[str, Any] | None,
    object_uri: str | None,
    requested_by: int | None,
    event_type: str,
    partition_date: datetime,
    ingest_parameters: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """단일 트랜잭션 insert: job + raw + hash_idx + outbox. flush 만, commit 은 호출자."""
    job_id = await raw_repo.insert_ingest_job(
        session,
        source_id=source_id,
        requested_by=requested_by,
        parameters=ingest_parameters or {},
    )
    raw_object_id = await raw_repo.insert_raw_object(
        session,
        source_id=source_id,
        job_id=job_id,
        object_type=object_type,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        partition_date=partition_date.date(),
        payload_json=payload_json,
        object_uri=object_uri,
    )
    await raw_repo.insert_content_hash_index(
        session,
        content_hash=content_hash,
        raw_object_id=raw_object_id,
        partition_date=partition_date.date(),
        source_id=source_id,
    )
    await raw_repo.insert_event_outbox(
        session,
        aggregate_type="raw_object",
        aggregate_id=str(raw_object_id),
        event_type=event_type,
        payload_json={
            "source_id": source_id,
            "raw_object_id": raw_object_id,
            "object_type": object_type,
            "content_hash": content_hash,
            "idempotency_key": idempotency_key,
            "object_uri": object_uri,
            "has_inline_payload": payload_json is not None,
            "partition_date": partition_date.date().isoformat(),
        },
    )
    return raw_object_id, job_id


# ---------------------------------------------------------------------------
# API JSON 수집
# ---------------------------------------------------------------------------
async def ingest_api(
    session: AsyncSession,
    *,
    source_code: str,
    body: dict[str, Any],
    idempotency_key_raw: str | None,
    requested_by: int | None,
    storage: ObjectStorage,
    settings: Settings,
) -> IngestOutcome:
    """JSON 본문 수집 경로.

    - inline 임계치 (64KB) 이하면 DB `payload_json` 에 인라인 저장.
    - 초과 시 Object Storage 에 저장 후 object_uri 만 DB 에.
    """
    source = await _resolve_active_source(session, source_code)
    idempotency_key = normalize_idempotency_key(idempotency_key_raw)
    content_hash = content_hash_of_json(body)

    existing = await _dedup_check(
        session,
        source_id=source.source_id,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        _record_metrics(source_code=source.source_code, kind="api", created=False, size_bytes=0)
        return IngestOutcome(response=_existing_to_response(existing), created=False)

    # inline 여부 결정 — canonical JSON 재계산 대신 길이만 측정.
    # (content_hash_of_json 은 내부적으로 canonical encode 를 이미 수행)
    import json as _json

    canonical_bytes = _json.dumps(
        body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    payload_json: dict[str, Any] | None = None
    object_uri: str | None = None
    now = datetime.now(UTC)
    if len(canonical_bytes) <= INLINE_JSON_LIMIT_BYTES:
        payload_json = body
    else:
        # Object Storage 먼저 put. 실패 시 DB 는 아직 건드리지 않음.
        from app.core import object_keys

        key = object_keys.raw_key(source.source_code, now, "json")
        object_uri = await storage.put(key, canonical_bytes, content_type="application/json")

    raw_object_id, job_id = await _persist_raw(
        session,
        source_id=source.source_id,
        object_type="JSON",
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        payload_json=payload_json,
        object_uri=object_uri,
        requested_by=requested_by,
        event_type="ingest.api.received",
        partition_date=now,
        ingest_parameters={"size_bytes": len(canonical_bytes)},
    )
    await session.commit()

    _record_metrics(
        source_code=source.source_code,
        kind="api",
        created=True,
        size_bytes=len(canonical_bytes),
    )

    return IngestOutcome(
        response=IngestResponse(
            raw_object_id=raw_object_id,
            job_id=job_id,
            dedup=False,
            object_uri=object_uri,
        ),
        created=True,
    )


# ---------------------------------------------------------------------------
# 파일 업로드
# ---------------------------------------------------------------------------
async def ingest_file(
    session: AsyncSession,
    *,
    source_code: str,
    filename: str,
    content: bytes,
    content_type: str,
    idempotency_key_raw: str | None,
    requested_by: int | None,
    storage: ObjectStorage,
    settings: Settings,
) -> IngestOutcome:
    """일반 파일 (CSV / PDF / XML 등). 항상 Object Storage 저장."""
    if len(content) > MAX_FILE_BYTES:
        raise app_errors.PayloadTooLargeError(
            f"file too large: {len(content)} bytes > {MAX_FILE_BYTES}"
        )

    source = await _resolve_active_source(session, source_code)
    idempotency_key = normalize_idempotency_key(idempotency_key_raw)
    content_hash = sha256_bytes(content)

    existing = await _dedup_check(
        session,
        source_id=source.source_id,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        _record_metrics(source_code=source.source_code, kind="file", created=False, size_bytes=0)
        return IngestOutcome(response=_existing_to_response(existing), created=False)

    # 파일 확장자 추출 (없으면 bin).
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    now = datetime.now(UTC)
    from app.core import object_keys

    try:
        key = object_keys.raw_key(source.source_code, now, ext)
    except ValueError:
        # 지원되지 않는 확장자 → bin 으로 저장.
        key = object_keys.raw_key(source.source_code, now, "bin")

    object_uri = await storage.put(key, content, content_type=content_type)

    object_type = _infer_object_type(content_type, ext)

    raw_object_id, job_id = await _persist_raw(
        session,
        source_id=source.source_id,
        object_type=object_type,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        payload_json=None,
        object_uri=object_uri,
        requested_by=requested_by,
        event_type="ingest.file.received",
        partition_date=now,
        ingest_parameters={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        },
    )
    await session.commit()

    _record_metrics(
        source_code=source.source_code,
        kind="file",
        created=True,
        size_bytes=len(content),
    )

    return IngestOutcome(
        response=IngestResponse(
            raw_object_id=raw_object_id,
            job_id=job_id,
            dedup=False,
            object_uri=object_uri,
        ),
        created=True,
    )


# ---------------------------------------------------------------------------
# 영수증 업로드 — 이미지 전용 + 10MB 상한
# ---------------------------------------------------------------------------
_RECEIPT_ALLOWED_CT = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/heic", "application/pdf"}
)


async def ingest_receipt(
    session: AsyncSession,
    *,
    source_code: str,
    filename: str,
    content: bytes,
    content_type: str,
    idempotency_key_raw: str | None,
    requested_by: int | None,
    storage: ObjectStorage,
    settings: Settings,
) -> IngestOutcome:
    if len(content) > MAX_RECEIPT_BYTES:
        raise app_errors.PayloadTooLargeError(
            f"receipt too large: {len(content)} bytes > {MAX_RECEIPT_BYTES}"
        )
    if content_type not in _RECEIPT_ALLOWED_CT:
        raise app_errors.ValidationError(f"unsupported receipt content_type: {content_type}")

    source = await _resolve_active_source(session, source_code)
    idempotency_key = normalize_idempotency_key(idempotency_key_raw)
    content_hash = sha256_bytes(content)

    existing = await _dedup_check(
        session,
        source_id=source.source_id,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        _record_metrics(
            source_code=source.source_code,
            kind="receipt",
            created=False,
            size_bytes=0,
        )
        return IngestOutcome(response=_existing_to_response(existing), created=False)

    ext = "pdf" if content_type == "application/pdf" else "jpg"
    if filename and "." in filename:
        maybe = filename.rsplit(".", 1)[-1].lower()
        if maybe in {"jpg", "jpeg", "png", "heic", "pdf"}:
            ext = "jpg" if maybe == "jpeg" else maybe
    now = datetime.now(UTC)
    from app.core import object_keys

    key = object_keys.receipt_key(source.source_code, now, ext)
    object_uri = await storage.put(key, content, content_type=content_type)

    raw_object_id, job_id = await _persist_raw(
        session,
        source_id=source.source_id,
        object_type="RECEIPT_IMAGE",
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        payload_json=None,
        object_uri=object_uri,
        requested_by=requested_by,
        event_type="ingest.receipt.received",
        partition_date=now,
        ingest_parameters={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        },
    )
    await session.commit()

    _record_metrics(
        source_code=source.source_code,
        kind="receipt",
        created=True,
        size_bytes=len(content),
    )

    return IngestOutcome(
        response=IngestResponse(
            raw_object_id=raw_object_id,
            job_id=job_id,
            dedup=False,
            object_uri=object_uri,
        ),
        created=True,
    )


# ---------------------------------------------------------------------------
# object_type 추정 — `raw.raw_object.object_type` CHECK 에 맞춰 매핑
# ---------------------------------------------------------------------------
_CT_TO_OBJECT_TYPE: dict[str, str] = {
    "application/json": "JSON",
    "application/xml": "XML",
    "text/xml": "XML",
    "text/csv": "CSV",
    "text/html": "HTML",
    "application/pdf": "PDF",
}


def _infer_object_type(content_type: str, ext: str) -> str:
    """content_type 우선, 실패 시 확장자로 fallback."""
    if content_type in _CT_TO_OBJECT_TYPE:
        return _CT_TO_OBJECT_TYPE[content_type]
    if content_type.startswith("image/"):
        return "IMAGE"
    ext_map = {
        "json": "JSON",
        "xml": "XML",
        "csv": "CSV",
        "html": "HTML",
        "pdf": "PDF",
        "jpg": "IMAGE",
        "jpeg": "IMAGE",
        "png": "IMAGE",
    }
    return ext_map.get(ext, "JSON")  # 알 수 없으면 JSON 로 (CHECK 통과)


__all__ = [
    "IngestOutcome",
    "ingest_api",
    "ingest_file",
    "ingest_receipt",
]
