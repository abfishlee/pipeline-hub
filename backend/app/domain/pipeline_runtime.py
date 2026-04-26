"""Pipeline Runtime — 자체 DAG 실행기 (Phase 3.2.1).

흐름:
  1. `start_pipeline_run(workflow_id, triggered_by)` —
     - workflow 의 nodes/edges 조회 → Kahn 토폴로지 정렬 (cycle 검출).
     - `run.pipeline_run` 1건 + `run.node_run` N건(모두 PENDING) 일괄 INSERT.
     - 입력이 없는 entry node 들을 READY 로 전이 → actor enqueue.
  2. `complete_node(node_run_id, status, error)` (워커 actor 호출):
     - 해당 node_run 종결 마킹 + Pub/Sub publish.
     - 같은 pipeline 의 후속 노드 중 *모든 입력이 SUCCESS* 인 것을 READY 로 전이.
     - 또 dispatch.
  3. 모든 노드가 종결되면 `pipeline_run` 도 종결 (전부 SUCCESS → SUCCESS,
     하나라도 FAILED → FAILED).

Phase 3.2.1 한정:
  - 노드 타입은 NOOP 만 즉시 SUCCESS. 다른 type 은 Phase 3.2.2 에서 actor 가 실제
    노드 로직을 호출 — 본 모듈은 그저 "actor 가 complete_node 를 호출하면 그래프
    를 진행시키는" 책임만 가진다.
  - 토폴로지 정렬은 Kahn (in-degree 0 부터). cycle 시 ValueError → API 가 422.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import metrics
from app.core.events import RedisPubSub
from app.models.run import NodeRun, PipelineRun
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition

PUBSUB_CHANNEL_PREFIX = "pipeline"


@dataclass(slots=True, frozen=True)
class StartedRun:
    pipeline_run_id: int
    run_date: date
    node_run_count: int
    ready_node_run_ids: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class NodeCompletion:
    pipeline_run_id: int
    run_date: date
    pipeline_status: str
    next_ready_node_run_ids: tuple[int, ...]


def _channel(pipeline_run_id: int) -> str:
    return f"{PUBSUB_CHANNEL_PREFIX}:{pipeline_run_id}"


def _topo_sort(
    nodes: Sequence[NodeDefinition],
    edges: Sequence[EdgeDefinition],
) -> list[NodeDefinition]:
    """Kahn 토폴로지 정렬. cycle 시 `ValueError`."""
    by_id = {n.node_id: n for n in nodes}
    in_degree: dict[int, int] = {n.node_id: 0 for n in nodes}
    successors: dict[int, list[int]] = defaultdict(list)
    for e in edges:
        if e.from_node_id not in by_id or e.to_node_id not in by_id:
            raise ValueError(
                f"edge {e.edge_id} references unknown node " f"({e.from_node_id} → {e.to_node_id})"
            )
        successors[e.from_node_id].append(e.to_node_id)
        in_degree[e.to_node_id] += 1

    queue: deque[int] = deque(sorted(nid for nid, deg in in_degree.items() if deg == 0))
    ordered: list[NodeDefinition] = []
    while queue:
        nid = queue.popleft()
        ordered.append(by_id[nid])
        for nxt in sorted(successors[nid]):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(nodes):
        raise ValueError("workflow contains a cycle — cannot order nodes")
    return ordered


def _entry_node_ids(nodes: Sequence[NodeDefinition], edges: Sequence[EdgeDefinition]) -> list[int]:
    has_incoming = {e.to_node_id for e in edges}
    return [n.node_id for n in nodes if n.node_id not in has_incoming]


def _publish_state(
    pubsub: RedisPubSub | None,
    *,
    pipeline_run: PipelineRun,
    node_run: NodeRun,
    workflow_id: int,
) -> None:
    if pubsub is None:
        return
    payload = {
        "pipeline_run_id": pipeline_run.pipeline_run_id,
        "run_date": pipeline_run.run_date.isoformat(),
        "workflow_id": workflow_id,
        "node_run_id": node_run.node_run_id,
        "node_key": node_run.node_key,
        "node_type": node_run.node_type,
        "status": node_run.status,
        "attempt_no": node_run.attempt_no,
        "error_message": node_run.error_message,
    }
    pubsub.publish(_channel(pipeline_run.pipeline_run_id), payload)


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------
def start_pipeline_run(
    session: Session,
    *,
    workflow_id: int,
    triggered_by_user_id: int | None,
    pubsub: RedisPubSub | None = None,
) -> StartedRun:
    workflow = session.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.workflow_id == workflow_id)
    ).scalar_one_or_none()
    if workflow is None:
        raise ValueError(f"workflow_id={workflow_id} not found")
    if workflow.status != "PUBLISHED":
        raise ValueError(f"workflow {workflow_id} is not PUBLISHED (status={workflow.status})")

    nodes = (
        session.execute(
            select(NodeDefinition)
            .where(NodeDefinition.workflow_id == workflow_id)
            .order_by(NodeDefinition.node_id)
        )
        .scalars()
        .all()
    )
    if not nodes:
        raise ValueError(f"workflow {workflow_id} has no nodes")
    edges = (
        session.execute(select(EdgeDefinition).where(EdgeDefinition.workflow_id == workflow_id))
        .scalars()
        .all()
    )

    # cycle 검증 — 결과는 사용 안 하지만 던지면 caller 가 422 로 변환.
    _topo_sort(nodes, edges)

    today = datetime.now(UTC).date()
    pr = PipelineRun(
        workflow_id=workflow_id,
        run_date=today,
        status="RUNNING",
        triggered_by=triggered_by_user_id,
        started_at=datetime.now(UTC),
    )
    session.add(pr)
    session.flush()

    metrics.pipeline_runs_total.labels(status="RUNNING").inc()

    new_node_runs: list[NodeRun] = []
    for n in nodes:
        nr = NodeRun(
            pipeline_run_id=pr.pipeline_run_id,
            run_date=pr.run_date,
            node_definition_id=n.node_id,
            node_key=n.node_key,
            node_type=n.node_type,
            status="PENDING",
        )
        session.add(nr)
        new_node_runs.append(nr)
    session.flush()

    # entry 노드를 READY 로 전이.
    entry_ids = set(_entry_node_ids(nodes, edges))
    ready_node_run_ids: list[int] = []
    for nr in new_node_runs:
        if nr.node_definition_id in entry_ids:
            nr.status = "READY"
            ready_node_run_ids.append(nr.node_run_id)
            _publish_state(pubsub, pipeline_run=pr, node_run=nr, workflow_id=workflow_id)

    return StartedRun(
        pipeline_run_id=pr.pipeline_run_id,
        run_date=pr.run_date,
        node_run_count=len(new_node_runs),
        ready_node_run_ids=tuple(ready_node_run_ids),
    )


# ---------------------------------------------------------------------------
# complete + dispatch
# ---------------------------------------------------------------------------
def _sibling_node_runs(session: Session, pipeline_run_id: int, run_date: date) -> list[NodeRun]:
    return list(
        session.execute(
            select(NodeRun)
            .where(NodeRun.pipeline_run_id == pipeline_run_id)
            .where(NodeRun.run_date == run_date)
        )
        .scalars()
        .all()
    )


def _ready_check(
    target: NodeRun, sibling_by_def: dict[int, NodeRun], edges: Sequence[EdgeDefinition]
) -> bool:
    """target 의 모든 입력 노드가 SUCCESS 면 True."""
    upstream = [e.from_node_id for e in edges if e.to_node_id == target.node_definition_id]
    if not upstream:
        return target.status == "PENDING"  # entry 인데 누락된 경우.
    for upstream_id in upstream:
        upstream_nr = sibling_by_def.get(upstream_id)
        if upstream_nr is None or upstream_nr.status != "SUCCESS":
            return False
    return True


def mark_node_running(
    session: Session,
    *,
    node_run_id: int,
    pubsub: RedisPubSub | None = None,
) -> NodeRun:
    nr = session.get(NodeRun, node_run_id)
    if nr is None:
        raise ValueError(f"node_run {node_run_id} not found")
    if nr.status not in ("READY", "PENDING"):
        # 이미 실행 중이거나 종결 — idempotent return.
        return nr
    nr.status = "RUNNING"
    nr.attempt_no += 1
    nr.started_at = datetime.now(UTC)
    pr = session.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_run_id == nr.pipeline_run_id)
        .where(PipelineRun.run_date == nr.run_date)
    ).scalar_one()
    _publish_state(pubsub, pipeline_run=pr, node_run=nr, workflow_id=pr.workflow_id)
    return nr


def complete_node(
    session: Session,
    *,
    node_run_id: int,
    status: str,
    error_message: str | None = None,
    output_json: dict[str, Any] | None = None,
    pubsub: RedisPubSub | None = None,
) -> NodeCompletion:
    if status not in ("SUCCESS", "FAILED", "SKIPPED"):
        raise ValueError(f"invalid terminal status: {status}")

    nr = session.get(NodeRun, node_run_id)
    if nr is None:
        raise ValueError(f"node_run {node_run_id} not found")

    pr = session.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_run_id == nr.pipeline_run_id)
        .where(PipelineRun.run_date == nr.run_date)
    ).scalar_one()

    nr.status = status
    nr.error_message = error_message
    nr.output_json = output_json
    nr.finished_at = datetime.now(UTC)
    metrics.pipeline_node_runs_total.labels(node_type=nr.node_type, status=status).inc()
    _publish_state(pubsub, pipeline_run=pr, node_run=nr, workflow_id=pr.workflow_id)

    # Phase 4.2.2 — DQ_CHECK 노드가 ERROR/BLOCK 으로 실패하면 dq_hold=True 로 신호.
    # 이 경우 cascade SKIPPED 를 차단하고 pipeline_run.status = ON_HOLD 로 전이.
    dq_hold = bool(status == "FAILED" and (output_json or {}).get("dq_hold"))

    # 후속 노드 dispatch.
    siblings = _sibling_node_runs(session, nr.pipeline_run_id, nr.run_date)
    sibling_by_def = {s.node_definition_id: s for s in siblings}
    edges = (
        session.execute(select(EdgeDefinition).where(EdgeDefinition.workflow_id == pr.workflow_id))
        .scalars()
        .all()
    )

    next_ready: list[int] = []
    if status == "SUCCESS":
        # 후속 노드들 중 READY 가능 한지 확인.
        downstream = [e.to_node_id for e in edges if e.from_node_id == nr.node_definition_id]
        for d_id in downstream:
            cand = sibling_by_def.get(d_id)
            if cand is None or cand.status != "PENDING":
                continue
            if _ready_check(cand, sibling_by_def, edges):
                cand.status = "READY"
                next_ready.append(cand.node_run_id)
                _publish_state(pubsub, pipeline_run=pr, node_run=cand, workflow_id=pr.workflow_id)
    elif status == "FAILED" and not dq_hold:
        # 도달 가능한 모든 PENDING/READY 후속 노드를 SKIPPED 로 마킹.
        # (Kahn 진행 차단 — 단순 정책: from 이 FAILED 면 모든 도달 가능 후속 SKIP)
        adj: dict[int, list[int]] = defaultdict(list)
        for e in edges:
            adj[e.from_node_id].append(e.to_node_id)
        visited: set[int] = set()
        queue: deque[int] = deque([nr.node_definition_id])
        while queue:
            nid = queue.popleft()
            for d in adj.get(nid, []):
                if d in visited:
                    continue
                visited.add(d)
                cand = sibling_by_def.get(d)
                if cand and cand.status in ("PENDING", "READY"):
                    cand.status = "SKIPPED"
                    cand.finished_at = datetime.now(UTC)
                    metrics.pipeline_node_runs_total.labels(
                        node_type=cand.node_type, status="SKIPPED"
                    ).inc()
                    _publish_state(
                        pubsub, pipeline_run=pr, node_run=cand, workflow_id=pr.workflow_id
                    )
                    queue.append(d)

    # Phase 4.2.2 — DQ hold 시 pipeline_run.status = ON_HOLD, 종결 판정 skip.
    if dq_hold:
        pr.status = "ON_HOLD"
        metrics.pipeline_runs_total.labels(status="ON_HOLD").inc()
        # outbox: NOTIFY 이벤트 (notify_worker 가 Slack/Email 발송).
        from app.models.run import EventOutbox

        session.add(
            EventOutbox(
                aggregate_type="pipeline_run",
                aggregate_id=str(pr.pipeline_run_id),
                event_type="pipeline_run.on_hold",
                payload_json={
                    "pipeline_run_id": pr.pipeline_run_id,
                    "run_date": pr.run_date.isoformat(),
                    "workflow_id": pr.workflow_id,
                    "node_run_id": nr.node_run_id,
                    "node_key": nr.node_key,
                    "error_message": error_message,
                    "quality_result_ids": (output_json or {}).get("quality_result_ids", []),
                },
            )
        )
        return NodeCompletion(
            pipeline_run_id=pr.pipeline_run_id,
            run_date=pr.run_date,
            pipeline_status="ON_HOLD",
            next_ready_node_run_ids=tuple(next_ready),
        )

    # pipeline 종결 판정.
    siblings = _sibling_node_runs(session, nr.pipeline_run_id, nr.run_date)
    terminal = {"SUCCESS", "FAILED", "SKIPPED", "CANCELLED"}
    all_terminal = all(s.status in terminal for s in siblings)
    pipeline_status = pr.status
    if all_terminal:
        any_failed = any(s.status == "FAILED" for s in siblings)
        pr.status = "FAILED" if any_failed else "SUCCESS"
        pr.finished_at = datetime.now(UTC)
        if pr.started_at:
            metrics.pipeline_run_duration_seconds.observe(
                max(0.0, (pr.finished_at - pr.started_at).total_seconds())
            )
        metrics.pipeline_runs_total.labels(status=pr.status).inc()
        pipeline_status = pr.status

    return NodeCompletion(
        pipeline_run_id=pr.pipeline_run_id,
        run_date=pr.run_date,
        pipeline_status=pipeline_status,
        next_ready_node_run_ids=tuple(next_ready),
    )


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------
def cancel_pipeline_run(
    session: Session,
    *,
    pipeline_run_id: int,
    run_date: date,
    user_id: int | None,
    pubsub: RedisPubSub | None = None,
) -> PipelineRun:
    pr = session.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_run_id == pipeline_run_id)
        .where(PipelineRun.run_date == run_date)
    ).scalar_one_or_none()
    if pr is None:
        raise ValueError(f"pipeline_run {pipeline_run_id} not found")
    if pr.status not in ("PENDING", "RUNNING"):
        return pr
    pr.status = "CANCELLED"
    pr.finished_at = datetime.now(UTC)
    pr.error_message = f"cancelled by user_id={user_id}"
    siblings = _sibling_node_runs(session, pipeline_run_id, run_date)
    for s in siblings:
        if s.status in ("PENDING", "READY", "RUNNING"):
            s.status = "CANCELLED"
            s.finished_at = datetime.now(UTC)
            metrics.pipeline_node_runs_total.labels(node_type=s.node_type, status="CANCELLED").inc()
            _publish_state(pubsub, pipeline_run=pr, node_run=s, workflow_id=pr.workflow_id)
    metrics.pipeline_runs_total.labels(status="CANCELLED").inc()
    return pr


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def get_pipeline_run_with_nodes(
    session: Session, *, pipeline_run_id: int
) -> tuple[PipelineRun, list[NodeRun]] | None:
    pr = session.execute(
        select(PipelineRun).where(PipelineRun.pipeline_run_id == pipeline_run_id)
    ).scalar_one_or_none()
    if pr is None:
        return None
    siblings = _sibling_node_runs(session, pr.pipeline_run_id, pr.run_date)
    return pr, siblings


def count_terminal_pipelines(session: Session) -> int:
    """Test 헬퍼 — 종결 pipeline 수."""
    return int(
        session.execute(
            select(func.count(PipelineRun.pipeline_run_id)).where(
                PipelineRun.status.in_(("SUCCESS", "FAILED", "CANCELLED"))
            )
        ).scalar_one()
        or 0
    )


__all__ = [
    "PUBSUB_CHANNEL_PREFIX",
    "NodeCompletion",
    "StartedRun",
    "cancel_pipeline_run",
    "complete_node",
    "count_terminal_pipelines",
    "get_pipeline_run_with_nodes",
    "mark_node_running",
    "start_pipeline_run",
]
