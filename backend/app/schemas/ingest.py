"""Pydantic DTOs + 상수 — `/v1/ingest/*`."""

from __future__ import annotations

from pydantic import BaseModel, Field

# 응답 본문에 inline 으로 담을 수 있는 JSON payload 최대 크기. 초과분은 Object Storage.
# 기준: PostgreSQL JSONB 의 toast 임계치 + 인덱스 효율 + 응답 대역폭.
INLINE_JSON_LIMIT_BYTES = 64 * 1024

# 파일 업로드 상한 (일반 파일). 운영 튜닝 시 환경변수화 검토.
MAX_FILE_BYTES = 50 * 1024 * 1024

# 영수증 이미지 상한. 초과 시 413 Payload Too Large.
MAX_RECEIPT_BYTES = 10 * 1024 * 1024


class IngestResponse(BaseModel):
    """수집 API 공통 응답.

    - `dedup=True`: 동일 content_hash 또는 idempotency_key 로 이미 적재된 건.
      `raw_object_id` 는 기존 건. `object_uri` 는 기존 값 (있을 수도, 없을 수도).
    - `dedup=False`: 신규 적재. `job_id` 는 방금 만든 ingest_job.
    """

    raw_object_id: int
    job_id: int | None
    dedup: bool = False
    object_uri: str | None = Field(
        default=None,
        description="Object Storage 에 저장된 경우 URI (예: s3://bucket/key)",
    )


__all__ = [
    "INLINE_JSON_LIMIT_BYTES",
    "MAX_FILE_BYTES",
    "MAX_RECEIPT_BYTES",
    "IngestResponse",
]
