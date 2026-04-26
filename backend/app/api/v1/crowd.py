"""HTTP 경계 — Crowd 검수.

  - `/v1/crowd-tasks/*`  — Phase 2.2.10 legacy. `run.crowd_task` view 호환. PATCH 는
    내부적으로 신규 domain (crowd_review) 으로 위임.
  - `/v1/crowd/tasks/*`  — Phase 4.2.1 정식. 이중 검수 + 합의 + outbox.

권한: ADMIN / REVIEWER / APPROVER. CONFLICT 해결만 ADMIN/APPROVER.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, SessionDep, require_roles
from app.domain import crowd_review
from app.models.crowd import (
    Review,
    Task,
    TaskAssignment,
    TaskDecision,
)
from app.models.ctl import AppUser
from app.repositories import crowd as crowd_repo
from app.schemas.crowd import (
    AssignTaskRequest,
    CrowdTaskDetail,
    CrowdTaskOut,
    CrowdTaskStatus,
    CrowdTaskStatusUpdate,
    OcrResultPreview,
    ResolveConflictRequest,
    ReviewOut,
    SubmitReviewRequest,
    TaskAssignmentOut,
    TaskDecisionOut,
    TaskFullDetail,
    TaskOut,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# 1. Legacy router (/v1/crowd-tasks)
# ---------------------------------------------------------------------------
legacy_router = APIRouter(
    prefix="/v1/crowd-tasks",
    tags=["crowd"],
    dependencies=[Depends(require_roles("ADMIN", "REVIEWER", "APPROVER"))],
)


@legacy_router.get("", response_model=list[CrowdTaskOut])
async def list_crowd_tasks_legacy(
    session: SessionDep,
    status: CrowdTaskStatus | None = Query(default=None),
    reason: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CrowdTaskOut]:
    rows = await crowd_repo.list_tasks(
        session, status=status, reason=reason, limit=limit, offset=offset
    )
    return [CrowdTaskOut.model_validate(r) for r in rows]


@legacy_router.get("/{crowd_task_id}", response_model=CrowdTaskDetail)
async def get_crowd_task_legacy(
    session: SessionDep,
    crowd_task_id: int,
) -> CrowdTaskDetail:
    task = await crowd_repo.get_task(session, crowd_task_id)
    if task is None:
        raise app_errors.NotFoundError(f"crowd_task {crowd_task_id} not found")
    raw = await crowd_repo.get_raw_object(
        session, raw_object_id=task.raw_object_id, partition_date=task.partition_date
    )
    ocr_rows = await crowd_repo.get_ocr_results(
        session, raw_object_id=task.raw_object_id, partition_date=task.partition_date
    )
    base = CrowdTaskOut.model_validate(task).model_dump()
    return CrowdTaskDetail(
        **base,
        raw_object_uri=(raw.object_uri if raw is not None else None),
        raw_object_payload=(raw.payload_json if raw is not None else None),
        ocr_results=[
            OcrResultPreview(
                ocr_result_id=o.ocr_result_id,
                page_no=o.page_no,
                text_content=o.text_content,
                confidence_score=float(o.confidence_score)
                if o.confidence_score is not None
                else None,
                engine_name=o.engine_name,
            )
            for o in ocr_rows
        ],
    )


@legacy_router.patch("/{crowd_task_id}/status", response_model=CrowdTaskOut)
async def update_crowd_task_status_legacy(
    session: SessionDep,
    user: CurrentUserDep,
    crowd_task_id: int,
    body: CrowdTaskStatusUpdate,
) -> CrowdTaskOut:
    """Phase 2.2.10 호환 PATCH — 내부적으로 Phase 4.2.1 domain 으로 위임.

    REVIEWING  → assign_reviewers([user_id])  (REVIEWING 상태 마킹)
    APPROVED   → submit_review(user_id, APPROVE)  (단일 검수 → SINGLE 합의)
    REJECTED   → submit_review(user_id, REJECT)
    """

    def _do(s: Session) -> None:
        if body.status == "REVIEWING":
            crowd_review.assign_reviewers(
                s, crowd_task_id=crowd_task_id, reviewer_ids=[user.user_id]
            )
            return
        crowd_review.submit_review(
            s,
            crowd_task_id=crowd_task_id,
            reviewer_id=user.user_id,
            decision="APPROVE" if body.status == "APPROVED" else "REJECT",
            comment=body.note,
        )

    await _in_sync_session(_do)

    # 결과는 view 에서 다시 SELECT.
    task = await crowd_repo.get_task(session, crowd_task_id)
    if task is None:
        raise app_errors.NotFoundError(f"crowd_task {crowd_task_id} not found")
    return CrowdTaskOut.model_validate(task)


# ---------------------------------------------------------------------------
# 2. Phase 4.2.1 정식 router (/v1/crowd/tasks)
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/v1/crowd",
    tags=["crowd-v4"],
    dependencies=[Depends(require_roles("ADMIN", "REVIEWER", "APPROVER"))],
)


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


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    user: CurrentUserDep,
    status: TaskStatus | None = Query(default=None),
    task_kind: str | None = Query(default=None, min_length=1, max_length=64),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskOut]:
    """task list — status / kind 필터 + priority desc 정렬."""

    def _do(s: Session) -> list[Task]:
        stmt = select(Task)
        if status:
            stmt = stmt.where(Task.status == status)
        if task_kind:
            stmt = stmt.where(Task.task_kind == task_kind)
        stmt = (
            stmt.order_by(Task.priority.desc(), Task.created_at.asc()).limit(limit).offset(offset)
        )
        return list(s.execute(stmt).scalars())

    rows = await _in_sync_session(_do)
    return [TaskOut.model_validate(r) for r in rows]


@router.get("/tasks/{crowd_task_id}", response_model=TaskFullDetail)
async def get_task(user: CurrentUserDep, crowd_task_id: int) -> TaskFullDetail:
    """task 상세 — assignments + reviews + decision 동봉."""

    def _do(
        s: Session,
    ) -> tuple[Task, list[TaskAssignment], list[Review], TaskDecision | None]:
        task = crowd_review.get_task_or_raise(s, crowd_task_id)
        assignments = list(
            s.execute(
                select(TaskAssignment).where(TaskAssignment.crowd_task_id == crowd_task_id)
            ).scalars()
        )
        reviews = list(
            s.execute(
                select(Review)
                .where(Review.crowd_task_id == crowd_task_id)
                .order_by(Review.decided_at.asc())
            ).scalars()
        )
        decision = s.get(TaskDecision, crowd_task_id)
        return task, assignments, reviews, decision

    task, assignments, reviews, decision = await _in_sync_session(_do)
    base = TaskOut.model_validate(task).model_dump()
    return TaskFullDetail(
        **base,
        assignments=[TaskAssignmentOut.model_validate(a) for a in assignments],
        reviews=[ReviewOut.model_validate(r) for r in reviews],
        decision=TaskDecisionOut.model_validate(decision) if decision is not None else None,
    )


@router.post("/tasks/{crowd_task_id}/assign", response_model=list[TaskAssignmentOut])
async def assign(
    user: CurrentUserDep,
    crowd_task_id: int,
    body: AssignTaskRequest,
) -> list[TaskAssignmentOut]:
    """검수자 1+명 배정. priority>=8 면 2명 이상 강제."""

    def _do(s: Session) -> list[TaskAssignment]:
        return crowd_review.assign_reviewers(
            s,
            crowd_task_id=crowd_task_id,
            reviewer_ids=body.reviewer_ids,
            due_at=body.due_at,
        )

    rows = await _in_sync_session(_do)
    return [TaskAssignmentOut.model_validate(a) for a in rows]


@router.post("/tasks/{crowd_task_id}/review", response_model=ReviewOut)
async def submit_review(
    user: CurrentUserDep,
    crowd_task_id: int,
    body: SubmitReviewRequest,
) -> ReviewOut:
    """검수자가 자신의 결정 제출. 단일/이중 검수 분기 + 합의 시 outbox 발행."""

    def _do(s: Session) -> Review:
        result = crowd_review.submit_review(
            s,
            crowd_task_id=crowd_task_id,
            reviewer_id=user.user_id,
            decision=body.decision,
            decision_payload=body.decision_payload,
            comment=body.comment,
            time_spent_ms=body.time_spent_ms,
        )
        review = s.get(Review, result.review_id)
        assert review is not None
        return review

    review = await _in_sync_session(_do)
    return ReviewOut.model_validate(review)


@router.post(
    "/tasks/{crowd_task_id}/resolve",
    response_model=TaskDecisionOut,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def resolve_conflict(
    user: CurrentUserDep,
    crowd_task_id: int,
    body: ResolveConflictRequest,
) -> TaskDecisionOut:
    """ADMIN/APPROVER 가 CONFLICT 해결. CONFLICT_RESOLVED + outbox."""

    def _do(s: Session) -> TaskDecision:
        crowd_review.resolve_conflict(
            s,
            crowd_task_id=crowd_task_id,
            resolver_user_id=user.user_id,
            final_decision=body.final_decision,
            note=body.note,
        )
        decision = s.get(TaskDecision, crowd_task_id)
        assert decision is not None
        return decision

    decision = await _in_sync_session(_do)
    return TaskDecisionOut.model_validate(decision)


@router.get("/stats/reviewers", response_model=list[dict[str, Any]])
async def reviewer_stats(user: CurrentUserDep) -> list[dict[str, Any]]:
    """검수자별 통계 — Phase 4.2.1 한정 실시간 집계 (30일 이내).

    Phase 4.2.10 에서 ctl.reviewer_stats cache 테이블 + Airflow 일별 갱신으로 교체.
    """

    def _do(s: Session) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        rows = s.execute(
            select(
                Review.reviewer_id,
                AppUser.display_name,
                func.count(Review.review_id).label("review_count"),
                func.avg(Review.time_spent_ms).label("avg_ms"),
            )
            .join(AppUser, AppUser.user_id == Review.reviewer_id)
            .where(Review.decided_at >= cutoff)
            .group_by(Review.reviewer_id, AppUser.display_name)
            .order_by(func.count(Review.review_id).desc())
        ).all()
        return [
            {
                "reviewer_id": int(r.reviewer_id),
                "display_name": r.display_name,
                "count_30d": int(r.review_count),
                "avg_decision_ms": int(r.avg_ms) if r.avg_ms is not None else None,
            }
            for r in rows
        ]

    return await _in_sync_session(_do)


__all__ = ["legacy_router", "router"]
