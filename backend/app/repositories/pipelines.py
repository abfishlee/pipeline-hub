"""Pipeline / Workflow repository (Phase 3.2.1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import NodeRun, PipelineRun
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition


async def create_workflow(
    session: AsyncSession,
    *,
    name: str,
    version: int,
    description: str | None,
    created_by: int | None,
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> WorkflowDefinition:
    """nodes/edges 일괄 적재. nodes 의 node_key 가 edges 에서 참조된다."""
    workflow = WorkflowDefinition(
        name=name,
        version=version,
        description=description,
        status="DRAFT",
        created_by=created_by,
    )
    session.add(workflow)
    await session.flush()  # workflow_id 채움.

    by_key: dict[str, NodeDefinition] = {}
    for n in nodes:
        nd = NodeDefinition(
            workflow_id=workflow.workflow_id,
            node_key=str(n["node_key"]),
            node_type=str(n["node_type"]),
            config_json=dict(n.get("config_json") or {}),
            position_x=int(n.get("position_x") or 0),
            position_y=int(n.get("position_y") or 0),
        )
        session.add(nd)
        by_key[nd.node_key] = nd
    await session.flush()

    for e in edges:
        from_key = str(e["from_node_key"])
        to_key = str(e["to_node_key"])
        if from_key not in by_key:
            raise ValueError(f"edge references unknown node_key: {from_key}")
        if to_key not in by_key:
            raise ValueError(f"edge references unknown node_key: {to_key}")
        ed = EdgeDefinition(
            workflow_id=workflow.workflow_id,
            from_node_id=by_key[from_key].node_id,
            to_node_id=by_key[to_key].node_id,
            condition_expr=e.get("condition_expr"),
        )
        session.add(ed)
    await session.flush()
    return workflow


async def list_workflows(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[WorkflowDefinition]:
    stmt = select(WorkflowDefinition)
    if status:
        stmt = stmt.where(WorkflowDefinition.status == status)
    stmt = stmt.order_by(WorkflowDefinition.updated_at.desc()).limit(limit).offset(offset)
    return (await session.execute(stmt)).scalars().all()


async def get_workflow(session: AsyncSession, workflow_id: int) -> WorkflowDefinition | None:
    return await session.get(WorkflowDefinition, workflow_id)


async def get_workflow_with_graph(
    session: AsyncSession, workflow_id: int
) -> tuple[WorkflowDefinition, list[NodeDefinition], list[EdgeDefinition]] | None:
    workflow = await get_workflow(session, workflow_id)
    if workflow is None:
        return None
    nodes = (
        (
            await session.execute(
                select(NodeDefinition)
                .where(NodeDefinition.workflow_id == workflow_id)
                .order_by(NodeDefinition.node_id)
            )
        )
        .scalars()
        .all()
    )
    edges = (
        (
            await session.execute(
                select(EdgeDefinition)
                .where(EdgeDefinition.workflow_id == workflow_id)
                .order_by(EdgeDefinition.edge_id)
            )
        )
        .scalars()
        .all()
    )
    return workflow, list(nodes), list(edges)


async def replace_graph(
    session: AsyncSession,
    *,
    workflow: WorkflowDefinition,
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> None:
    """DRAFT 워크플로의 nodes/edges 를 통째로 교체. 기존 row CASCADE 삭제."""
    # 먼저 edges 제거 (FK 의존), 다음 nodes.
    from sqlalchemy import delete

    await session.execute(
        delete(EdgeDefinition).where(EdgeDefinition.workflow_id == workflow.workflow_id)
    )
    await session.execute(
        delete(NodeDefinition).where(NodeDefinition.workflow_id == workflow.workflow_id)
    )
    await session.flush()

    by_key: dict[str, NodeDefinition] = {}
    for n in nodes:
        nd = NodeDefinition(
            workflow_id=workflow.workflow_id,
            node_key=str(n["node_key"]),
            node_type=str(n["node_type"]),
            config_json=dict(n.get("config_json") or {}),
            position_x=int(n.get("position_x") or 0),
            position_y=int(n.get("position_y") or 0),
        )
        session.add(nd)
        by_key[nd.node_key] = nd
    await session.flush()
    for e in edges:
        from_key = str(e["from_node_key"])
        to_key = str(e["to_node_key"])
        if from_key not in by_key or to_key not in by_key:
            raise ValueError(f"edge references unknown node_key: {from_key}/{to_key}")
        session.add(
            EdgeDefinition(
                workflow_id=workflow.workflow_id,
                from_node_id=by_key[from_key].node_id,
                to_node_id=by_key[to_key].node_id,
                condition_expr=e.get("condition_expr"),
            )
        )
    await session.flush()


async def transition_workflow_status(
    session: AsyncSession, *, workflow: WorkflowDefinition, target: str
) -> WorkflowDefinition:
    workflow.status = target
    workflow.updated_at = datetime.now(UTC)
    if target == "PUBLISHED":
        workflow.published_at = datetime.now(UTC)
    await session.flush()
    return workflow


async def get_pipeline_run_with_nodes(
    session: AsyncSession, pipeline_run_id: int
) -> tuple[PipelineRun, list[NodeRun]] | None:
    pr = (
        await session.execute(
            select(PipelineRun).where(PipelineRun.pipeline_run_id == pipeline_run_id)
        )
    ).scalar_one_or_none()
    if pr is None:
        return None
    siblings = (
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.pipeline_run_id == pipeline_run_id)
                .where(NodeRun.run_date == pr.run_date)
                .order_by(NodeRun.node_run_id)
            )
        )
        .scalars()
        .all()
    )
    return pr, list(siblings)


__all__ = [
    "create_workflow",
    "get_pipeline_run_with_nodes",
    "get_workflow",
    "get_workflow_with_graph",
    "list_workflows",
    "replace_graph",
    "transition_workflow_status",
]
