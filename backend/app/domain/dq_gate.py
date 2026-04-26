"""DQ Gate (Phase 4.2.2) — ON_HOLD pipeline_run 의 승인/반려 처리.

흐름:
  1. DQ_CHECK ERROR/BLOCK 실패 → `pipeline_runtime.complete_node` 가 dq_hold 검출
     → pipeline_run.status = ON_HOLD + outbox `pipeline_run.on_hold` 발행.
  2. APPROVER 가 `approve_hold` 호출:
     - hold_decision INSERT (decision='APPROVE')
     - pipeline_run.status = RUNNING
     - 실패한 DQ_CHECK 노드의 *직접 후속* 노드를 READY 로 마킹 → caller 가 enqueue.
     - outbox `pipeline_run.hold_approved`.
  3. APPROVER 가 `reject_hold` 호출:
     - hold_decision INSERT (decision='REJECT')
     - pipeline_run.status = CANCELLED, finished_at = now()
     - 잔여 PENDING/READY/RUNNING node_run 모두 CANCELLED.
     - stg.standard_record / stg.price_observation rollback (load_batch_id = pipeline_run_id).
     - outbox `pipeline_run.hold_rejected`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import metrics
from app.core.events import RedisPubSub
from app.domain.pipeline_runtime import _publish_state, _sibling_node_runs
from app.models.run import EventOutbox, HoldDecision, NodeRun, PipelineRun
from app.models.wf import EdgeDefinition


@dataclass(slots=True, frozen=True)
class HoldDecisionResult:
    decision_id: int
    pipeline_run_id: int
    run_date: date
    decision: str
    pipeline_status: str
    ready_node_run_ids: tuple[int, ...]
    cancelled_node_run_ids: tuple[int, ...]
    rollback_rows: int


def _get_on_hold_run(session: Session, pipeline_run_id: int) -> PipelineRun:
    pr = session.execute(
        select(PipelineRun).where(PipelineRun.pipeline_run_id == pipeline_run_id)
    ).scalar_one_or_none()
    if pr is None:
        raise ValueError(f"pipeline_run {pipeline_run_id} not found")
    if pr.status != "ON_HOLD":
        raise ValueError(
            f"pipeline_run {pipeline_run_id} is not ON_HOLD (status={pr.status})"
        )
    return pr


def _failed_dq_node_runs(
    session: Session, *, pipeline_run_id: int, run_date: date
) -> list[NodeRun]:
    return list(
        session.execute(
            select(NodeRun)
            .where(NodeRun.pipeline_run_id == pipeline_run_id)
            .where(NodeRun.run_date == run_date)
            .where(NodeRun.status == "FAILED")
            .where(NodeRun.node_type == "DQ_CHECK")
        )
        .scalars()
        .all()
    )


def _quality_result_ids_from_dq_nodes(dq_nodes: Sequence[NodeRun]) -> list[int]:
    ids: list[int] = []
    for n in dq_nodes:
        out = n.output_json or {}
        for qid in out.get("quality_result_ids", []) or []:
            try:
                ids.append(int(qid))
            except (TypeError, ValueError):
                continue
    return ids


def approve_hold(
    session: Session,
    *,
    pipeline_run_id: int,
    signer_user_id: int,
    reason: str | None = None,
    pubsub: RedisPubSub | None = None,
) -> HoldDecisionResult:
    pr = _get_on_hold_run(session, pipeline_run_id)
    dq_failed = _failed_dq_node_runs(
        session, pipeline_run_id=pr.pipeline_run_id, run_date=pr.run_date
    )

    decision = HoldDecision(
        pipeline_run_id=pr.pipeline_run_id,
        run_date=pr.run_date,
        decision="APPROVE",
        signer_user_id=signer_user_id,
        reason=reason,
        quality_result_ids=_quality_result_ids_from_dq_nodes(dq_failed),
    )
    session.add(decision)

    # pipeline_run 재개.
    pr.status = "RUNNING"

    # 실패한 DQ_CHECK 직접 후속을 READY 로 — _ready_check 는 upstream SUCCESS 전제이므로
    # 본 게이트에서는 FAILED-with-approval 도 SUCCESS 로 간주하기 위해 sibling 맵 일시
    # 패치 후 평가.
    edges = list(
        session.execute(
            select(EdgeDefinition).where(EdgeDefinition.workflow_id == pr.workflow_id)
        )
        .scalars()
        .all()
    )
    siblings = _sibling_node_runs(session, pr.pipeline_run_id, pr.run_date)
    sibling_by_def = {s.node_definition_id: s for s in siblings}
    failed_dq_def_ids = {n.node_definition_id for n in dq_failed}

    def _approval_ready(target: NodeRun) -> bool:
        upstream = [e.from_node_id for e in edges if e.to_node_id == target.node_definition_id]
        if not upstream:
            return target.status == "PENDING"
        for upstream_id in upstream:
            up = sibling_by_def.get(upstream_id)
            if up is None:
                return False
            if up.node_definition_id in failed_dq_def_ids:
                continue  # 승인된 DQ 실패 — bypass.
            if up.status != "SUCCESS":
                return False
        return True

    next_ready: list[int] = []
    for s in siblings:
        if s.status != "PENDING":
            continue
        if _approval_ready(s):
            s.status = "READY"
            next_ready.append(s.node_run_id)
            _publish_state(pubsub, pipeline_run=pr, node_run=s, workflow_id=pr.workflow_id)

    session.flush()

    session.add(
        EventOutbox(
            aggregate_type="pipeline_run",
            aggregate_id=str(pr.pipeline_run_id),
            event_type="pipeline_run.hold_approved",
            payload_json={
                "pipeline_run_id": pr.pipeline_run_id,
                "run_date": pr.run_date.isoformat(),
                "workflow_id": pr.workflow_id,
                "signer_user_id": signer_user_id,
                "reason": reason,
                "decision_id": decision.decision_id,
                "ready_node_run_ids": next_ready,
            },
        )
    )

    metrics.pipeline_runs_total.labels(status="RUNNING").inc()

    return HoldDecisionResult(
        decision_id=decision.decision_id,
        pipeline_run_id=pr.pipeline_run_id,
        run_date=pr.run_date,
        decision="APPROVE",
        pipeline_status="RUNNING",
        ready_node_run_ids=tuple(next_ready),
        cancelled_node_run_ids=(),
        rollback_rows=0,
    )


def reject_hold(
    session: Session,
    *,
    pipeline_run_id: int,
    signer_user_id: int,
    reason: str | None = None,
    pubsub: RedisPubSub | None = None,
) -> HoldDecisionResult:
    pr = _get_on_hold_run(session, pipeline_run_id)
    dq_failed = _failed_dq_node_runs(
        session, pipeline_run_id=pr.pipeline_run_id, run_date=pr.run_date
    )

    decision = HoldDecision(
        pipeline_run_id=pr.pipeline_run_id,
        run_date=pr.run_date,
        decision="REJECT",
        signer_user_id=signer_user_id,
        reason=reason,
        quality_result_ids=_quality_result_ids_from_dq_nodes(dq_failed),
    )
    session.add(decision)

    # 잔여 노드 CANCELLED.
    siblings = _sibling_node_runs(session, pr.pipeline_run_id, pr.run_date)
    cancelled: list[int] = []
    for s in siblings:
        if s.status in ("PENDING", "READY", "RUNNING"):
            s.status = "CANCELLED"
            s.finished_at = datetime.now(UTC)
            metrics.pipeline_node_runs_total.labels(
                node_type=s.node_type, status="CANCELLED"
            ).inc()
            _publish_state(pubsub, pipeline_run=pr, node_run=s, workflow_id=pr.workflow_id)
            cancelled.append(s.node_run_id)

    # stg rollback — load_batch_id = pipeline_run_id 행을 삭제 (TRUNCATE 금지).
    rollback_rows = 0
    res1 = session.execute(
        text(
            "DELETE FROM stg.standard_record WHERE load_batch_id = :pid"
        ),
        {"pid": pr.pipeline_run_id},
    )
    rollback_rows += int(getattr(res1, "rowcount", 0) or 0)
    res2 = session.execute(
        text(
            "DELETE FROM stg.price_observation WHERE load_batch_id = :pid"
        ),
        {"pid": pr.pipeline_run_id},
    )
    rollback_rows += int(getattr(res2, "rowcount", 0) or 0)

    pr.status = "CANCELLED"
    pr.finished_at = datetime.now(UTC)
    pr.error_message = (
        f"DQ gate rejected by user_id={signer_user_id}: {reason}"
        if reason
        else f"DQ gate rejected by user_id={signer_user_id}"
    )[:2000]
    if pr.started_at:
        metrics.pipeline_run_duration_seconds.observe(
            max(0.0, (pr.finished_at - pr.started_at).total_seconds())
        )
    metrics.pipeline_runs_total.labels(status="CANCELLED").inc()

    session.flush()

    session.add(
        EventOutbox(
            aggregate_type="pipeline_run",
            aggregate_id=str(pr.pipeline_run_id),
            event_type="pipeline_run.hold_rejected",
            payload_json={
                "pipeline_run_id": pr.pipeline_run_id,
                "run_date": pr.run_date.isoformat(),
                "workflow_id": pr.workflow_id,
                "signer_user_id": signer_user_id,
                "reason": reason,
                "decision_id": decision.decision_id,
                "rollback_rows": rollback_rows,
                "cancelled_node_run_ids": cancelled,
            },
        )
    )

    return HoldDecisionResult(
        decision_id=decision.decision_id,
        pipeline_run_id=pr.pipeline_run_id,
        run_date=pr.run_date,
        decision="REJECT",
        pipeline_status="CANCELLED",
        ready_node_run_ids=(),
        cancelled_node_run_ids=tuple(cancelled),
        rollback_rows=rollback_rows,
    )


__all__ = ["HoldDecisionResult", "approve_hold", "reject_hold"]
