"""Phase 4.2.1 — Crowd 검수 도메인.

상태머신 + 이중 검수 + 합의 + outbox 발행.

핵심 규칙
---------
1. **이중 검수 트리거** — `priority >= 8` 또는 `requires_double_review=TRUE` 인 task 는
   2명 검수자의 review row 가 모두 도착해야 합의. 1명만 도착 시 status=REVIEWING 유지.
2. **합의 분기**:
   - 단일 검수 (priority < 8): 1명 review 후 즉시 task_decision 생성. consensus_kind=SINGLE.
   - 이중 검수 일치: 2명 모두 같은 decision → DOUBLE_AGREED.
   - 이중 검수 불일치: status=CONFLICT → 관리자 (ADMIN/APPROVER) 의 ResolveConflictRequest
     으로 CONFLICT_RESOLVED 마킹.
3. **outbox 발행** — task_decision 생성 시 `crowd.task.decided` event 를 run.event_outbox
   에 INSERT. 후속 worker (Phase 4.2.2) 가 mart 자동 반영.
4. **재처리** — final_decision=REJECT 면 effect_payload 에 stg rollback 정보 동봉
   (호출자가 필요하면 `domain.standardization` 의 함수 호출하여 재표준화 큐에 재투입).

본 도메인은 sync session 사용 — outbox 발행 / 다중 row 갱신을 트랜잭션으로 묶기 위해.
호출자(API) 가 thread offload 책임.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.crowd import Review, Task, TaskAssignment, TaskDecision
from app.models.run import EventOutbox

DOUBLE_REVIEW_PRIORITY_THRESHOLD = 8


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------
@dataclass
class ReviewSubmitResult:
    review_id: int
    task_status: str
    consensus_kind: str | None  # None 이면 아직 합의 안 됨 (이중 검수 1번째 도착).
    decision_id: int | None  # task_decision 생성 시 그 PK.


@dataclass
class ConflictResolveResult:
    decision_id: int
    final_decision: str


# ---------------------------------------------------------------------------
# Task 조회/배정
# ---------------------------------------------------------------------------
def get_task_or_raise(session: Session, crowd_task_id: int) -> Task:
    task = session.get(Task, crowd_task_id)
    if task is None:
        raise NotFoundError(f"crowd.task {crowd_task_id} not found")
    return task


def assign_reviewers(
    session: Session,
    *,
    crowd_task_id: int,
    reviewer_ids: Sequence[int],
    due_at: datetime | None = None,
) -> list[TaskAssignment]:
    """task 에 검수자 1+명 배정. priority>=8 면 reviewer_ids 가 2명 이상이어야 함.

    이미 같은 (task, reviewer) 가 있으면 ON CONFLICT 무시 (멱등).
    """
    task = get_task_or_raise(session, crowd_task_id)
    if task.status not in ("PENDING", "REVIEWING"):
        raise ConflictError(f"task {crowd_task_id} is {task.status}, cannot assign")

    if _needs_double_review(task) and len(set(reviewer_ids)) < 2:
        raise ValidationError(
            f"task {crowd_task_id} priority>={DOUBLE_REVIEW_PRIORITY_THRESHOLD} requires "
            "at least 2 distinct reviewers"
        )

    out: list[TaskAssignment] = []
    for rid in reviewer_ids:
        existing = session.execute(
            select(TaskAssignment)
            .where(TaskAssignment.crowd_task_id == crowd_task_id)
            .where(TaskAssignment.reviewer_id == rid)
        ).scalar_one_or_none()
        if existing is not None:
            out.append(existing)
            continue
        a = TaskAssignment(
            crowd_task_id=crowd_task_id,
            reviewer_id=rid,
            due_at=due_at,
        )
        session.add(a)
        out.append(a)

    if task.status == "PENDING":
        task.status = "REVIEWING"
        task.updated_at = datetime.now(UTC)
    session.flush()
    return out


def _needs_double_review(task: Task) -> bool:
    return task.requires_double_review or task.priority >= DOUBLE_REVIEW_PRIORITY_THRESHOLD


# ---------------------------------------------------------------------------
# Review 제출 + 합의
# ---------------------------------------------------------------------------
def submit_review(
    session: Session,
    *,
    crowd_task_id: int,
    reviewer_id: int,
    decision: str,
    decision_payload: dict[str, Any] | None = None,
    comment: str | None = None,
    time_spent_ms: int | None = None,
) -> ReviewSubmitResult:
    """검수자가 결정 제출. 단일/이중 검수 분기.

    - 단일 검수: 즉시 task_decision 생성 + outbox 발행 + status=APPROVED/REJECTED.
    - 이중 검수 1번째: review row 만 INSERT, status=REVIEWING 유지.
    - 이중 검수 2번째 일치: task_decision DOUBLE_AGREED + outbox.
    - 이중 검수 2번째 불일치: status=CONFLICT, 관리자 처리 대기.
    """
    if decision not in ("APPROVE", "REJECT", "SKIP"):
        raise ValidationError(f"invalid decision: {decision}")

    task = get_task_or_raise(session, crowd_task_id)
    if task.status not in ("PENDING", "REVIEWING"):
        raise ConflictError(f"task {crowd_task_id} is {task.status}, cannot review")

    # 같은 reviewer 가 이미 review 했으면 거부 (수정은 별도 endpoint).
    existing = session.execute(
        select(Review)
        .where(Review.crowd_task_id == crowd_task_id)
        .where(Review.reviewer_id == reviewer_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"reviewer {reviewer_id} already reviewed task {crowd_task_id}")

    review = Review(
        crowd_task_id=crowd_task_id,
        reviewer_id=reviewer_id,
        decision=decision,
        decision_payload=decision_payload or {},
        comment=comment,
        time_spent_ms=time_spent_ms,
    )
    session.add(review)
    session.flush()  # review.review_id 채움.

    # SKIP 은 합의 흐름에 안 잡힘 — 다른 검수자가 처리 (status 그대로).
    if decision == "SKIP":
        task.status = "REVIEWING"
        task.updated_at = datetime.now(UTC)
        session.flush()
        return ReviewSubmitResult(
            review_id=review.review_id,
            task_status=task.status,
            consensus_kind=None,
            decision_id=None,
        )

    # 합의 시도.
    needs_double = _needs_double_review(task)
    all_reviews = list(
        session.execute(
            select(Review)
            .where(Review.crowd_task_id == crowd_task_id)
            .where(Review.decision != "SKIP")
        ).scalars()
    )

    if not needs_double:
        return _finalize_decision(
            session,
            task=task,
            consensus_kind="SINGLE",
            final_decision=decision,
            decided_by=reviewer_id,
            new_review_id=review.review_id,
        )

    # needs_double — 2 review 가 모였는지 확인.
    if len(all_reviews) < 2:
        task.status = "REVIEWING"
        task.updated_at = datetime.now(UTC)
        session.flush()
        return ReviewSubmitResult(
            review_id=review.review_id,
            task_status=task.status,
            consensus_kind=None,
            decision_id=None,
        )

    decisions = {r.decision for r in all_reviews}
    if len(decisions) == 1:
        # 모두 일치 — DOUBLE_AGREED.
        return _finalize_decision(
            session,
            task=task,
            consensus_kind="DOUBLE_AGREED",
            final_decision=decisions.pop(),
            decided_by=reviewer_id,
            new_review_id=review.review_id,
        )

    # 불일치 — CONFLICT.
    task.status = "CONFLICT"
    task.updated_at = datetime.now(UTC)
    session.flush()
    return ReviewSubmitResult(
        review_id=review.review_id,
        task_status="CONFLICT",
        consensus_kind=None,
        decision_id=None,
    )


def _finalize_decision(
    session: Session,
    *,
    task: Task,
    consensus_kind: str,
    final_decision: str,
    decided_by: int | None,
    new_review_id: int,
) -> ReviewSubmitResult:
    if final_decision not in ("APPROVE", "REJECT"):
        # SKIP 은 여기 들어오지 않음.
        raise ValidationError(f"cannot finalize with decision {final_decision}")

    decision = TaskDecision(
        crowd_task_id=task.crowd_task_id,
        final_decision=final_decision,
        decided_by=decided_by,
        consensus_kind=consensus_kind,
        effect_payload=_build_effect_payload(task, final_decision),
    )
    session.add(decision)
    task.status = "APPROVED" if final_decision == "APPROVE" else "REJECTED"
    task.updated_at = datetime.now(UTC)
    session.flush()

    # outbox — Phase 4.2.2 의 mart 반영 worker 가 소비.
    session.add(
        EventOutbox(
            aggregate_type="crowd.task",
            aggregate_id=str(task.crowd_task_id),
            event_type="crowd.task.decided",
            payload_json={
                "crowd_task_id": task.crowd_task_id,
                "task_kind": task.task_kind,
                "final_decision": final_decision,
                "consensus_kind": consensus_kind,
                "raw_object_id": task.raw_object_id,
                "ocr_result_id": task.ocr_result_id,
                "std_record_id": task.std_record_id,
                "effect_payload": decision.effect_payload,
            },
        )
    )
    session.flush()

    return ReviewSubmitResult(
        review_id=new_review_id,
        task_status=task.status,
        consensus_kind=consensus_kind,
        decision_id=task.crowd_task_id,
    )


def _build_effect_payload(task: Task, final_decision: str) -> dict[str, Any]:
    """task_kind + final_decision 별 비즈니스 효과 페이로드.

    Phase 4.2.2 의 mart 반영 worker 가 본 페이로드를 보고 분기. 본 함수는 *어떤 효과를
    줘야 하는지* 의 의도만 기록 — 실제 mart 변경은 worker.
    """
    if final_decision == "REJECT":
        return {
            "action": "rollback_stg",
            "reason": "crowd_rejected",
            "task_kind": task.task_kind,
        }
    # APPROVE 분기.
    if task.task_kind in ("OCR_REVIEW", "ocr_low_confidence"):
        return {
            "action": "promote_ocr_to_mart",
            "ocr_result_id": task.ocr_result_id,
        }
    if task.task_kind in ("PRODUCT_MATCHING", "std_low_confidence"):
        return {
            "action": "add_alias",
            "std_record_id": task.std_record_id,
        }
    if task.task_kind in ("price_fact_low_confidence", "sample_review"):
        return {
            "action": "promote_price_fact",
            "raw_object_id": task.raw_object_id,
        }
    return {"action": "approve_generic", "task_kind": task.task_kind}


# ---------------------------------------------------------------------------
# Conflict 해결 — 관리자 전용
# ---------------------------------------------------------------------------
def resolve_conflict(
    session: Session,
    *,
    crowd_task_id: int,
    resolver_user_id: int,
    final_decision: str,
    note: str | None = None,
) -> ConflictResolveResult:
    """CONFLICT 상태 task 를 관리자가 해결. ADMIN/APPROVER 만 호출 (API 가드)."""
    task = get_task_or_raise(session, crowd_task_id)
    if task.status != "CONFLICT":
        raise ConflictError(f"task {crowd_task_id} is {task.status}, not CONFLICT")
    if final_decision not in ("APPROVE", "REJECT"):
        raise ValidationError(f"final_decision must be APPROVE/REJECT, got {final_decision}")

    decision = TaskDecision(
        crowd_task_id=task.crowd_task_id,
        final_decision=final_decision,
        decided_by=resolver_user_id,
        consensus_kind="CONFLICT_RESOLVED",
        effect_payload={**_build_effect_payload(task, final_decision), "resolver_note": note},
    )
    session.add(decision)
    task.status = "APPROVED" if final_decision == "APPROVE" else "REJECTED"
    task.updated_at = datetime.now(UTC)
    session.flush()

    session.add(
        EventOutbox(
            aggregate_type="crowd.task",
            aggregate_id=str(task.crowd_task_id),
            event_type="crowd.task.decided",
            payload_json={
                "crowd_task_id": task.crowd_task_id,
                "task_kind": task.task_kind,
                "final_decision": final_decision,
                "consensus_kind": "CONFLICT_RESOLVED",
                "resolver_user_id": resolver_user_id,
                "effect_payload": decision.effect_payload,
            },
        )
    )
    session.flush()
    return ConflictResolveResult(decision_id=task.crowd_task_id, final_decision=final_decision)


__all__ = [
    "DOUBLE_REVIEW_PRIORITY_THRESHOLD",
    "ConflictResolveResult",
    "ReviewSubmitResult",
    "assign_reviewers",
    "get_task_or_raise",
    "resolve_conflict",
    "submit_review",
]
