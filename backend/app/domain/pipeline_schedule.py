"""파이프라인 스케줄 / Backfill / 재실행 도메인 (Phase 3.2.7).

Phase 3.2.7 의 책임:
  - 스케줄 메타 갱신 (cron 표현식 검증 + enabled 토글). 실제 cron 트리거는 Phase 4
    Airflow 통합 시 수신자가 활용. 본 phase 는 메타 + UI 까지만.
  - Backfill — 시작/종료 날짜 사이의 각 일자에 대해 별도 `pipeline_run` 을 생성.
    각 run 은 그 날짜를 `run_date` 로 기록 (월 파티션 자동 라우팅).
  - 재실행 — 기존 종결된 pipeline_run 을 통째로 다시 돌리거나(`restart_run`),
    특정 노드부터만 다시 돌린다(`restart_run(from_node_key=...)`).
    구현은 *새 pipeline_run* 을 만들고, from_node_key 가 지정되면 그 노드의 ancestor
    들은 SUCCESS / 나머지는 PENDING/READY 로 시드한다.

`croniter` 는 Phase 1 부터 의존성에 등록되어 있어 추가 install 없음.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.domain import pipeline_runtime as runtime
from app.models.run import NodeRun, PipelineRun
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition

MAX_BACKFILL_DAYS = 366  # 1년 한도 — 실수로 거대한 backfill 트리거 방지.


# ---------------------------------------------------------------------------
# 스케줄 메타 갱신
# ---------------------------------------------------------------------------
def validate_cron(expr: str) -> str:
    """5-field 표준 cron. 불일치 시 ValidationError."""
    expr = expr.strip()
    if not expr:
        raise ValidationError("cron expression is empty")
    parts = expr.split()
    if len(parts) != 5:
        raise ValidationError(
            f"cron must have 5 fields (minute hour dom month dow), got {len(parts)}"
        )
    try:
        croniter(expr, datetime.now(UTC))
    except (ValueError, KeyError) as exc:
        raise ValidationError(f"invalid cron expression: {exc}") from exc
    return expr


def set_schedule(
    session: Session,
    *,
    workflow_id: int,
    cron: str | None,
    enabled: bool,
) -> WorkflowDefinition:
    """Workflow.schedule_cron / schedule_enabled 설정.

    cron=None 이면 enabled 도 강제 False.
    """
    workflow = session.get(WorkflowDefinition, workflow_id)
    if workflow is None:
        raise NotFoundError(f"workflow {workflow_id} not found")

    if cron is not None:
        cron = validate_cron(cron)
    else:
        # cron 비우면 자동 비활성화.
        enabled = False

    workflow.schedule_cron = cron
    workflow.schedule_enabled = enabled
    workflow.updated_at = datetime.now(UTC)
    session.flush()
    return workflow


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
@dataclass
class BackfillResult:
    pipeline_run_ids: list[int]
    run_dates: list[date]


def backfill(
    session: Session,
    *,
    workflow_id: int,
    start_date: date,
    end_date: date,
    triggered_by_user_id: int | None,
) -> BackfillResult:
    """`[start_date, end_date]` 의 각 일자에 대해 pipeline_run 을 1개씩 생성.

    각 run 은 PENDING 상태로 시작 — caller(API) 가 actor enqueue 책임.
    """
    if start_date > end_date:
        raise ValidationError(f"start_date {start_date} > end_date {end_date}")
    span = (end_date - start_date).days + 1
    if span > MAX_BACKFILL_DAYS:
        raise ValidationError(
            f"backfill span {span} exceeds limit {MAX_BACKFILL_DAYS} days — split into chunks"
        )

    workflow = session.get(WorkflowDefinition, workflow_id)
    if workflow is None:
        raise NotFoundError(f"workflow {workflow_id} not found")
    if workflow.status != "PUBLISHED":
        raise ConflictError(
            f"workflow {workflow_id} is {workflow.status} — must be PUBLISHED to backfill"
        )

    nodes = list(
        session.execute(
            select(NodeDefinition)
            .where(NodeDefinition.workflow_id == workflow_id)
            .order_by(NodeDefinition.node_id)
        ).scalars()
    )
    edges = list(
        session.execute(
            select(EdgeDefinition).where(EdgeDefinition.workflow_id == workflow_id)
        ).scalars()
    )
    if not nodes:
        raise ConflictError(f"workflow {workflow_id} has no nodes")
    # Cycle 검증은 runtime 의 _topo_sort 호출과 동일 — start_pipeline_run 이 매번 함.
    _ = runtime._topo_sort(nodes, edges)  # raises ValueError on cycle

    run_ids: list[int] = []
    dates: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        # 같은 (workflow_id, run_date) 가 이미 있으면 skip — backfill 멱등성.
        existing = session.execute(
            select(PipelineRun)
            .where(PipelineRun.workflow_id == workflow_id)
            .where(PipelineRun.run_date == cursor)
        ).scalar_one_or_none()
        if existing is not None:
            run_ids.append(existing.pipeline_run_id)
            dates.append(cursor)
            cursor += timedelta(days=1)
            continue

        pr = PipelineRun(
            workflow_id=workflow_id,
            run_date=cursor,
            status="PENDING",
            triggered_by=triggered_by_user_id,
        )
        session.add(pr)
        session.flush()
        for n in nodes:
            session.add(
                NodeRun(
                    pipeline_run_id=pr.pipeline_run_id,
                    run_date=pr.run_date,
                    node_definition_id=n.node_id,
                    node_key=n.node_key,
                    node_type=n.node_type,
                    status="PENDING",
                )
            )
        session.flush()
        run_ids.append(pr.pipeline_run_id)
        dates.append(cursor)
        cursor += timedelta(days=1)

    return BackfillResult(pipeline_run_ids=run_ids, run_dates=dates)


# ---------------------------------------------------------------------------
# Run 검색
# ---------------------------------------------------------------------------
def search_runs(
    session: Session,
    *,
    workflow_id: int | None = None,
    status: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PipelineRun]:
    stmt = select(PipelineRun)
    if workflow_id is not None:
        stmt = stmt.where(PipelineRun.workflow_id == workflow_id)
    if status is not None:
        stmt = stmt.where(PipelineRun.status == status)
    if from_date is not None:
        stmt = stmt.where(PipelineRun.run_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(PipelineRun.run_date <= to_date)
    stmt = stmt.order_by(PipelineRun.created_at.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


# ---------------------------------------------------------------------------
# 재실행 (전체 또는 특정 노드부터)
# ---------------------------------------------------------------------------
@dataclass
class RestartResult:
    new_pipeline_run_id: int
    new_run_date: date
    ready_node_run_ids: tuple[int, ...]
    seeded_success_node_keys: tuple[str, ...]


def _ancestors_of(
    target_node_id: int,
    nodes: Sequence[NodeDefinition],
    edges: Sequence[EdgeDefinition],
) -> set[int]:
    """target 의 모든 조상 (이전 단계) 노드 IDs (자신 포함하지 않음)."""
    by_id = {n.node_id: n for n in nodes}
    if target_node_id not in by_id:
        return set()
    rev: dict[int, list[int]] = {n.node_id: [] for n in nodes}
    for e in edges:
        rev.setdefault(e.to_node_id, []).append(e.from_node_id)

    ancestors: set[int] = set()
    stack = [target_node_id]
    while stack:
        cur = stack.pop()
        for parent in rev.get(cur, []):
            if parent not in ancestors:
                ancestors.add(parent)
                stack.append(parent)
    return ancestors


def restart_run(
    session: Session,
    *,
    pipeline_run_id: int,
    from_node_key: str | None = None,
    triggered_by_user_id: int | None,
) -> RestartResult:
    """기존 pipeline_run 을 기반으로 새 run 생성.

    - `from_node_key=None` (기본): 같은 그래프를 새 run_date(오늘) 로 처음부터 다시 실행.
    - `from_node_key="X"`: X 의 모든 ancestor 는 SUCCESS 로 미리 마킹 + X 와 X 의 후손은
      PENDING (X 자신은 즉시 READY). ancestor 의 output_json 이 필요한 경우 — 현재
      Phase 3 NOOP 위주라 단순 SUCCESS 시드면 충분, 향후 lineage 결합 시 보강.
    """
    pr = session.execute(
        select(PipelineRun).where(PipelineRun.pipeline_run_id == pipeline_run_id)
    ).scalar_one_or_none()
    if pr is None:
        raise NotFoundError(f"pipeline_run {pipeline_run_id} not found")

    workflow = session.get(WorkflowDefinition, pr.workflow_id)
    if workflow is None:
        raise NotFoundError(f"workflow {pr.workflow_id} not found")
    if workflow.status != "PUBLISHED":
        raise ConflictError(
            f"workflow {pr.workflow_id} is {workflow.status} — must be PUBLISHED to restart"
        )

    nodes = list(
        session.execute(
            select(NodeDefinition)
            .where(NodeDefinition.workflow_id == pr.workflow_id)
            .order_by(NodeDefinition.node_id)
        ).scalars()
    )
    edges = list(
        session.execute(
            select(EdgeDefinition).where(EdgeDefinition.workflow_id == pr.workflow_id)
        ).scalars()
    )

    target_node: NodeDefinition | None = None
    if from_node_key is not None:
        target_node = next((n for n in nodes if n.node_key == from_node_key), None)
        if target_node is None:
            raise ValidationError(
                f"node_key '{from_node_key}' not found in workflow {pr.workflow_id}"
            )

    today = datetime.now(UTC).date()
    # 같은 (workflow, today) 충돌 회피: 이미 있으면 1초 늦춰 새 PK 만 붙이고 today 유지
    # (pipeline_run PK 는 (id, run_date) — id 가 BIGSERIAL 이라 자연 충돌 없음).
    new_pr = PipelineRun(
        workflow_id=pr.workflow_id,
        run_date=today,
        status="RUNNING",
        triggered_by=triggered_by_user_id,
        started_at=datetime.now(UTC),
    )
    session.add(new_pr)
    session.flush()

    ancestor_ids: set[int] = set()
    if target_node is not None:
        ancestor_ids = _ancestors_of(target_node.node_id, nodes, edges)

    seeded: list[str] = []
    new_node_runs: list[NodeRun] = []
    for n in nodes:
        if target_node is not None and n.node_id in ancestor_ids:
            initial_status = "SUCCESS"
            seeded.append(n.node_key)
        else:
            initial_status = "PENDING"
        nr = NodeRun(
            pipeline_run_id=new_pr.pipeline_run_id,
            run_date=new_pr.run_date,
            node_definition_id=n.node_id,
            node_key=n.node_key,
            node_type=n.node_type,
            status=initial_status,
            attempt_no=1 if initial_status == "SUCCESS" else 0,
            started_at=datetime.now(UTC) if initial_status == "SUCCESS" else None,
            finished_at=datetime.now(UTC) if initial_status == "SUCCESS" else None,
        )
        session.add(nr)
        new_node_runs.append(nr)
    session.flush()

    # READY 결정:
    #  - target 노드가 지정되면 그 노드를 READY 로.
    #  - 아니면 entry node 들을 READY (start_pipeline_run 과 동일 정책).
    has_incoming = {e.to_node_id for e in edges}
    ready_ids: list[int] = []
    for nr in new_node_runs:
        if target_node is not None:
            if nr.node_definition_id == target_node.node_id:
                nr.status = "READY"
                ready_ids.append(nr.node_run_id)
        else:
            if nr.node_definition_id not in has_incoming and nr.status == "PENDING":
                nr.status = "READY"
                ready_ids.append(nr.node_run_id)
    session.flush()

    return RestartResult(
        new_pipeline_run_id=new_pr.pipeline_run_id,
        new_run_date=new_pr.run_date,
        ready_node_run_ids=tuple(ready_ids),
        seeded_success_node_keys=tuple(seeded),
    )


__all__ = [
    "MAX_BACKFILL_DAYS",
    "BackfillResult",
    "RestartResult",
    "backfill",
    "restart_run",
    "search_runs",
    "set_schedule",
    "validate_cron",
]
