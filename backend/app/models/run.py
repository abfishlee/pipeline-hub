"""run schema ORM models — execution history / outbox / DLQ.

docs/03_DATA_MODEL.md 3.7 정합. pipeline_run / node_run 은 wf 와 함께 Phase 3 에서 추가.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
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
    """Idempotent consumer marker — (event_id, consumer_name) 단위 처리 기록.

    같은 outbox event 를 여러 consumer 가 각자 처리하는 fan-out 패턴 (raw_object.created
    → ocr / transform / crawler) 에서 consumer 별로 독립 마킹. Phase 2.2.2 migration 0010
    에서 PK 를 합성으로 변경.
    """

    __tablename__ = "processed_event"
    __table_args__ = {"schema": "run"}

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    consumer_name: Mapped[str] = mapped_column(Text, primary_key=True)
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


class CrowdTask(Base):
    """OCR confidence 미달 등 사람 검수가 필요한 작업 큐.

    Phase 2.2.4 placeholder — Phase 4 에서 정식 Crowd 검수 UI/스키마 도입 시 컬럼
    보강. 그때까진 운영자가 수동으로 PENDING 큐를 처리.
    """

    __tablename__ = "crowd_task"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','REVIEWING','APPROVED','REJECTED')",
            name="ck_crowd_task_status",
        ),
        CheckConstraint(
            "length(reason) BETWEEN 1 AND 200",
            name="ck_crowd_task_reason",
        ),
        {"schema": "run"},
    )

    crowd_task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_object_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    partition_date: Mapped[date] = mapped_column(Date, nullable=False)
    ocr_result_id: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))


class PipelineRun(Base):
    """Visual ETL Designer 워크플로의 1회 실행 — RANGE 파티션 by run_date.

    Phase 3.2.1. 노드 실행 이력은 `NodeRun`.
    """

    __tablename__ = "pipeline_run"
    __table_args__ = (
        PrimaryKeyConstraint("pipeline_run_id", "run_date", name="pk_pipeline_run"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED')",
            name="ck_pipeline_run_status",
        ),
        {
            "schema": "run",
            "postgresql_partition_by": "RANGE (run_date)",
        },
    )

    pipeline_run_id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("wf.workflow_definition.workflow_id"), nullable=False
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    triggered_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NodeRun(Base):
    """파이프라인 1실행의 노드 단위 실행 이력 — 상태머신 PENDING/READY/RUNNING/
    SUCCESS/FAILED/SKIPPED/CANCELLED.

    `pipeline_run` 의 합성 PK 로 인해 FK 도 합성 (pipeline_run_id, run_date).
    """

    __tablename__ = "node_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pipeline_run_id", "run_date"],
            ["run.pipeline_run.pipeline_run_id", "run.pipeline_run.run_date"],
            ondelete="CASCADE",
            name="fk_node_run_pipeline",
        ),
        CheckConstraint(
            "status IN ('PENDING','READY','RUNNING','SUCCESS','FAILED','SKIPPED','CANCELLED')",
            name="ck_node_run_status",
        ),
        {"schema": "run"},
    )

    node_run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    node_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("wf.node_definition.node_id"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "CrowdTask",
    "DeadLetter",
    "EventOutbox",
    "IngestJob",
    "NodeRun",
    "PipelineRun",
    "ProcessedEvent",
]
