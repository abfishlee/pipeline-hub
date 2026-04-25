"""파이프라인 배포 도메인 — DRAFT → PUBLISHED 전환의 모든 부수 효과 (Phase 3.2.6).

Phase 3.2.1 의 단순 status 전환 (`transition_workflow_status`) 은 이름에 충실하게 같은
row 의 status 만 바꿨다. 이 모듈은 그 위에 "버전 자동 증가 + 그래프 스냅샷 복제 + diff
계산 + release 이력 영속" 을 얹는다.

핵심 결정
---------
1. **PUBLISHED 는 새 row** — DRAFT 와 같은 `name` 을 공유하되 `version` (= version_no) 만
   max+1 로 증가. 기존 DRAFT 는 status="DRAFT" 그대로 유지되어 사용자가 계속 편집 가능.
   같은 (name, version) UNIQUE 가 자연스러운 안전장치.
2. **그래프 freeze** — 이전 phase 처럼 PUBLISHED 의 `node_definition` / `edge_definition`
   을 복제해 둔다. 향후 사용자가 같은 DRAFT 를 또 편집해도 PUBLISHED 는 영향 없음.
3. **diff 는 node_key 기준** — 같은 node_key 가 양쪽에 있으면 'changed', 한쪽에만 있으면
   'added'/'removed'. config_json 비교는 정렬된 JSON 표현(dict_keys 순서 무관) 으로.
4. **release row 는 별 트랜잭션 안에서 함께 커밋** — 호출자(API) 가 sync session 으로
   단일 commit 처리. 부분 실패가 있으면 rollback.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.wf import (
    EdgeDefinition,
    NodeDefinition,
    PipelineRelease,
    WorkflowDefinition,
)

# ---------------------------------------------------------------------------
# Diff 결과 타입
# ---------------------------------------------------------------------------


@dataclass
class NodeChange:
    node_key: str
    node_type: str | None = None
    config_before: dict[str, Any] | None = None
    config_after: dict[str, Any] | None = None


@dataclass
class EdgeChange:
    from_node_key: str
    to_node_key: str


@dataclass
class WorkflowDiff:
    nodes_added: list[NodeChange] = field(default_factory=list)
    nodes_removed: list[NodeChange] = field(default_factory=list)
    nodes_changed: list[NodeChange] = field(default_factory=list)
    edges_added: list[EdgeChange] = field(default_factory=list)
    edges_removed: list[EdgeChange] = field(default_factory=list)

    def summary(self) -> dict[str, list[str]]:
        """release.change_summary 에 저장하는 축약 형태 — node_key 만."""
        return {
            "added": [n.node_key for n in self.nodes_added],
            "removed": [n.node_key for n in self.nodes_removed],
            "changed": [n.node_key for n in self.nodes_changed],
            "edges_added": [f"{e.from_node_key}->{e.to_node_key}" for e in self.edges_added],
            "edges_removed": [f"{e.from_node_key}->{e.to_node_key}" for e in self.edges_removed],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _json_canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _node_to_dict(n: NodeDefinition) -> dict[str, Any]:
    return {
        "node_key": n.node_key,
        "node_type": n.node_type,
        "config_json": dict(n.config_json or {}),
        "position_x": int(n.position_x or 0),
        "position_y": int(n.position_y or 0),
    }


def _edge_pair(e: EdgeDefinition, by_id: dict[int, str]) -> tuple[str, str]:
    return by_id[e.from_node_id], by_id[e.to_node_id]


def _edge_to_dict(e: EdgeDefinition, by_id: dict[int, str]) -> dict[str, Any]:
    src, tgt = _edge_pair(e, by_id)
    return {
        "from_node_key": src,
        "to_node_key": tgt,
        "condition_expr": e.condition_expr,
    }


def _load_graph(
    session: Session, workflow_id: int
) -> tuple[WorkflowDefinition, list[NodeDefinition], list[EdgeDefinition]]:
    workflow = session.get(WorkflowDefinition, workflow_id)
    if workflow is None:
        raise NotFoundError(f"workflow {workflow_id} not found")
    nodes = list(
        session.execute(
            select(NodeDefinition)
            .where(NodeDefinition.workflow_id == workflow_id)
            .order_by(NodeDefinition.node_id)
        ).scalars()
    )
    edges = list(
        session.execute(
            select(EdgeDefinition)
            .where(EdgeDefinition.workflow_id == workflow_id)
            .order_by(EdgeDefinition.edge_id)
        ).scalars()
    )
    return workflow, nodes, edges


# ---------------------------------------------------------------------------
# Diff 계산
# ---------------------------------------------------------------------------
def compute_diff(
    before_nodes: Sequence[NodeDefinition],
    before_edges: Sequence[EdgeDefinition],
    after_nodes: Sequence[NodeDefinition],
    after_edges: Sequence[EdgeDefinition],
) -> WorkflowDiff:
    """node_key 기준 added/removed/changed + edge pair 기준 added/removed."""
    before_by_key = {n.node_key: n for n in before_nodes}
    after_by_key = {n.node_key: n for n in after_nodes}

    diff = WorkflowDiff()

    # nodes
    for key, n in after_by_key.items():
        if key not in before_by_key:
            diff.nodes_added.append(
                NodeChange(
                    node_key=key, node_type=n.node_type, config_after=dict(n.config_json or {})
                )
            )
        else:
            old = before_by_key[key]
            if old.node_type != n.node_type or _json_canonical(old.config_json) != _json_canonical(
                n.config_json
            ):
                diff.nodes_changed.append(
                    NodeChange(
                        node_key=key,
                        node_type=n.node_type,
                        config_before=dict(old.config_json or {}),
                        config_after=dict(n.config_json or {}),
                    )
                )
    for key, n in before_by_key.items():
        if key not in after_by_key:
            diff.nodes_removed.append(
                NodeChange(
                    node_key=key, node_type=n.node_type, config_before=dict(n.config_json or {})
                )
            )

    # edges (node_id 가 다른 row 라 직접 비교 불가 → key 쌍으로 정규화)
    before_node_ids = {n.node_id: n.node_key for n in before_nodes}
    after_node_ids = {n.node_id: n.node_key for n in after_nodes}

    before_pairs = {_edge_pair(e, before_node_ids) for e in before_edges}
    after_pairs = {_edge_pair(e, after_node_ids) for e in after_edges}

    for src, tgt in after_pairs - before_pairs:
        diff.edges_added.append(EdgeChange(from_node_key=src, to_node_key=tgt))
    for src, tgt in before_pairs - after_pairs:
        diff.edges_removed.append(EdgeChange(from_node_key=src, to_node_key=tgt))

    return diff


def diff_workflows(
    session: Session, workflow_a_id: int, workflow_b_id: int
) -> tuple[WorkflowDefinition, WorkflowDefinition, WorkflowDiff]:
    """A → B 방향 diff. (A 는 'before', B 는 'after')."""
    a_wf, a_nodes, a_edges = _load_graph(session, workflow_a_id)
    b_wf, b_nodes, b_edges = _load_graph(session, workflow_b_id)
    return a_wf, b_wf, compute_diff(a_nodes, a_edges, b_nodes, b_edges)


# ---------------------------------------------------------------------------
# Publish — 새 PUBLISHED 워크플로 + release row
# ---------------------------------------------------------------------------
@dataclass
class PublishResult:
    release: PipelineRelease
    published_workflow: WorkflowDefinition
    nodes: list[NodeDefinition]
    edges: list[EdgeDefinition]
    diff: WorkflowDiff


def publish_workflow(
    session: Session, *, source_workflow_id: int, released_by: int | None
) -> PublishResult:
    """DRAFT 를 freeze → 새 PUBLISHED row 를 만들어 version_no max+1 으로 적재.

    원본 DRAFT 는 그대로 둔다 (status 변경 없음). 사용자가 계속 편집 가능.

    Raises:
      NotFoundError — workflow_id 미존재
      ConflictError — DRAFT 가 아니거나 nodes 가 0개
    """
    src_wf, src_nodes, src_edges = _load_graph(session, source_workflow_id)
    if src_wf.status != "DRAFT":
        raise ConflictError(
            f"workflow {source_workflow_id} is {src_wf.status} — only DRAFT can be published"
        )
    if not src_nodes:
        raise ConflictError("cannot publish empty workflow (need ≥1 node)")

    # 같은 name 의 max(version) → +1
    next_version_no = (
        session.execute(
            select(func.coalesce(func.max(WorkflowDefinition.version), 0)).where(
                WorkflowDefinition.name == src_wf.name
            )
        ).scalar_one()
        + 1
    )

    now = datetime.now(UTC)
    published = WorkflowDefinition(
        name=src_wf.name,
        version=next_version_no,
        description=src_wf.description,
        status="PUBLISHED",
        created_by=released_by,
        published_at=now,
    )
    session.add(published)
    session.flush()  # workflow_id

    # 이전 최신 PUBLISHED 를 diff 비교 대상으로 — 동일 name 의 PUBLISHED 중 version 최댓값.
    prev_published_id = session.execute(
        select(WorkflowDefinition.workflow_id)
        .where(
            WorkflowDefinition.name == src_wf.name,
            WorkflowDefinition.status == "PUBLISHED",
            WorkflowDefinition.workflow_id != published.workflow_id,
        )
        .order_by(WorkflowDefinition.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    new_nodes: list[NodeDefinition] = []
    new_edges: list[EdgeDefinition] = []
    by_key: dict[str, NodeDefinition] = {}

    for n in src_nodes:
        nd = NodeDefinition(
            workflow_id=published.workflow_id,
            node_key=n.node_key,
            node_type=n.node_type,
            config_json=dict(n.config_json or {}),
            position_x=n.position_x,
            position_y=n.position_y,
        )
        session.add(nd)
        new_nodes.append(nd)
        by_key[nd.node_key] = nd
    session.flush()

    src_node_id_to_key = {n.node_id: n.node_key for n in src_nodes}
    for e in src_edges:
        src_key = src_node_id_to_key[e.from_node_id]
        tgt_key = src_node_id_to_key[e.to_node_id]
        ed = EdgeDefinition(
            workflow_id=published.workflow_id,
            from_node_id=by_key[src_key].node_id,
            to_node_id=by_key[tgt_key].node_id,
            condition_expr=e.condition_expr,
        )
        session.add(ed)
        new_edges.append(ed)
    session.flush()

    # diff: prev_published vs new published.
    if prev_published_id is not None:
        _, prev_nodes, prev_edges = _load_graph(session, prev_published_id)
        diff = compute_diff(prev_nodes, prev_edges, new_nodes, new_edges)
    else:
        diff = WorkflowDiff(
            nodes_added=[
                NodeChange(
                    node_key=n.node_key,
                    node_type=n.node_type,
                    config_after=dict(n.config_json or {}),
                )
                for n in new_nodes
            ],
            edges_added=[
                EdgeChange(from_node_key=k1, to_node_key=k2)
                for k1, k2 in (
                    _edge_pair(e, {n.node_id: n.node_key for n in new_nodes}) for e in new_edges
                )
            ],
        )

    new_node_ids = {n.node_id: n.node_key for n in new_nodes}
    release = PipelineRelease(
        workflow_name=src_wf.name,
        version_no=next_version_no,
        source_workflow_id=src_wf.workflow_id,
        released_workflow_id=published.workflow_id,
        released_by=released_by,
        released_at=now,
        change_summary=diff.summary(),
        nodes_snapshot=[_node_to_dict(n) for n in new_nodes],
        edges_snapshot=[_edge_to_dict(e, new_node_ids) for e in new_edges],
    )
    session.add(release)
    session.flush()

    return PublishResult(
        release=release,
        published_workflow=published,
        nodes=new_nodes,
        edges=new_edges,
        diff=diff,
    )


def list_releases(
    session: Session, *, workflow_name: str | None = None, limit: int = 50
) -> list[PipelineRelease]:
    stmt = select(PipelineRelease)
    if workflow_name:
        stmt = stmt.where(PipelineRelease.workflow_name == workflow_name)
    stmt = stmt.order_by(PipelineRelease.released_at.desc()).limit(limit)
    return list(session.execute(stmt).scalars())


__all__ = [
    "EdgeChange",
    "NodeChange",
    "PublishResult",
    "WorkflowDiff",
    "compute_diff",
    "diff_workflows",
    "list_releases",
    "publish_workflow",
]
