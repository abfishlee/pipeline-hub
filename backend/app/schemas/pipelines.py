"""Pipeline (Visual ETL) API schemas (Phase 3.2.1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal[
    # v1 (Phase 3.2)
    "NOOP",
    "SOURCE_API",
    "SQL_TRANSFORM",
    "DEDUP",
    "DQ_CHECK",
    "LOAD_MASTER",
    "NOTIFY",
    # v2 (Phase 5 generic + Phase 6 Wave 1) — DB CHECK (migration 0047) 와 정렬
    "MAP_FIELDS",
    "SQL_INLINE_TRANSFORM",
    "SQL_ASSET_TRANSFORM",
    "HTTP_TRANSFORM",
    "FUNCTION_TRANSFORM",
    "LOAD_TARGET",
    "OCR_TRANSFORM",
    "CRAWL_FETCH",
    "STANDARDIZE",
    "SOURCE_DATA",
    "PUBLIC_API_FETCH",
    # Phase 7 Wave 1A — 외부 push / upload / DB 수집
    "WEBHOOK_INGEST",
    "FILE_UPLOAD_INGEST",
    "DB_INCREMENTAL_FETCH",
    # Phase 7 Wave 1B — OCR/Crawler push 결과
    "OCR_RESULT_INGEST",
    "CRAWLER_RESULT_INGEST",
    "CDC_EVENT_FETCH",
]
WorkflowStatus = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]


# ---------------------------------------------------------------------------
# Definitions (input)
# ---------------------------------------------------------------------------
class NodeIn(BaseModel):
    node_key: str = Field(min_length=1, max_length=64)
    node_type: NodeType
    config_json: dict[str, Any] = Field(default_factory=dict)
    position_x: int = 0
    position_y: int = 0


class EdgeIn(BaseModel):
    from_node_key: str = Field(min_length=1, max_length=64)
    to_node_key: str = Field(min_length=1, max_length=64)
    condition_expr: dict[str, Any] | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    description: str | None = Field(default=None, max_length=1000)
    nodes: list[NodeIn]
    edges: list[EdgeIn] = Field(default_factory=list)


class WorkflowPatch(BaseModel):
    """DRAFT 상태에서만 수정 — name/description/nodes/edges 교체 가능. status 전이는 별도."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    nodes: list[NodeIn] | None = None
    edges: list[EdgeIn] | None = None


class WorkflowStatusUpdate(BaseModel):
    status: Literal["PUBLISHED", "ARCHIVED"]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: int
    node_key: str
    node_type: NodeType
    config_json: dict[str, Any]
    position_x: int
    position_y: int


class EdgeOut(BaseModel):
    edge_id: int
    from_node_id: int
    to_node_id: int
    condition_expr: dict[str, Any] | None


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: int
    name: str
    version: int
    description: str | None
    status: WorkflowStatus
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    # Phase 3.2.7
    schedule_cron: str | None = None
    schedule_enabled: bool = False


class WorkflowDetail(WorkflowOut):
    nodes: list[NodeOut] = Field(default_factory=list)
    edges: list[EdgeOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
class NodeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_run_id: int
    node_definition_id: int
    node_key: str
    node_type: str
    status: str
    attempt_no: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    output_json: dict[str, Any] | None


class PipelineRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pipeline_run_id: int
    workflow_id: int
    run_date: date
    status: str
    triggered_by: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime


class PipelineRunDetail(PipelineRunOut):
    node_runs: list[NodeRunOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Release / Diff (Phase 3.2.6)
# ---------------------------------------------------------------------------
class PipelineReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_id: int
    workflow_name: str
    version_no: int
    source_workflow_id: int | None
    released_workflow_id: int
    released_by: int | None
    released_at: datetime
    change_summary: dict[str, Any]


class PipelineReleaseDetail(PipelineReleaseOut):
    nodes_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    edges_snapshot: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowStatusTransitionOut(BaseModel):
    """PATCH /status 의 응답 — PUBLISHED 시 새 워크플로/release 정보를 함께 반환."""

    workflow: WorkflowOut
    published_workflow: WorkflowOut | None = None
    release: PipelineReleaseOut | None = None


class NodeChangeOut(BaseModel):
    node_key: str
    node_type: str | None = None
    config_before: dict[str, Any] | None = None
    config_after: dict[str, Any] | None = None


class EdgeChangeOut(BaseModel):
    from_node_key: str
    to_node_key: str


class WorkflowDiffOut(BaseModel):
    before_workflow_id: int
    after_workflow_id: int
    nodes_added: list[NodeChangeOut] = Field(default_factory=list)
    nodes_removed: list[NodeChangeOut] = Field(default_factory=list)
    nodes_changed: list[NodeChangeOut] = Field(default_factory=list)
    edges_added: list[EdgeChangeOut] = Field(default_factory=list)
    edges_removed: list[EdgeChangeOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Schedule / Backfill / Restart (Phase 3.2.7)
# ---------------------------------------------------------------------------
class ScheduleUpdate(BaseModel):
    cron: str | None = Field(default=None, max_length=200)
    enabled: bool = False


class BackfillRequest(BaseModel):
    """`[start_date, end_date]` 양 끝 포함."""

    start_date: date
    end_date: date


class BackfillResponse(BaseModel):
    pipeline_run_ids: list[int]
    run_dates: list[date]


class RestartRequest(BaseModel):
    from_node_key: str | None = Field(default=None, min_length=1, max_length=64)


class RestartResponse(BaseModel):
    new_pipeline_run_id: int
    new_run_date: date
    ready_node_run_ids: list[int]
    seeded_success_node_keys: list[str]


# ---------------------------------------------------------------------------
# DQ Gate (Phase 4.2.2)
# ---------------------------------------------------------------------------
class HoldDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class QualityResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quality_result_id: int
    pipeline_run_id: int | None
    node_run_id: int | None
    target_table: str
    check_kind: str
    passed: bool
    severity: str
    status: str
    details_json: dict[str, Any]
    sample_json: list[dict[str, Any]]
    created_at: datetime


class HoldDecisionResponse(BaseModel):
    decision_id: int
    pipeline_run_id: int
    run_date: date
    decision: Literal["APPROVE", "REJECT"]
    pipeline_status: str
    ready_node_run_ids: list[int] = Field(default_factory=list)
    cancelled_node_run_ids: list[int] = Field(default_factory=list)
    rollback_rows: int = 0


class OnHoldRunOut(PipelineRunOut):
    """ON_HOLD pipeline_run 1건 + 실패 DQ 결과 미리보기."""

    failed_node_keys: list[str] = Field(default_factory=list)
    quality_results: list[QualityResultOut] = Field(default_factory=list)


__all__ = [
    "BackfillRequest",
    "BackfillResponse",
    "EdgeChangeOut",
    "EdgeIn",
    "EdgeOut",
    "HoldDecisionRequest",
    "HoldDecisionResponse",
    "NodeChangeOut",
    "NodeIn",
    "NodeOut",
    "NodeRunOut",
    "NodeType",
    "OnHoldRunOut",
    "PipelineReleaseDetail",
    "PipelineReleaseOut",
    "PipelineRunDetail",
    "PipelineRunOut",
    "QualityResultOut",
    "RestartRequest",
    "RestartResponse",
    "ScheduleUpdate",
    "WorkflowCreate",
    "WorkflowDetail",
    "WorkflowDiffOut",
    "WorkflowOut",
    "WorkflowPatch",
    "WorkflowStatus",
    "WorkflowStatusTransitionOut",
    "WorkflowStatusUpdate",
]
