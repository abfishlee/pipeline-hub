"""HTTP 경계 — `/v1/pipelines` (Visual ETL Designer 워크플로 CRUD + 실행).

Phase 3.2.1 Pipeline Runtime. 실행 트리거는 sync session 으로 도메인 호출
(start_pipeline_run 이 즉시 entry node 들을 enqueue). 노드 실행은 dramatiq actor.

권한: ADMIN / APPROVER (워크플로 PUBLISH/실행 권한이 mart 쓰기와 동등). 조회는 OPERATOR
이상 허용.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core import errors as app_errors
from app.core.events import RedisPubSub
from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, SessionDep, require_roles
from app.domain import pipeline_runtime as runtime
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition
from app.repositories import pipelines as pipelines_repo
from app.schemas.pipelines import (
    EdgeOut,
    NodeOut,
    NodeRunOut,
    PipelineRunDetail,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowOut,
    WorkflowPatch,
    WorkflowStatus,
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
    response_model=WorkflowOut,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def transition_status(
    session: SessionDep,
    workflow_id: int,
    body: WorkflowStatusUpdate,
) -> WorkflowOut:
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
    updated = await pipelines_repo.transition_workflow_status(
        session, workflow=workflow, target=body.status
    )
    await session.commit()
    return WorkflowOut.model_validate(updated)


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
