"""run schema ORM models — execution history / outbox / DLQ.

docs/03_DATA_MODEL.md 3.7 정합. pipeline_run / node_run 은 wf 와 함께 Phase 3 에서 추가.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class IngestJob(Base):
    __tablename__ = "ingest_job"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('ON_DEMAND','SCHEDULED','RETRY','BACKFILL')",
            name="ck_ingest_job_job_type",
        ),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED')",
            name="ck_ingest_job_status",
        ),
        {"schema": "run"},
    )

    job_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    output_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventOutbox(Base):
    """트랜잭션 정합 이벤트 발행 — outbox publisher 가 Redis Streams 로 옮김."""

    __tablename__ = "event_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PUBLISHED','FAILED')",
            name="ck_event_outbox_status",
        ),
        {"schema": "run"},
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedEvent(Base):
    """Idempotent consumer marker — 같은 event_id 중복 처리 방지."""

    __tablename__ = "processed_event"
    __table_args__ = {"schema": "run"}

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    consumer_name: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeadLetter(Base):
    __tablename__ = "dead_letter"
    __table_args__ = {"schema": "run"}

    dl_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replayed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))


__all__ = ["DeadLetter", "EventOutbox", "IngestJob", "ProcessedEvent"]
