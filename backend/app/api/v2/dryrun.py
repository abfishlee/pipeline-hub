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


# ---------------------------------------------------------------------------
# 5. Workflow-level dry-run (Phase 6 Wave 5 — DAG 전체 박스 e2e)
# ---------------------------------------------------------------------------
class _NodeDryRunResult(BaseModel):
    node_id: int
    node_key: str
    node_type: str
    status: str  # "success" | "failed" | "skipped"
    row_count: int = 0
    duration_ms: int = 0
    error_message: str | None = None
    output_table: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowDryRunResponse(BaseModel):
    workflow_id: int
    name: str
    domain_code: str | None
    status: str
    total_duration_ms: int
    succeeded: int
    failed: int
    skipped: int
    nodes: list[_NodeDryRunResult]


def _topological_order(
    nodes: list[Any], edges: list[Any]
) -> list[Any]:
    """Kahn's algorithm — 사이클 감지 시 ValueError."""
    in_degree: dict[int, int] = {n.node_id: 0 for n in nodes}
    adj: dict[int, list[int]] = {n.node_id: [] for n in nodes}
    for e in edges:
        adj[e.from_node_id].append(e.to_node_id)
        in_degree[e.to_node_id] = in_degree.get(e.to_node_id, 0) + 1
    queue = [nid for nid, d in in_degree.items() if d == 0]
    visited: list[int] = []
    while queue:
        nid = queue.pop(0)
        visited.append(nid)
        for nxt in adj.get(nid, []):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    if len(visited) != len(nodes):
        raise HTTPException(422, detail="workflow DAG 에 사이클이 있습니다.")
    by_id = {n.node_id: n for n in nodes}
    return [by_id[nid] for nid in visited]


@router.post("/workflow/{workflow_id}", response_model=WorkflowDryRunResponse)
async def dryrun_workflow(
    workflow_id: int, user: CurrentUserDep
) -> WorkflowDryRunResponse:
    """워크플로의 모든 노드를 위상 정렬 순서로 dry-run.

    각 노드는 *별도 트랜잭션 + rollback* 으로 격리. upstream 의 output_table 변수를
    downstream 의 source_table 로 전달 (단순 DAG; 분기/병합 시 직전 노드 1개만 사용).
    실패한 노드 이후는 SKIPPED 처리 (multi-branch 정확 처리는 Phase 7).
    """
    from app.models.wf import WorkflowDefinition

    def _do() -> WorkflowDryRunResponse:
        sm = get_sync_sessionmaker()
        started_total = datetime.utcnow()
        node_results: list[_NodeDryRunResult] = []
        succeeded = 0
        failed = 0
        skipped = 0

        with sm() as session:
            wf = session.get(WorkflowDefinition, workflow_id)
            if wf is None:
                raise HTTPException(404, detail=f"workflow {workflow_id} not found")
            nodes = list(
                session.execute(
                    text(
                        "SELECT node_id, node_key, node_type, config_json, "
                        "       position_x, position_y "
                        "FROM wf.node_definition WHERE workflow_id = :wid "
                        "ORDER BY node_id"
                    ),
                    {"wid": workflow_id},
                )
            )
            if not nodes:
                raise HTTPException(422, detail="workflow 에 노드가 없습니다.")
            edges = list(
                session.execute(
                    text(
                        "SELECT from_node_id, to_node_id "
                        "FROM wf.edge_definition WHERE workflow_id = :wid"
                    ),
                    {"wid": workflow_id},
                )
            )
            wf_name = wf.name

        # 위상 정렬 (별도 transaction).
        ordered_ids = _topological_order(
            [type("N", (), {"node_id": n.node_id})() for n in nodes],
            [
                type(
                    "E",
                    (),
                    {"from_node_id": e.from_node_id, "to_node_id": e.to_node_id},
                )()
                for e in edges
            ],
        )
        ordered = sorted(
            nodes,
            key=lambda n: [o.node_id for o in ordered_ids].index(n.node_id),
        )
        # 단순 lineage map: node_id → 직전 출력 table.
        out_table_by_id: dict[int, str | None] = {}
        # 직전 노드 (가장 최근에 실행된 upstream) 추적.
        upstream_by_id: dict[int, int | None] = {}
        for e in edges:
            upstream_by_id[e.to_node_id] = e.from_node_id

        domain_code: str | None = None
        had_failure = False

        for n in ordered:
            if had_failure:
                node_results.append(
                    _NodeDryRunResult(
                        node_id=n.node_id,
                        node_key=str(n.node_key),
                        node_type=str(n.node_type),
                        status="skipped",
                        error_message="upstream 노드 실패로 skip",
                    )
                )
                skipped += 1
                continue

            node_started = datetime.utcnow()
            cfg: dict[str, Any] = dict(n.config_json or {})
            # upstream 의 output_table 을 source_table 로 자동 주입 (없으면 그대로).
            up_id = upstream_by_id.get(n.node_id)
            if up_id is not None and up_id in out_table_by_id and out_table_by_id[up_id]:
                cfg.setdefault("source_table", out_table_by_id[up_id])
            cfg["dry_run"] = True

            domain_for_node = (
                cfg.get("domain_code")
                or cfg.get("domain")
                or domain_code
                or "agri"
            )
            if domain_code is None:
                domain_code = str(domain_for_node)

            try:
                runner = get_v2_runner(str(n.node_type))
            except Exception as exc:
                node_results.append(
                    _NodeDryRunResult(
                        node_id=n.node_id,
                        node_key=str(n.node_key),
                        node_type=str(n.node_type),
                        status="failed",
                        error_message=f"runner 미존재: {exc}",
                    )
                )
                failed += 1
                had_failure = True
                continue

            with sm() as session2:
                ctx = NodeV2Context(
                    session=session2,
                    pipeline_run_id=-1,
                    node_run_id=-1,
                    node_key=str(n.node_key),
                    domain_code=str(domain_for_node),
                    user_id=user.user_id,
                )
                try:
                    output = runner.run(ctx, cfg)
                    session2.rollback()  # dry-run = 항상 rollback
                    duration_ms = int(
                        (datetime.utcnow() - node_started).total_seconds() * 1000
                    )
                    output_table = (
                        output.payload.get("output_table")
                        or output.payload.get("target_table")
                        or cfg.get("output_table")
                    )
                    out_table_by_id[n.node_id] = (
                        str(output_table) if output_table else None
                    )
                    if output.status == "failed":
                        node_results.append(
                            _NodeDryRunResult(
                                node_id=n.node_id,
                                node_key=str(n.node_key),
                                node_type=str(n.node_type),
                                status="failed",
                                row_count=output.row_count,
                                duration_ms=duration_ms,
                                error_message=output.error_message,
                                output_table=str(output_table) if output_table else None,
                                payload=dict(output.payload),
                            )
                        )
                        failed += 1
                        had_failure = True
                    else:
                        node_results.append(
                            _NodeDryRunResult(
                                node_id=n.node_id,
                                node_key=str(n.node_key),
                                node_type=str(n.node_type),
                                status="success",
                                row_count=output.row_count,
                                duration_ms=duration_ms,
                                output_table=str(output_table) if output_table else None,
                                payload=dict(output.payload),
                            )
                        )
                        succeeded += 1
                except Exception as exc:
                    session2.rollback()
                    duration_ms = int(
                        (datetime.utcnow() - node_started).total_seconds() * 1000
                    )
                    logger.warning("workflow dry-run node failed", exc_info=exc)
                    node_results.append(
                        _NodeDryRunResult(
                            node_id=n.node_id,
                            node_key=str(n.node_key),
                            node_type=str(n.node_type),
                            status="failed",
                            duration_ms=duration_ms,
                            error_message=str(exc)[:500],
                        )
                    )
                    failed += 1
                    had_failure = True

        total_duration_ms = int(
            (datetime.utcnow() - started_total).total_seconds() * 1000
        )

        # 결과를 ctl.dry_run_record 1건에 요약 적재.
        with sm() as session3:
            try:
                _persist_dry_run(
                    session3,
                    kind="workflow",
                    domain_code=domain_code,
                    target_summary={
                        "workflow_id": workflow_id,
                        "name": wf_name,
                        "succeeded": succeeded,
                        "failed": failed,
                        "skipped": skipped,
                    },
                    row_counts={
                        r.node_key: r.row_count for r in node_results
                    },
                    errors=[
                        f"{r.node_key}: {r.error_message}"
                        for r in node_results
                        if r.error_message
                    ],
                    duration_ms=total_duration_ms,
                    requested_by=user.user_id,
                )
                session3.commit()
            except Exception as exc:
                session3.rollback()
                logger.warning("workflow dry-run persist failed", exc_info=exc)

        return WorkflowDryRunResponse(
            workflow_id=workflow_id,
            name=str(wf_name),
            domain_code=domain_code,
            status="success" if failed == 0 else "failed",
            total_duration_ms=total_duration_ms,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            nodes=node_results,
        )

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# 6. Recent dry-run list (Phase 6 Wave 5 — 최근 dry-run 이력)
# ---------------------------------------------------------------------------
class DryRunRecordOut(BaseModel):
    dry_run_id: int
    requested_by: int | None
    kind: str
    domain_code: str | None
    target_summary: dict[str, Any]
    row_counts: dict[str, Any]
    errors: list[str]
    duration_ms: int
    requested_at: datetime


@router.get("/recent", response_model=list[DryRunRecordOut])
async def list_recent_dry_runs(
    kind: str | None = None,
    domain_code: str | None = None,
    limit: int = 50,
) -> list[DryRunRecordOut]:
    def _do() -> list[DryRunRecordOut]:
        sm = get_sync_sessionmaker()
        params: dict[str, Any] = {"lim": min(max(limit, 1), 200)}
        clauses: list[str] = []
        if kind:
            clauses.append("kind = :k")
            params["k"] = kind
        if domain_code:
            clauses.append("domain_code = :d")
            params["d"] = domain_code
        sql = (
            "SELECT dry_run_id, requested_by, kind, domain_code, target_summary, "
            "       row_counts, errors, duration_ms, requested_at "
            "FROM ctl.dry_run_record "
        )
        if clauses:
            sql += "WHERE " + " AND ".join(clauses) + " "
        sql += "ORDER BY requested_at DESC LIMIT :lim"
        with sm() as session:
            rows = session.execute(text(sql), params).all()
        return [
            DryRunRecordOut(
                dry_run_id=int(r.dry_run_id),
                requested_by=int(r.requested_by) if r.requested_by else None,
                kind=str(r.kind),
                domain_code=str(r.domain_code) if r.domain_code else None,
                target_summary=r.target_summary or {},
                row_counts=r.row_counts or {},
                errors=list(r.errors or []),
                duration_ms=int(r.duration_ms or 0),
                requested_at=r.requested_at,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_do)


__all__ = ["router"]
