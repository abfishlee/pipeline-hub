"""Dead Letter 큐 API schemas (Phase 2.2.10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dl_id: int
    origin: str  # actor 이름 (예: process_ocr_event)
    payload_json: dict[str, Any]
    error_message: str | None
    stack_trace: str | None
    failed_at: datetime
    replayed_at: datetime | None
    replayed_by: int | None


class DeadLetterReplayResult(BaseModel):
    dl_id: int
    origin: str
    enqueued_message_id: str | None
    replayed_at: datetime
    replayed_by: int
