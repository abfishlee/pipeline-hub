"""HTTP — `/v2/dryrun` (Phase 5.2.4 STEP 7 Q4).

Q4 답변 — *트랜잭션 rollback 기반* 실제 실행. EXPLAIN cost 보다 정확.

가드:
  - sample_limit (기본 1_000)
  - statement_timeout (기본 5_000ms)
  - 결과 *항상* ROLLBACK
  - mart write 는 본 노드 직후 트랜잭션 닫히는 시점 필수 rollback

지원 종류:
  - field_mapping  — MAP_FIELDS 노드 dry-run (sandbox source → 가상 target)
  - load_target    — LOAD_TARGET 노드 dry-run (rows_affected 추정)
  - dq_rule        — DQ rule 1개 평가 결과
  - sql_asset      — SQL_ASSET 의 SELECT 결과 (limit 포함)
  - mart_designer  — MartDesignSpec 의 DDL 생성 (실 적용 X — DDL 만 반환)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_engine, get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.guardrails.dry_run import run_dry
from app.domain.mart_designer import (
    ColumnSpec,
    IndexSpec,
    MartDesignError,
    MartDesignSpec,
    design_table,
    save_draft,
)
from app.domain.nodes_v2 import NodeV2Context, get_v2_runner

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v2/dryrun",
    tags=["v2-dryrun"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "OPERATOR", "APPROVER"))
    ],
)


# ---------------------------------------------------------------------------
# 공통 schema
# ---------------------------------------------------------------------------
class DryRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dry_run_id: int | None = None
    kind: str
    domain_code: str | None
    rows_affected: list[int] = Field(default_factory=list)
    row_counts: list[int] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    target_summary: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime | None = None


# ---------------------------------------------------------------------------
# 공통 helper — DryRunRecord 적재
# ---------------------------------------------------------------------------
def _persist_dry_run(
    session: Session,
    *,
    kind: str,
    domain_code: str | None,
    target_summary: dict[str, Any],
    row_counts: dict[str, Any],
    errors: list[str],
    duration_ms: int,
    requested_by: int | None,
) -> int:
    dry_run_id = session.execute(
        text(
            "INSERT INTO ctl.dry_run_record "
            "(requested_by, kind, domain_code, target_summary, row_counts, "
            " errors, duration_ms) "
            "VALUES (:by, :kind, :dom, CAST(:tgt AS JSONB), CAST(:rc AS JSONB), "
            "        :err, :ms) "
            "RETURNING dry_run_id"
        ),
        {
            "by": requested_by,
            "kind": kind,
            "dom": domain_code,
            "tgt": json.dumps(target_summary, default=str),
            "rc": json.dumps(row_counts, default=str),
            "err": errors,
            "ms": duration_ms,
        },
    ).scalar_one()
    return int(dry_run_id)


# ---------------------------------------------------------------------------
# 1. raw SQL dry-run (sandbox/스튜디오용)
# ---------------------------------------------------------------------------
class RawSqlDryRunRequest(BaseModel):
    domain_code: str | None = None
    queries: list[str] = Field(min_length=1, max_length=10)
    fetch_after: list[str] = Field(default_factory=list, max_length=10)


@router.post("/sql", response_model=DryRunSummary)
async def dryrun_sql(
    body: RawSqlDryRunRequest,
    user: CurrentUserDep,
) -> DryRunSummary:
    def _do() -> DryRunSummary:
        engine = get_sync_engine()
        result = run_dry(
            engine=engine,
            queries=body.queries,
            fetch_after=body.fetch_after,
        )
        sm = get_sync_sessionmaker()
        with sm() as session:
            dry_run_id = _persist_dry_run(
                session,
                kind="custom",
                domain_code=body.domain_code,
                target_summary={"queries": body.queries[:3]},
                row_counts={
                    "rows_affected": result.rows_affected,
                    "row_counts": result.row_counts,
                },
                errors=result.errors,
                duration_ms=result.duration_ms,
                requested_by=user.user_id,
            )
            session.commit()
        return DryRunSummary(
            dry_run_id=dry_run_id,
            kind="custom",
            domain_code=body.domain_code,
            rows_affected=result.rows_affected,
            row_counts=result.row_counts,
            errors=result.errors,
            duration_ms=result.duration_ms,
            target_summary={"queries": body.queries[:3]},
        )

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# 2. LOAD_TARGET dry-run
# ---------------------------------------------------------------------------
class LoadTargetDryRunRequest(BaseModel):
    domain_code: str
    source_table: str
    policy_id: int | None = None
    resource_id: int | None = None
    target_table: str | None = None


@router.post("/load-target", response_model=DryRunSummary)
async def dryrun_load_target(
    body: LoadTargetDryRunRequest,
    user: CurrentUserDep,
) -> DryRunSummary:
    def _do() -> DryRunSummary:
        sm = get_sync_sessionmaker()
        runner = get_v2_runner("LOAD_TARGET")
        with sm() as session:
            ctx = NodeV2Context(
                session=session,
                pipeline_run_id=-1,
                node_run_id=-1,
                node_key=f"dryrun-load-{datetime.utcnow().timestamp()}",
                domain_code=body.domain_code,
                user_id=user.user_id,
            )
            try:
                output = runner.run(
                    ctx,
                    {
                        "source_table": body.source_table,
                        "policy_id": body.policy_id,
                        "resource_id": body.resource_id,
                        "target_table": body.target_table,
                        "dry_run": True,
                    },
                )
            except Exception as exc:
                session.rollback()
                raise HTTPException(status_code=422, detail=str(exc)[:500]) from exc
            session.rollback()  # dry-run — 항상 rollback
        errors = (
            [output.error_message]
            if output.status == "failed" and output.error_message
            else []
        )
        with sm() as session:
            dry_run_id = _persist_dry_run(
                session,
                kind="load_target",
                domain_code=body.domain_code,
                target_summary={
                    "source_table": body.source_table,
                    "target_table": body.target_table or output.payload.get("target_table"),
                    "mode": output.payload.get("mode"),
                },
                row_counts={"row_count": output.row_count, **output.payload},
                errors=errors,
                duration_ms=0,
                requested_by=user.user_id,
            )
            session.commit()
        return DryRunSummary(
            dry_run_id=dry_run_id,
            kind="load_target",
            domain_code=body.domain_code,
            rows_affected=[output.row_count],
            row_counts=[output.row_count],
            errors=errors,
            target_summary=output.payload,
        )

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# 3. Field Mapping dry-run
# ---------------------------------------------------------------------------
class FieldMappingDryRunRequest(BaseModel):
    domain_code: str
    contract_id: int
    source_table: str
    target_table: str | None = None
    apply_only_published: bool = False  # DRAFT 도 평가 (Q1)


@router.post("/field-mapping", response_model=DryRunSummary)
async def dryrun_field_mapping(
    body: FieldMappingDryRunRequest,
    user: CurrentUserDep,
) -> DryRunSummary:
    def _do() -> DryRunSummary:
        sm = get_sync_sessionmaker()
        runner = get_v2_runner("MAP_FIELDS")
        with sm() as session:
            ctx = NodeV2Context(
                session=session,
                pipeline_run_id=-1,
                node_run_id=-1,
                node_key=f"dryrun-map-{datetime.utcnow().timestamp()}",
                domain_code=body.domain_code,
                contract_id=body.contract_id,
                user_id=user.user_id,
            )
            try:
                output = runner.run(
                    ctx,
                    {
                        "contract_id": body.contract_id,
                        "source_table": body.source_table,
                        "target_table": body.target_table,
                        "apply_only_published": body.apply_only_published,
                        "limit_rows": 1_000,
                    },
                )
            except Exception as exc:
                session.rollback()
                raise HTTPException(status_code=422, detail=str(exc)[:500]) from exc
            session.rollback()  # dry-run — sandbox 도 보존하지 않음.
        errors = (
            [output.error_message]
            if output.status == "failed" and output.error_message
            else []
        )
        with sm() as session:
            dry_run_id = _persist_dry_run(
                session,
                kind="field_mapping",
                domain_code=body.domain_code,
                target_summary={
                    "contract_id": body.contract_id,
                    "source_table": body.source_table,
                    "target_table": output.payload.get("target_table"),
                },
                row_counts={"row_count": output.row_count},
                errors=errors,
                duration_ms=0,
                requested_by=user.user_id,
            )
            session.commit()
        return DryRunSummary(
            dry_run_id=dry_run_id,
            kind="field_mapping",
            domain_code=body.domain_code,
            rows_affected=[output.row_count],
            row_counts=[output.row_count],
            errors=errors,
            target_summary=output.payload,
        )

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# 4. Mart Designer dry-run (DDL 생성만 — DDL 적용은 별도)
# ---------------------------------------------------------------------------
class _MartDesignColumn(BaseModel):
    name: str
    type: str
    nullable: bool = True
    default: str | None = None
    description: str | None = None


class _MartDesignIndex(BaseModel):
    name: str
    columns: list[str] = Field(min_length=1)
    unique: bool = False


class MartDesignerDryRunRequest(BaseModel):
    domain_code: str
    target_table: str
    columns: list[_MartDesignColumn] = Field(min_length=1, max_length=200)
    primary_key: list[str] = Field(default_factory=list)
    partition_key: str | None = None
    indexes: list[_MartDesignIndex] = Field(default_factory=list, max_length=20)
    description: str | None = None
    save_as_draft: bool = True


class MartDesignerDryRunResponse(DryRunSummary):
    ddl_text: str
    is_alter: bool
    draft_id: int | None = None


@router.post("/mart-designer", response_model=MartDesignerDryRunResponse)
async def dryrun_mart_designer(
    body: MartDesignerDryRunRequest,
    user: CurrentUserDep,
) -> MartDesignerDryRunResponse:
    def _do() -> MartDesignerDryRunResponse:
        sm = get_sync_sessionmaker()
        spec = MartDesignSpec(
            domain_code=body.domain_code,
            target_table=body.target_table,
            columns=[
                ColumnSpec(
                    name=c.name,
                    type=c.type,
                    nullable=c.nullable,
                    default=c.default,
                    description=c.description,
                )
                for c in body.columns
            ],
            primary_key=list(body.primary_key),
            partition_key=body.partition_key,
            indexes=[
                IndexSpec(name=i.name, columns=tuple(i.columns), unique=i.unique)
                for i in body.indexes
            ],
            description=body.description,
        )
        with sm() as session:
            try:
                result = design_table(session, spec)
            except MartDesignError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            draft_id: int | None = None
            if body.save_as_draft:
                draft_id = save_draft(
                    session, spec=spec, result=result, created_by=user.user_id
                )
            dry_run_id = _persist_dry_run(
                session,
                kind="mart_designer",
                domain_code=body.domain_code,
                target_summary={
                    "target_table": body.target_table,
                    "is_alter": result.is_alter,
                    "draft_id": draft_id,
                },
                row_counts={},
                errors=[],
                duration_ms=0,
                requested_by=user.user_id,
            )
            session.commit()
        return MartDesignerDryRunResponse(
            dry_run_id=dry_run_id,
            kind="mart_designer",
            domain_code=body.domain_code,
            target_summary=result.diff_summary,
            ddl_text=result.ddl_text,
            is_alter=result.is_alter,
            draft_id=draft_id,
        )

    return await asyncio.to_thread(_do)


__all__ = ["router"]
