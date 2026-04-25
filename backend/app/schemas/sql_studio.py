"""SQL Studio API schemas (Phase 3.2.4)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SqlValidateRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


class SqlValidateResponse(BaseModel):
    valid: bool
    error: str | None = None
    referenced_tables: list[str] = Field(default_factory=list)
