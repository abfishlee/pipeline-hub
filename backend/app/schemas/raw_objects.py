"""Pydantic DTOs — `raw.raw_object` 조회."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ObjectType = Literal["JSON", "XML", "CSV", "HTML", "PDF", "IMAGE", "DB_ROW", "RECEIPT_IMAGE"]
RawStatus = Literal["RECEIVED", "PROCESSED", "FAILED", "DISCARDED"]


class RawObjectSummary(BaseModel):
    """리스트 조회용 — payload_json/object_uri 같은 큰 필드는 boolean 으로 표시.

    상세는 별도 detail endpoint 호출.
    """

    model_config = ConfigDict(from_attributes=True)

    raw_object_id: int
    source_id: int
    job_id: int | None = None
    object_type: ObjectType
    status: RawStatus
    received_at: datetime
    partition_date: date
    has_inline_payload: bool = False
    object_uri_present: bool = False


class RawObjectDetail(BaseModel):
    """상세 조회 — payload_json (있으면) 또는 download_url (presigned GET)."""

    model_config = ConfigDict(from_attributes=True)

    raw_object_id: int
    source_id: int
    job_id: int | None = None
    object_type: ObjectType
    status: RawStatus
    content_hash: str
    idempotency_key: str | None = None
    received_at: datetime
    partition_date: date
    payload_json: dict[str, Any] | None = None
    object_uri: str | None = None
    download_url: str | None = Field(
        default=None,
        description="presigned GET URL (5분 유효). object_uri 가 있을 때만 발급.",
    )


__all__ = ["ObjectType", "RawObjectDetail", "RawObjectSummary", "RawStatus"]
