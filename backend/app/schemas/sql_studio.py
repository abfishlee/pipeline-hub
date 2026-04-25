"""SQL Studio API schemas (Phase 3.2.4 + 3.2.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 3.2.4 dry-run validate
# ---------------------------------------------------------------------------
class SqlValidateRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


class SqlValidateResponse(BaseModel):
    valid: bool
    error: str | None = None
    referenced_tables: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.2.5 preview / explain
# ---------------------------------------------------------------------------
class SqlPreviewRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=1000, ge=1, le=10_000)
    sql_query_version_id: int | None = None


class SqlPreviewResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int


class SqlExplainRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    sql_query_version_id: int | None = None


class SqlExplainResponse(BaseModel):
    plan_json: list[dict[str, Any]]
    elapsed_ms: int


# ---------------------------------------------------------------------------
# 3.2.5 SqlQuery / SqlQueryVersion CRUD
# ---------------------------------------------------------------------------
class SqlQueryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    sql_text: str = Field(min_length=1, max_length=20_000)


class SqlVersionCreate(BaseModel):
    sql_text: str = Field(min_length=1, max_length=20_000)


class SqlVersionReview(BaseModel):
    """approve/reject 공용 — 코멘트만."""

    comment: str | None = Field(default=None, max_length=2_000)


class SqlQueryVersionOut(BaseModel):
    sql_query_version_id: int
    sql_query_id: int
    version_no: int
    sql_text: str
    referenced_tables: list[str]
    status: str
    parent_version_id: int | None
    submitted_by: int | None
    submitted_at: datetime | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    review_comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class SqlQueryOut(BaseModel):
    sql_query_id: int
    name: str
    description: str | None
    owner_user_id: int
    current_version_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SqlQueryDetail(SqlQueryOut):
    versions: list[SqlQueryVersionOut]
