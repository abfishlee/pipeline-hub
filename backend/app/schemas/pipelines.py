"""Pipeline (Visual ETL) API schemas (Phase 3.2.1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal[
    "NOOP",
    "SOURCE_API",
    "SQL_TRANSFORM",
    "DEDUP",
    "DQ_CHECK",
    "LOAD_MASTER",
    "NOTIFY",
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


__all__ = [
    "BackfillRequest",
    "BackfillResponse",
    "EdgeChangeOut",
    "EdgeIn",
    "EdgeOut",
    "NodeChangeOut",
    "NodeIn",
    "NodeOut",
    "NodeRunOut",
    "NodeType",
    "PipelineReleaseDetail",
    "PipelineReleaseOut",
    "PipelineRunDetail",
    "PipelineRunOut",
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
