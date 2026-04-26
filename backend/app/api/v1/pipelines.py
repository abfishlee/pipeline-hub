"""HTTP 경계 — `/v1/pipelines` (Visual ETL Designer 워크플로 CRUD + 실행 + 배포 + 스케줄).

Phase 3.2.1 Pipeline Runtime. 실행 트리거는 sync session 으로 도메인 호출
(start_pipeline_run 이 즉시 entry node 들을 enqueue). 노드 실행은 dramatiq actor.

Phase 3.2.6 추가: PATCH /status PUBLISHED 가 단순 status 변경 → 새 PUBLISHED 워크플로
복제 + version 자동 증가 + release 이력 적재 + diff 반환으로 격상.

Phase 3.2.7 추가: 스케줄 메타 (cron / enabled), Backfill (날짜 범위 → 일자별 run),
runs 검색 (status/기간/workflow), 재실행 (전체 또는 특정 노드부터).

권한: ADMIN / APPROVER (워크플로 PUBLISH/실행 권한이 mart 쓰기와 동등). 조회는 OPERATOR
이상 허용.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.core.events import RedisPubSub
from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, SessionDep, require_roles
from app.domain import dq_gate as dq_gate_domain
from app.domain import pipeline_release as release_domain
from app.domain import pipeline_runtime as runtime
from app.domain import pipeline_schedule as schedule_domain
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition
from app.repositories import pipelines as pipelines_repo
from app.schemas.pipelines import (
    BackfillRequest,
    BackfillResponse,
    EdgeChangeOut,
    EdgeOut,
    HoldDecisionRequest,
    HoldDecisionResponse,
    NodeChangeOut,
    NodeOut,
    NodeRunOut,
    OnHoldRunOut,
    PipelineReleaseDetail,
    PipelineReleaseOut,
    PipelineRunDetail,
    PipelineRunOut,
    QualityResultOut,
    RestartRequest,
    RestartResponse,
    ScheduleUpdate,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowDiffOut,
    WorkflowOut,
    WorkflowPatch,
    WorkflowStatus,
    WorkflowStatusTransitionOut,
    WorkflowStatusUpdate,
)

router = APIRouter(
    prefix="/v1/pipelines",
    tags=["pipelines"],
    dependencies=[Depends(require_roles("ADMIN", "APPROVER", "OPERATOR"))],
)


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=WorkflowDetail,
    status_code=201,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def create_pipeline(
    session: SessionDep,
    user: CurrentUserDep,
    body: WorkflowCreate,
) -> WorkflowDetail:
    try:
        workflow = await pipelines_repo.create_workflow(
            session,
            name=body.name,
            version=body.version,
            description=body.description,
            created_by=user.user_id,
            nodes=[n.model_dump() for n in body.nodes],
            edges=[e.model_dump() for e in body.edges],
        )
    except ValueError as exc:
        raise app_errors.ValidationError(str(exc)) from exc
    await session.commit()

    graph = await pipelines_repo.get_workflow_with_graph(session, workflow.workflow_id)
    assert graph is not None
    return _to_detail(graph)


@router.get("", response_model=list[WorkflowOut])
async def list_pipelines(
    session: SessionDep,
    status: WorkflowStatus | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkflowOut]:
    rows = await pipelines_repo.list_workflows(session, status=status, limit=limit, offset=offset)
    return [WorkflowOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Releases (Phase 3.2.6) — `/{workflow_id}` 보다 먼저 선언해 path 충돌 방지.
# ---------------------------------------------------------------------------
@router.get("/releases", response_model=list[PipelineReleaseOut])
async def list_releases(
    session: SessionDep,
    name: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PipelineReleaseOut]:
    rows = await _in_sync_session(
        lambda s: release_domain.list_releases(s, workflow_name=name, limit=limit)
    )
    return [PipelineReleaseOut.model_validate(r) for r in rows]


@router.get("/releases/{release_id}", response_model=PipelineReleaseDetail)
async def get_release(
    session: SessionDep,
    release_id: int,
) -> PipelineReleaseDetail:
    def _do(s: Session) -> object:
        from app.models.wf import PipelineRelease

        r = s.get(PipelineRelease, release_id)
        if r is None:
            raise app_errors.NotFoundError(f"release {release_id} not found")
        return r

    rel = await _in_sync_session(_do)
    return PipelineReleaseDetail.model_validate(rel)


# Phase 3.2.7 — `/runs` 검색 라우트는 `/{workflow_id}` 보다 먼저 등록 필요
# (그렇지 않으면 "runs" 가 int 변환 시도 → 422 충돌).
@router.get("/runs", response_model=list[PipelineRunOut])
async def search_runs(
    workflow_id: Annotated[int | None, Query(ge=1)] = None,
    status: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PipelineRunOut]:
    """status / 기간 / workflow 별 실행 이력 검색."""
    rows = await _in_sync_session(
        lambda s: schedule_domain.search_runs(
            s,
            workflow_id=workflow_id,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
    )
    return [PipelineRunOut.model_validate(r) for r in rows]


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_pipeline(session: SessionDep, workflow_id: int) -> WorkflowDetail:
    graph = await pipelines_repo.get_workflow_with_graph(session, workflow_id)
    if graph is None:
        raise app_errors.NotFoundError(f"workflow {workflow_id} not found")
    return _to_detail(graph)


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowDetail,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def patch_pipeline(
    session: SessionDep,
    workflow_id: int,
    body: WorkflowPatch,
) -> WorkflowDetail:
    workflow = await pipelines_repo.get_workflow(session, workflow_id)
    if workflow is None:
        raise app_errors.NotFoundError(f"workflow {workflow_id} not found")
    if workflow.status != "DRAFT":
        raise app_errors.ValidationError(
            f"workflow {workflow_id} is {workflow.status} — only DRAFT is editable"
        )

    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.nodes is not None or body.edges is not None:
        try:
            await pipelines_repo.replace_graph(
                session,
                workflow=workflow,
                nodes=[n.model_dump() for n in (body.nodes or [])],
                edges=[e.model_dump() for e in (body.edges or [])],
            )
        except ValueError as exc:
            raise app_errors.ValidationError(str(exc)) from exc
    await session.commit()
    graph = await pipelines_repo.get_workflow_with_graph(session, workflow.workflow_id)
    assert graph is not None
    return _to_detail(graph)


@router.patch(
    "/{workflow_id}/status",
    response_model=WorkflowStatusTransitionOut,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def transition_status(
    session: SessionDep,
    user: CurrentUserDep,
    workflow_id: int,
    body: WorkflowStatusUpdate,
) -> WorkflowStatusTransitionOut:
    """status 전이 — Phase 3.2.6 정책.

    - DRAFT → PUBLISHED : 새 PUBLISHED 워크플로 row 생성 (version 자동 +1) +
      `wf.pipeline_release` 적재 + 그래프 freeze + diff 계산. 원본 DRAFT 는 status 유지.
    - DRAFT → ARCHIVED  : status 만 변경.
    - PUBLISHED → ARCHIVED : status 만 변경.
    """
    workflow = await pipelines_repo.get_workflow(session, workflow_id)
    if workflow is None:
        raise app_errors.NotFoundError(f"workflow {workflow_id} not found")
    valid_from = {
        "DRAFT": {"PUBLISHED", "ARCHIVED"},
        "PUBLISHED": {"ARCHIVED"},
        "ARCHIVED": set(),
    }
    if body.status not in valid_from.get(workflow.status, set()):
        raise app_errors.ValidationError(f"invalid transition: {workflow.status} → {body.status}")

    if workflow.status == "DRAFT" and body.status == "PUBLISHED":
        # sync 도메인으로 release + 새 PUBLISHED 워크플로 생성.
        result = await _publish_in_sync(workflow_id=workflow_id, released_by=user.user_id)
        # 원본 워크플로 row 도 갱신 (updated_at 만 — status 는 그대로 DRAFT).
        await session.refresh(workflow)
        return WorkflowStatusTransitionOut(
            workflow=WorkflowOut.model_validate(workflow),
            published_workflow=WorkflowOut.model_validate(result["published"]),
            release=PipelineReleaseOut.model_validate(result["release"]),
        )

    updated = await pipelines_repo.transition_workflow_status(
        session, workflow=workflow, target=body.status
    )
    await session.commit()
    return WorkflowStatusTransitionOut(workflow=WorkflowOut.model_validate(updated))


# ---------------------------------------------------------------------------
# sync helper (Phase 3.2.6 publish)
# ---------------------------------------------------------------------------
T = TypeVar("T")


async def _in_sync_session(fn: Callable[[Session], T]) -> T:
    def _wrapped() -> T:
        sm = get_sync_sessionmaker()
        with sm() as session:
            try:
                result = fn(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise

    return await asyncio.to_thread(_wrapped)


async def _publish_in_sync(*, workflow_id: int, released_by: int) -> dict[str, object]:
    """Sync session 으로 publish — async session 을 통한 동시 commit 충돌 회피.

    호출자(async 라우트) 가 같은 row 를 들고 있을 수 있어 publish 후 refresh 필요.
    """

    def _do(session: Session) -> dict[str, object]:
        # NotFoundError / ConflictError 는 그대로 throw — main.py 의 DomainError 핸들러가
        # 적절한 HTTP status (404 / 409) 로 변환.
        res = release_domain.publish_workflow(
            session, source_workflow_id=workflow_id, released_by=released_by
        )
        # expire_on_commit=False sessionmaker 라 session 종료 후에도 attrs 접근 가능.
        return {
            "published": res.published_workflow,
            "release": res.release,
            "diff": res.diff,
        }

    return await _in_sync_session(_do)


# ---------------------------------------------------------------------------
# Diff (Phase 3.2.6)
# ---------------------------------------------------------------------------
@router.get("/{workflow_id}/diff", response_model=WorkflowDiffOut)
async def diff_workflow(
    session: SessionDep,
    workflow_id: int,
    against: Annotated[int, Query(ge=1, description="비교 대상 workflow_id")],
) -> WorkflowDiffOut:
    """`against` 워크플로(=before) → workflow_id (=after) 방향 diff.

    예: `/v1/pipelines/{draft_id}/diff?against={published_id}` 면 published 가 before, draft 가
    after — 즉 prod 에 비해 새 DRAFT 가 무엇을 추가/제거/변경했는지를 보여준다.
    """

    def _do(s: Session) -> tuple[int, int, release_domain.WorkflowDiff]:
        _a, _b, diff = release_domain.diff_workflows(s, against, workflow_id)
        return against, workflow_id, diff

    before_id, after_id, diff = await _in_sync_session(_do)
    return WorkflowDiffOut(
        before_workflow_id=before_id,
        after_workflow_id=after_id,
        nodes_added=[NodeChangeOut(**vars(n)) for n in diff.nodes_added],
        nodes_removed=[NodeChangeOut(**vars(n)) for n in diff.nodes_removed],
        nodes_changed=[NodeChangeOut(**vars(n)) for n in diff.nodes_changed],
        edges_added=[EdgeChangeOut(**vars(e)) for e in diff.edges_added],
        edges_removed=[EdgeChangeOut(**vars(e)) for e in diff.edges_removed],
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
@router.post(
    "/{workflow_id}/runs",
    response_model=PipelineRunDetail,
    status_code=202,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def trigger_run(
    session: SessionDep,
    user: CurrentUserDep,
    workflow_id: int,
) -> PipelineRunDetail:
    """실행 트리거. workflow 가 PUBLISHED 여야 함.

    sync session 도메인이 pipeline_run + node_run 을 INSERT 하고 entry 노드들을
    READY 마킹. 이후 actor 가 비동기로 실행 (Phase 3.2.1 NOOP 만 — 즉시 SUCCESS
    가 아니라 READY 상태로 반환되며 worker 가 실제 처리).

    여기서는 actor enqueue 를 백그라운드에서 시도. 워커가 없어도(실 인프라 미가동)
    pipeline_run + node_run 메타는 이미 적재되어 운영 화면에서 확인 가능.
    """
    workflow = await pipelines_repo.get_workflow(session, workflow_id)
    if workflow is None:
        raise app_errors.NotFoundError(f"workflow {workflow_id} not found")
    if workflow.status != "PUBLISHED":
        raise app_errors.ValidationError(
            f"workflow {workflow_id} is {workflow.status} — must be PUBLISHED to run"
        )

    sm = get_sync_sessionmaker()
    pubsub = RedisPubSub.from_settings()
    try:
        with sm() as sync_session:
            try:
                started = runtime.start_pipeline_run(
                    sync_session,
                    workflow_id=workflow_id,
                    triggered_by_user_id=user.user_id,
                    pubsub=pubsub,
                )
            except ValueError as exc:
                raise app_errors.ValidationError(str(exc)) from exc
            sync_session.commit()
    finally:
        pubsub.close()

    # entry node 들을 actor 로 enqueue.
    try:
        from app.workers.pipeline_node_worker import process_node_event

        for node_run_id in started.ready_node_run_ids:
            process_node_event.send(
                event_id=f"node-run-{node_run_id}-attempt-1",
                node_run_id=node_run_id,
                run_date_iso=started.run_date.isoformat(),
            )
    except Exception:
        # broker 미가동 시에도 API 는 200 — 운영자가 화면에서 PENDING 확인 후 수동 재발송.
        pass

    detail = await pipelines_repo.get_pipeline_run_with_nodes(session, started.pipeline_run_id)
    if detail is None:
        raise app_errors.NotFoundError("pipeline_run lookup failed after start")
    pr, node_runs = detail
    return PipelineRunDetail(
        pipeline_run_id=pr.pipeline_run_id,
        workflow_id=pr.workflow_id,
        run_date=pr.run_date,
        status=pr.status,
        triggered_by=pr.triggered_by,
        started_at=pr.started_at,
        finished_at=pr.finished_at,
        error_message=pr.error_message,
        created_at=pr.created_at,
        node_runs=[NodeRunOut.model_validate(n) for n in node_runs],
    )


# ---------------------------------------------------------------------------
# Schedule / Backfill / Restart / Runs Search (Phase 3.2.7)
# ---------------------------------------------------------------------------
@router.patch(
    "/{workflow_id}/schedule",
    response_model=WorkflowOut,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def update_schedule(
    workflow_id: int,
    body: ScheduleUpdate,
) -> WorkflowOut:
    """cron 표현식 갱신 + 활성/비활성 토글. cron 비우면 자동 비활성화."""
    workflow = await _in_sync_session(
        lambda s: schedule_domain.set_schedule(
            s, workflow_id=workflow_id, cron=body.cron, enabled=body.enabled
        )
    )
    return WorkflowOut.model_validate(workflow)


@router.post(
    "/{workflow_id}/backfill",
    response_model=BackfillResponse,
    status_code=202,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def backfill_workflow(
    user: CurrentUserDep,
    workflow_id: int,
    body: BackfillRequest,
) -> BackfillResponse:
    """`[start_date, end_date]` 각 일자에 대해 PENDING pipeline_run 생성.

    이미 같은 (workflow_id, run_date) 가 있으면 그 ID 반환 (멱등). actor enqueue 는
    호출 후 백그라운드에서 시도 — 워커가 없으면 PENDING 으로 남는다.
    """
    try:
        result = await _in_sync_session(
            lambda s: schedule_domain.backfill(
                s,
                workflow_id=workflow_id,
                start_date=body.start_date,
                end_date=body.end_date,
                triggered_by_user_id=user.user_id,
            )
        )
    except ValueError as exc:
        raise app_errors.ValidationError(str(exc)) from exc

    return BackfillResponse(
        pipeline_run_ids=result.pipeline_run_ids,
        run_dates=result.run_dates,
    )


@router.post(
    "/runs/{pipeline_run_id}/restart",
    response_model=RestartResponse,
    status_code=202,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def restart_run(
    user: CurrentUserDep,
    pipeline_run_id: int,
    body: RestartRequest,
) -> RestartResponse:
    """기존 run 의 그래프를 새 run 으로 복제.

    `from_node_key` 가 지정되면 해당 노드의 ancestors 는 SUCCESS 로 시드, 그 노드 자체는
    READY. 미지정 시 entry 노드들이 READY (= start_pipeline_run 동등).

    응답으로 새 pipeline_run_id 반환 + 워커 actor enqueue 는 백그라운드 시도.
    """

    def _do(s: Session) -> schedule_domain.RestartResult:
        return schedule_domain.restart_run(
            s,
            pipeline_run_id=pipeline_run_id,
            from_node_key=body.from_node_key,
            triggered_by_user_id=user.user_id,
        )

    result = await _in_sync_session(_do)

    # entry 또는 from_node 들을 actor 로 enqueue (broker 미가동 시에도 API 는 200).
    try:
        from app.workers.pipeline_node_worker import process_node_event

        for node_run_id in result.ready_node_run_ids:
            process_node_event.send(
                event_id=f"node-run-{node_run_id}-attempt-1",
                node_run_id=node_run_id,
                run_date_iso=result.new_run_date.isoformat(),
            )
    except Exception:
        pass

    return RestartResponse(
        new_pipeline_run_id=result.new_pipeline_run_id,
        new_run_date=result.new_run_date,
        ready_node_run_ids=list(result.ready_node_run_ids),
        seeded_success_node_keys=list(result.seeded_success_node_keys),
    )


# ---------------------------------------------------------------------------
# DQ Gate (Phase 4.2.2) — ON_HOLD 검색 / 승인 / 반려.
# 라우트 순서 주의: `/runs/on_hold` 가 `/runs/{id}` 보다 먼저 등록되어야 함.
# ---------------------------------------------------------------------------
@router.get("/runs/on_hold", response_model=list[OnHoldRunOut])
async def list_on_hold_runs(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OnHoldRunOut]:
    """ON_HOLD 상태 pipeline_run 목록 + 각 run 의 실패 DQ 결과 미리보기."""
    from sqlalchemy import select

    from app.models.dq import QualityResult
    from app.models.run import NodeRun, PipelineRun

    def _do(s: Session) -> list[OnHoldRunOut]:
        runs = list(
            s.execute(
                select(PipelineRun)
                .where(PipelineRun.status == "ON_HOLD")
                .order_by(PipelineRun.pipeline_run_id.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        out: list[OnHoldRunOut] = []
        for pr in runs:
            failed_nodes = list(
                s.execute(
                    select(NodeRun)
                    .where(NodeRun.pipeline_run_id == pr.pipeline_run_id)
                    .where(NodeRun.run_date == pr.run_date)
                    .where(NodeRun.status == "FAILED")
                    .where(NodeRun.node_type == "DQ_CHECK")
                )
                .scalars()
                .all()
            )
            qrs = list(
                s.execute(
                    select(QualityResult)
                    .where(QualityResult.pipeline_run_id == pr.pipeline_run_id)
                    .where(QualityResult.status == "FAIL")
                    .order_by(QualityResult.created_at.desc())
                )
                .scalars()
                .all()
            )
            base = PipelineRunOut.model_validate(pr).model_dump()
            out.append(
                OnHoldRunOut(
                    **base,
                    failed_node_keys=[n.node_key for n in failed_nodes],
                    quality_results=[QualityResultOut.model_validate(q) for q in qrs],
                )
            )
        return out

    return await _in_sync_session(_do)


@router.post(
    "/runs/{pipeline_run_id}/hold/approve",
    response_model=HoldDecisionResponse,
    dependencies=[Depends(require_roles("APPROVER", "ADMIN"))],
)
async def approve_hold_endpoint(
    user: CurrentUserDep,
    pipeline_run_id: int,
    body: HoldDecisionRequest,
) -> HoldDecisionResponse:
    """ON_HOLD pipeline_run 을 승인하여 실행 재개. APPROVER/ADMIN 만 가능."""
    pubsub = RedisPubSub.from_settings()
    try:
        def _do(s: Session) -> dq_gate_domain.HoldDecisionResult:
            return dq_gate_domain.approve_hold(
                s,
                pipeline_run_id=pipeline_run_id,
                signer_user_id=user.user_id,
                reason=body.reason,
                pubsub=pubsub,
            )

        try:
            result = await _in_sync_session(_do)
        except ValueError as exc:
            raise app_errors.ValidationError(str(exc)) from exc
    finally:
        pubsub.close()

    # 후속 ready 노드 enqueue (broker 미가동 시에도 200).
    try:
        from app.workers.pipeline_node_worker import process_node_event

        for node_run_id in result.ready_node_run_ids:
            process_node_event.send(
                event_id=f"node-run-{node_run_id}-approve-{result.decision_id}",
                node_run_id=node_run_id,
                run_date_iso=result.run_date.isoformat(),
            )
    except Exception:
        pass

    return HoldDecisionResponse(
        decision_id=result.decision_id,
        pipeline_run_id=result.pipeline_run_id,
        run_date=result.run_date,
        decision="APPROVE",
        pipeline_status=result.pipeline_status,
        ready_node_run_ids=list(result.ready_node_run_ids),
        cancelled_node_run_ids=[],
        rollback_rows=0,
    )


@router.post(
    "/runs/{pipeline_run_id}/hold/reject",
    response_model=HoldDecisionResponse,
    dependencies=[Depends(require_roles("APPROVER", "ADMIN"))],
)
async def reject_hold_endpoint(
    user: CurrentUserDep,
    pipeline_run_id: int,
    body: HoldDecisionRequest,
) -> HoldDecisionResponse:
    """ON_HOLD pipeline_run 을 반려 → CANCELLED + stg rollback."""
    pubsub = RedisPubSub.from_settings()
    try:
        def _do(s: Session) -> dq_gate_domain.HoldDecisionResult:
            return dq_gate_domain.reject_hold(
                s,
                pipeline_run_id=pipeline_run_id,
                signer_user_id=user.user_id,
                reason=body.reason,
                pubsub=pubsub,
            )

        try:
            result = await _in_sync_session(_do)
        except ValueError as exc:
            raise app_errors.ValidationError(str(exc)) from exc
    finally:
        pubsub.close()

    return HoldDecisionResponse(
        decision_id=result.decision_id,
        pipeline_run_id=result.pipeline_run_id,
        run_date=result.run_date,
        decision="REJECT",
        pipeline_status=result.pipeline_status,
        ready_node_run_ids=[],
        cancelled_node_run_ids=list(result.cancelled_node_run_ids),
        rollback_rows=result.rollback_rows,
    )


@router.get("/runs/{pipeline_run_id}", response_model=PipelineRunDetail)
async def get_run(session: SessionDep, pipeline_run_id: int) -> PipelineRunDetail:
    detail = await pipelines_repo.get_pipeline_run_with_nodes(session, pipeline_run_id)
    if detail is None:
        raise app_errors.NotFoundError(f"pipeline_run {pipeline_run_id} not found")
    pr, node_runs = detail
    return PipelineRunDetail(
        pipeline_run_id=pr.pipeline_run_id,
        workflow_id=pr.workflow_id,
        run_date=pr.run_date,
        status=pr.status,
        triggered_by=pr.triggered_by,
        started_at=pr.started_at,
        finished_at=pr.finished_at,
        error_message=pr.error_message,
        created_at=pr.created_at,
        node_runs=[NodeRunOut.model_validate(n) for n in node_runs],
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _to_detail(
    graph: tuple[WorkflowDefinition, list[NodeDefinition], list[EdgeDefinition]],
) -> WorkflowDetail:
    workflow, nodes, edges = graph
    base = WorkflowOut.model_validate(workflow).model_dump()
    return WorkflowDetail(
        **base,
        nodes=[NodeOut.model_validate(n) for n in nodes],
        edges=[
            EdgeOut(
                edge_id=e.edge_id,
                from_node_id=e.from_node_id,
                to_node_id=e.to_node_id,
                condition_expr=e.condition_expr,
            )
            for e in edges
        ],
    )


__all__ = ["router"]
