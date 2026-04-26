"""Crowd 검수 API schemas — Phase 2.2.10 placeholder + Phase 4.2.1 정식.

Phase 4 의 정식 schema 는 `crowd.task` 기반. Phase 2.2.10 의 `CrowdTaskOut` 등은
`run.crowd_task` view 호환 형태로 유지 (legacy endpoint 호환).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Phase 2.2.10 호환 (run.crowd_task view 가 같은 형태) — 기존 endpoint 가 사용.
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


# ---------------------------------------------------------------------------
# Phase 4.2.1 — 정식 crowd schema 기반 DTO
# ---------------------------------------------------------------------------
TaskKind = Literal[
    "OCR_REVIEW",
    "PRODUCT_MATCHING",
    "RECEIPT_VALIDATION",
    "ANOMALY_CHECK",
    "std_low_confidence",
    "ocr_low_confidence",
    "price_fact_low_confidence",
    "sample_review",
]
TaskStatus = Literal["PENDING", "REVIEWING", "CONFLICT", "APPROVED", "REJECTED", "CANCELLED"]
ReviewDecision = Literal["APPROVE", "REJECT", "SKIP"]
ConsensusKind = Literal["SINGLE", "DOUBLE_AGREED", "CONFLICT_RESOLVED"]


class TaskOut(BaseModel):
    """crowd.task 1행."""

    model_config = ConfigDict(from_attributes=True)

    crowd_task_id: int
    task_kind: TaskKind
    priority: int
    raw_object_id: int | None
    partition_date: date | None
    ocr_result_id: int | None
    std_record_id: int | None
    payload: dict[str, Any]
    status: TaskStatus
    requires_double_review: bool
    created_at: datetime
    updated_at: datetime


class TaskAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assignment_id: int
    crowd_task_id: int
    reviewer_id: int
    assigned_at: datetime
    due_at: datetime | None
    released_at: datetime | None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: int
    crowd_task_id: int
    reviewer_id: int
    decision: ReviewDecision
    decision_payload: dict[str, Any]
    comment: str | None
    time_spent_ms: int | None
    decided_at: datetime


class TaskDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    crowd_task_id: int
    final_decision: Literal["APPROVE", "REJECT"]
    decided_by: int | None
    consensus_kind: ConsensusKind
    effect_payload: dict[str, Any]
    decided_at: datetime


class TaskFullDetail(TaskOut):
    """단건 상세 — assignments + reviews + decision 동봉."""

    assignments: list[TaskAssignmentOut] = Field(default_factory=list)
    reviews: list[ReviewOut] = Field(default_factory=list)
    decision: TaskDecisionOut | None = None


class AssignTaskRequest(BaseModel):
    """검수자 1+명 배정. priority>=8 면 자동으로 2명 이상 강제."""

    reviewer_ids: list[int] = Field(min_length=1, max_length=5)
    due_at: datetime | None = None


class SubmitReviewRequest(BaseModel):
    """검수자가 자신의 결정을 제출."""

    decision: ReviewDecision
    decision_payload: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)
    time_spent_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class ResolveConflictRequest(BaseModel):
    """관리자 (ADMIN/APPROVER) 가 CONFLICT 해결."""

    final_decision: Literal["APPROVE", "REJECT"]
    note: str | None = Field(default=None, max_length=2000)


class ReviewerStatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reviewer_id: int
    reviewed_count_30d: int
    avg_decision_ms_30d: int | None
    conflict_rate_30d: float | None
    regression_rate_30d: float | None
    updated_at: datetime


__all__ = [
    "AssignTaskRequest",
    "ConsensusKind",
    "CrowdTaskDetail",
    "CrowdTaskOut",
    "CrowdTaskStatus",
    "CrowdTaskStatusUpdate",
    "OcrResultPreview",
    "ResolveConflictRequest",
    "ReviewDecision",
    "ReviewOut",
    "ReviewerStatsOut",
    "SubmitReviewRequest",
    "TaskAssignmentOut",
    "TaskDecisionOut",
    "TaskFullDetail",
    "TaskKind",
    "TaskOut",
    "TaskStatus",
]
