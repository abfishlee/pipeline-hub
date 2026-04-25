"""HTTP 경계 — `/v1/ingest/*` 수집 API.

권한: OPERATOR 또는 ADMIN. 모든 엔드포인트는 Bearer 인증 필수.
응답:
  - 201 Created      신규 raw_object 적재 성공
  - 200 OK           dedup 히트 (기존 raw_object_id 반환)
  - 403 FORBIDDEN    source_code 가 비활성 또는 권한 부족
  - 404 NOT_FOUND    source_code 미존재
  - 413 PAYLOAD_TOO_LARGE  영수증/파일 상한 초과
  - 422              content_type 불일치
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Path, UploadFile
from fastapi.responses import JSONResponse

from app.deps import CurrentUserDep, SessionDep, SettingsDep, require_roles
from app.domain import ingest as ingest_domain
from app.integrations.object_storage import ObjectStorage, get_object_storage
from app.schemas.ingest import IngestResponse

router = APIRouter(
    prefix="/v1/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_roles("OPERATOR", "ADMIN"))],
)


def _storage_dep() -> ObjectStorage:
    return get_object_storage()


StorageDep = Annotated[ObjectStorage, Depends(_storage_dep)]


def _to_http_response(outcome: ingest_domain.IngestOutcome) -> JSONResponse:
    # Pydantic v2 → JSON 직렬화
    payload: dict[str, object] = outcome.response.model_dump()
    status_code = 201 if outcome.created else 200
    return JSONResponse(content=payload, status_code=status_code)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
@router.post("/api/{source_code}", response_model=IngestResponse)
async def ingest_api_json(
    source_code: Annotated[str, Path(min_length=3, max_length=64)],
    body: dict[str, object],
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    current: CurrentUserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    outcome = await ingest_domain.ingest_api(
        session,
        source_code=source_code,
        body=body,
        idempotency_key_raw=idempotency_key,
        requested_by=current.user_id,
        storage=storage,
        settings=settings,
    )
    return _to_http_response(outcome)


# ---------------------------------------------------------------------------
# File (multipart)
# ---------------------------------------------------------------------------
@router.post("/file/{source_code}", response_model=IngestResponse)
async def ingest_file_upload(
    source_code: Annotated[str, Path(min_length=3, max_length=64)],
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    current: CurrentUserDep,
    file: Annotated[UploadFile, File(description="수집할 파일")],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    content = await file.read()
    outcome = await ingest_domain.ingest_file(
        session,
        source_code=source_code,
        filename=file.filename or "unknown",
        content=content,
        content_type=file.content_type or "application/octet-stream",
        idempotency_key_raw=idempotency_key,
        requested_by=current.user_id,
        storage=storage,
        settings=settings,
    )
    return _to_http_response(outcome)


# ---------------------------------------------------------------------------
# Receipt (multipart 이미지 전용)
# ---------------------------------------------------------------------------
@router.post("/receipt", response_model=IngestResponse)
async def ingest_receipt_upload(
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    current: CurrentUserDep,
    file: Annotated[UploadFile, File(description="영수증 이미지 또는 PDF")],
    source_code: Annotated[str, Form(min_length=3, max_length=64)] = "RECEIPT_APP",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    content = await file.read()
    outcome = await ingest_domain.ingest_receipt(
        session,
        source_code=source_code,
        filename=file.filename or "receipt",
        content=content,
        content_type=file.content_type or "application/octet-stream",
        idempotency_key_raw=idempotency_key,
        requested_by=current.user_id,
        storage=storage,
        settings=settings,
    )
    return _to_http_response(outcome)
