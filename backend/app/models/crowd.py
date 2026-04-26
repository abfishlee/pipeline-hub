"""crowd schema ORM — Phase 4.2.1 정식 검수 모듈.

Phase 2.2.4 의 `run.crowd_task` placeholder 와 동등한 기능 + 이중 검수 + 보상 + 스킬 태그.
마이그레이션 정책은 ADR-0011 참조.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class Task(Base):
    """검수 단위.

    상태머신:
      PENDING       — 작성 직후 (자동 파이프라인이 INSERT). 배정 가능.
      REVIEWING     — 1+ 검수자 배정됨 + review row 0~1개.
      CONFLICT      — 이중 검수에서 두 검수자 결정이 다름. 관리자 지명 대기.
      APPROVED      — 합의 결과 = APPROVE. mart 자동 반영 outbox 발행.
      REJECTED      — 합의 결과 = REJECT. stg 로 되돌림.
      CANCELLED     — 운영자가 취소 (삭제 대신 보존).
    """

    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint(
            "task_kind IN ("
            "'OCR_REVIEW','PRODUCT_MATCHING','RECEIPT_VALIDATION','ANOMALY_CHECK',"
            "'std_low_confidence','ocr_low_confidence',"
            "'price_fact_low_confidence','sample_review')",
            name="ck_crowd_task_kind",
        ),
        CheckConstraint(
            "status IN ('PENDING','REVIEWING','CONFLICT','APPROVED','REJECTED','CANCELLED')",
            name="ck_crowd_task_status",
        ),
        CheckConstraint("priority BETWEEN 1 AND 10", name="ck_crowd_task_priority"),
        {"schema": "crowd"},
    )

    crowd_task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_kind: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    raw_object_id: Mapped[int | None] = mapped_column(BigInteger)
    partition_date: Mapped[date | None] = mapped_column(Date)
    ocr_result_id: Mapped[int | None] = mapped_column(BigInteger)
    std_record_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    requires_double_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    assignments: Mapped[list[TaskAssignment]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    decision: Mapped[TaskDecision | None] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )


class TaskAssignment(Base):
    __tablename__ = "task_assignment"
    __table_args__ = (
        UniqueConstraint("crowd_task_id", "reviewer_id", name="uq_assignment"),
        {"schema": "crowd"},
    )

    assignment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    crowd_task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("crowd.task.crowd_task_id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="assignments")


class Review(Base):
    """검수자 1인의 결정. 이중 검수 시 같은 task 에 row 2개."""

    __tablename__ = "review"
    __table_args__ = (
        UniqueConstraint("crowd_task_id", "reviewer_id", name="uq_review"),
        CheckConstraint(
            "decision IN ('APPROVE','REJECT','SKIP')",
            name="ck_crowd_review_decision",
        ),
        {"schema": "crowd"},
    )

    review_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    crowd_task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("crowd.task.crowd_task_id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decision_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    comment: Mapped[str | None] = mapped_column(Text)
    time_spent_ms: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship(back_populates="reviews")


class TaskDecision(Base):
    """task 의 최종 합의. consensus_kind = SINGLE/DOUBLE_AGREED/CONFLICT_RESOLVED."""

    __tablename__ = "task_decision"
    __table_args__ = (
        CheckConstraint(
            "final_decision IN ('APPROVE','REJECT')",
            name="ck_crowd_decision_final",
        ),
        CheckConstraint(
            "consensus_kind IN ('SINGLE','DOUBLE_AGREED','CONFLICT_RESOLVED')",
            name="ck_crowd_decision_consensus",
        ),
        {"schema": "crowd"},
    )

    crowd_task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("crowd.task.crowd_task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    final_decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    consensus_kind: Mapped[str] = mapped_column(Text, nullable=False)
    effect_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship(back_populates="decision")


class Payout(Base):
    __tablename__ = "payout"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PAID','VOIDED')",
            name="ck_crowd_payout_status",
        ),
        {"schema": "crowd"},
    )

    payout_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("crowd.review.review_id", ondelete="CASCADE"),
        nullable=False,
    )
    amount_krw: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="KRW")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillTag(Base):
    __tablename__ = "skill_tag"
    __table_args__ = (
        UniqueConstraint("reviewer_id", "tag", name="uq_skill_tag"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_skill_confidence"),
        {"schema": "crowd"},
    )

    skill_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reviewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ctl.app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.5")


class ReviewerStats(Base):
    """ctl.reviewer_stats — 일별 갱신 cache 테이블 (Phase 4.2.1 의 통계)."""

    __tablename__ = "reviewer_stats"
    __table_args__ = {"schema": "ctl"}

    reviewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ctl.app_user.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    reviewed_count_30d: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    avg_decision_ms_30d: Mapped[int | None] = mapped_column(Integer)
    conflict_rate_30d: Mapped[float | None] = mapped_column(Numeric(5, 4))
    regression_rate_30d: Mapped[float | None] = mapped_column(Numeric(5, 4))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "Payout",
    "Review",
    "ReviewerStats",
    "SkillTag",
    "Task",
    "TaskAssignment",
    "TaskDecision",
]
