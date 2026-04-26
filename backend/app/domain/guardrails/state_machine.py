"""상태머신 — DRAFT → REVIEW → APPROVED → PUBLISHED.

각 entity (source_contract / field_mapping / dq_rule / mart_load_policy / sql_asset)
는 자신의 status 컬럼을 가지고, *상태 전이* 는 본 모듈이 검증 + ctl.approval_request
1행 INSERT.

전이 규칙 (Phase 5 MVP):

    DRAFT ──[request_review]──→ REVIEW
    REVIEW ──[approve(ADMIN)]──→ APPROVED
    REVIEW ──[reject(ADMIN)]───→ DRAFT     (수정 후 재요청)
    APPROVED ──[publish]──────→ PUBLISHED
    APPROVED ──[recall]───────→ DRAFT      (publish 전 취소)
    PUBLISHED ──[revise]──────→ DRAFT      (새 버전 시작 — 기존은 보존)

다중 승인 (Phase 6+) 은 같은 (entity_type, entity_id, entity_version) 에 대해 N row
INSERT 로 표현 — 스키마 변경 없이 확장 가능.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import text
from sqlalchemy.orm import Session


class Status(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class EntityType(StrEnum):
    SOURCE_CONTRACT = "source_contract"
    FIELD_MAPPING = "field_mapping"
    DQ_RULE = "dq_rule"
    MART_LOAD_POLICY = "mart_load_policy"
    SQL_ASSET = "sql_asset"


@dataclass(slots=True, frozen=True)
class Transition:
    from_status: Status
    to_status: Status
    requires_admin: bool


# 허용 전이 매트릭스.
ALLOWED: Final[tuple[Transition, ...]] = (
    Transition(Status.DRAFT, Status.REVIEW, requires_admin=False),
    Transition(Status.REVIEW, Status.APPROVED, requires_admin=True),
    Transition(Status.REVIEW, Status.DRAFT, requires_admin=True),
    Transition(Status.APPROVED, Status.PUBLISHED, requires_admin=True),
    Transition(Status.APPROVED, Status.DRAFT, requires_admin=True),
    Transition(Status.PUBLISHED, Status.DRAFT, requires_admin=False),
)


class TransitionError(ValueError):
    """허용되지 않은 전이 — caller 가 422/409 로 변환."""


def valid_transitions(current: Status) -> list[Status]:
    """현재 status 에서 갈 수 있는 다음 status 목록."""
    return [t.to_status for t in ALLOWED if t.from_status == current]


def find_transition(from_status: Status, to_status: Status) -> Transition:
    for t in ALLOWED:
        if t.from_status == from_status and t.to_status == to_status:
            return t
    raise TransitionError(
        f"transition {from_status} → {to_status} is not allowed "
        f"(valid from {from_status}: {valid_transitions(from_status)})"
    )


@dataclass(slots=True, frozen=True)
class TransitionResult:
    request_id: int
    entity_type: str
    entity_id: int
    entity_version: int
    from_status: Status
    to_status: Status
    decision: str  # APPROVE | REJECT | None (pending)
    is_admin_required: bool


def request_transition(
    session: Session,
    *,
    entity_type: EntityType,
    entity_id: int,
    entity_version: int,
    from_status: Status,
    to_status: Status,
    requester_user_id: int,
    reason: str | None = None,
) -> TransitionResult:
    """전이 요청 1건 INSERT. ADMIN 결재 필요한 전이면 decision/decided_at 미기재.

    request_review (DRAFT → REVIEW) 는 작성자 본인이 요청 가능. ADMIN 미필요.
    """
    transition = find_transition(from_status, to_status)
    is_admin_required = transition.requires_admin

    # request_review 같은 *non-admin* 전이는 즉시 결재 처리 (= 본인이 결재자).
    decision: str | None = None
    decided_at: datetime | None = None
    approver_user_id: int | None = None
    if not is_admin_required:
        decision = "APPROVE"
        decided_at = datetime.now(UTC)
        approver_user_id = requester_user_id

    request_id = session.execute(
        text(
            "INSERT INTO ctl.approval_request "
            "(entity_type, entity_id, entity_version, from_status, to_status, "
            " requester_user_id, approver_user_id, decision, decided_at, reason) "
            "VALUES (:et, :eid, :ev, :fs, :ts, :req, :app, :dec, :dat, :rsn) "
            "RETURNING request_id"
        ),
        {
            "et": entity_type.value,
            "eid": entity_id,
            "ev": entity_version,
            "fs": from_status.value,
            "ts": to_status.value,
            "req": requester_user_id,
            "app": approver_user_id,
            "dec": decision,
            "dat": decided_at,
            "rsn": reason,
        },
    ).scalar_one()
    return TransitionResult(
        request_id=int(request_id),
        entity_type=entity_type.value,
        entity_id=entity_id,
        entity_version=entity_version,
        from_status=from_status,
        to_status=to_status,
        decision=decision or "PENDING",
        is_admin_required=is_admin_required,
    )


def resolve_request(
    session: Session,
    *,
    request_id: int,
    decision: str,  # APPROVE | REJECT
    approver_user_id: int,
    is_admin: bool,
    reason: str | None = None,
) -> TransitionResult:
    """ADMIN 이 pending request 에 대해 APPROVE/REJECT.

    REJECT 시 to_status 는 DRAFT 로 자동 되돌림 (전이 결과로 저장).
    """
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError(f"invalid decision: {decision}")

    row = session.execute(
        text(
            "SELECT entity_type, entity_id, entity_version, from_status, to_status, "
            "       decision FROM ctl.approval_request WHERE request_id = :id"
        ),
        {"id": request_id},
    ).one_or_none()
    if row is None:
        raise ValueError(f"request {request_id} not found")
    if row.decision is not None:
        raise TransitionError(
            f"request {request_id} already {row.decision}"
        )

    requested_to = Status(row.to_status)
    transition = find_transition(Status(row.from_status), requested_to)
    if transition.requires_admin and not is_admin:
        raise TransitionError(
            f"transition {row.from_status} → {row.to_status} requires ADMIN"
        )

    # REJECT 면 entity 의 status 를 DRAFT 로 강제.
    final_to = requested_to if decision == "APPROVE" else Status.DRAFT

    session.execute(
        text(
            "UPDATE ctl.approval_request SET "
            "  decision = :dec, decided_at = now(), approver_user_id = :app, "
            "  reason = COALESCE(:rsn, reason), to_status = :ts "
            "WHERE request_id = :id"
        ),
        {
            "dec": decision,
            "app": approver_user_id,
            "rsn": reason,
            "ts": final_to.value,
            "id": request_id,
        },
    )

    return TransitionResult(
        request_id=request_id,
        entity_type=row.entity_type,
        entity_id=int(row.entity_id),
        entity_version=int(row.entity_version),
        from_status=Status(row.from_status),
        to_status=final_to,
        decision=decision,
        is_admin_required=transition.requires_admin,
    )


__all__ = [
    "ALLOWED",
    "EntityType",
    "Status",
    "Transition",
    "TransitionError",
    "TransitionResult",
    "find_transition",
    "request_transition",
    "resolve_request",
    "valid_transitions",
]
