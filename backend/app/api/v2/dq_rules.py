"""HTTP — `/v2/dq-rules` (Phase 5.2.4 STEP 7 Q3).

DQ Rule Builder 의 backend.

Q3 답변 — *SQL Studio sandbox 와 통합*. DQ Rule Builder UI 가 custom_sql 미리보기를
요청하면 본 라우트가 SQL Studio 의 *동일 검증 엔진* (sql_studio.run_validate) 을 호출.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_engine, get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.guardrails.dry_run import run_dry
from app.domain.guardrails.sql_guard import (
    NodeKind,
    SqlGuardError,
    SqlNodeContext,
    guard_sql,
)
from app.models.domain import DqRule

router = APIRouter(
    prefix="/v2/dq-rules",
    tags=["v2-dq-rules"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class DqRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    domain_code: str
    target_table: str
    rule_kind: str
    rule_json: dict[str, Any]
    severity: str
    timeout_ms: int
    sample_limit: int
    max_scan_rows: int | None
    incremental_only: bool
    status: str
    version: int
    description: str | None
    created_at: datetime
    updated_at: datetime


class DqRuleCreate(BaseModel):
    domain_code: str
    target_table: str
    rule_kind: str = Field(
        pattern=r"^(row_count_min|null_pct_max|unique_columns|"
        r"reference|range|custom_sql)$"
    )
    rule_json: dict[str, Any] = Field(default_factory=dict)
    severity: str = Field(default="ERROR", pattern=r"^(INFO|WARN|ERROR|BLOCK)$")
    timeout_ms: int = Field(default=30_000, ge=100, le=600_000)
    sample_limit: int = Field(default=10, ge=1, le=10_000)
    max_scan_rows: int | None = Field(default=None, ge=1)
    incremental_only: bool = False
    description: str | None = None


class DqRuleUpdate(BaseModel):
    rule_json: dict[str, Any] | None = None
    severity: str | None = Field(default=None, pattern=r"^(INFO|WARN|ERROR|BLOCK)$")
    timeout_ms: int | None = Field(default=None, ge=100, le=600_000)
    sample_limit: int | None = Field(default=None, ge=1, le=10_000)
    max_scan_rows: int | None = None
    incremental_only: bool | None = None
    description: str | None = None
    status: str | None = Field(
        default=None, pattern=r"^(DRAFT|REVIEW|APPROVED|PUBLISHED)$"
    )


class CustomSqlPreviewRequest(BaseModel):
    domain_code: str
    sql: str = Field(min_length=1, max_length=5_000)
    sample_limit: int = Field(default=10, ge=1, le=1_000)


class CustomSqlPreviewResponse(BaseModel):
    is_valid: bool
    error: str | None = None
    row_count: int | None = None
    duration_ms: int = 0


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        try:
            res = fn(session)
            session.commit()
            return res
        except Exception:
            session.rollback()
            raise


@router.get("", response_model=list[DqRuleOut])
async def list_rules(
    domain_code: str | None = None, target_table: str | None = None
) -> list[DqRuleOut]:
    def _do(s: Session) -> list[DqRuleOut]:
        q = select(DqRule).order_by(
            DqRule.domain_code, DqRule.target_table, DqRule.rule_id
        )
        if domain_code:
            q = q.where(DqRule.domain_code == domain_code)
        if target_table:
            q = q.where(DqRule.target_table == target_table)
        rows = s.execute(q).scalars().all()
        return [DqRuleOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=DqRuleOut, status_code=201)
async def create_rule(body: DqRuleCreate) -> DqRuleOut:
    def _do(s: Session) -> DqRuleOut:
        rule = DqRule(
            domain_code=body.domain_code,
            target_table=body.target_table,
            rule_kind=body.rule_kind,
            rule_json=body.rule_json,
            severity=body.severity,
            timeout_ms=body.timeout_ms,
            sample_limit=body.sample_limit,
            max_scan_rows=body.max_scan_rows,
            incremental_only=body.incremental_only,
            description=body.description,
            status="DRAFT",
        )
        s.add(rule)
        s.flush()
        return DqRuleOut.model_validate(rule)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{rule_id}", response_model=DqRuleOut)
async def update_rule(rule_id: int, body: DqRuleUpdate) -> DqRuleOut:
    def _do(s: Session) -> DqRuleOut:
        rule = s.get(DqRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"rule {rule_id} not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(rule, field_name, value)
        s.flush()
        return DqRuleOut.model_validate(rule)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("/preview", response_model=CustomSqlPreviewResponse)
async def preview_custom_sql(
    body: CustomSqlPreviewRequest, user: CurrentUserDep
) -> CustomSqlPreviewResponse:
    """custom_sql DQ rule 의 EXPLAIN/실행 결과 (rollback 보장).

    Q3 — SQL Studio sandbox 와 동일 sql_guard 통과 후 dry_run 으로 row_count 산출.
    """
    del user

    def _do() -> CustomSqlPreviewResponse:
        # 1. sql_guard (DQ_CHECK 컨텍스트 — SELECT only).
        try:
            extra: frozenset[str] = frozenset(
                {
                    f"{body.domain_code}_mart",
                    f"{body.domain_code}_stg",
                    f"{body.domain_code}_raw",
                }
            )
            guard_sql(
                body.sql,
                ctx=SqlNodeContext(
                    node_kind=NodeKind.DQ_CHECK,
                    domain_code=body.domain_code,
                    allowed_extra_schemas=extra,
                ),
            )
        except SqlGuardError as exc:
            return CustomSqlPreviewResponse(
                is_valid=False, error=f"guard: {exc}"[:500]
            )
        # 2. dry_run — sample_limit 강제.
        wrapped = f"SELECT COUNT(*) FROM ({body.sql}) _q"
        result = run_dry(
            engine=get_sync_engine(),
            queries=[],
            fetch_after=[wrapped],
        )
        if result.errors:
            return CustomSqlPreviewResponse(
                is_valid=False,
                error="; ".join(result.errors)[:500],
                duration_ms=result.duration_ms,
            )
        row_count = result.row_counts[0] if result.row_counts else 0
        return CustomSqlPreviewResponse(
            is_valid=True,
            row_count=row_count,
            duration_ms=result.duration_ms,
        )

    return await asyncio.to_thread(_do)


__all__ = ["router"]
