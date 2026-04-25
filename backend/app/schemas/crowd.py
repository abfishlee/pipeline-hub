"""Crowd 검수 큐 API schemas (Phase 2.2.10)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CrowdTaskStatus = Literal["PENDING", "REVIEWING", "APPROVED", "REJECTED"]


class CrowdTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    crowd_task_id: int
    raw_object_id: int
    partition_date: date
    ocr_result_id: int | None
    reason: str
    status: CrowdTaskStatus
    payload_json: dict[str, Any]
    assigned_to: int | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: int | None


class OcrResultPreview(BaseModel):
    ocr_result_id: int
    page_no: int | None
    text_content: str | None
    confidence_score: float | None
    engine_name: str


class CrowdTaskDetail(CrowdTaskOut):
    """단건 조회 — raw_object payload + ocr_result 본문 포함."""

    raw_object_uri: str | None = None
    raw_object_payload: dict[str, Any] | None = None
    ocr_results: list[OcrResultPreview] = Field(default_factory=list)


class CrowdTaskStatusUpdate(BaseModel):
    status: Literal["REVIEWING", "APPROVED", "REJECTED"]
    note: str | None = Field(default=None, max_length=500)
