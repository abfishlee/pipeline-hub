"""raw schema ORM models.

docs/03_DATA_MODEL.md 3.3 정합. 파티션 테이블은 ORM 에서 단일 인터페이스로 다루고,
실제 파티션 생성은 Alembic + 매월 자동화 스크립트(Phase 2)가 담당.
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
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class RawObject(Base):
    """파티션 테이블 (RANGE on partition_date).

    ORM 으로는 단일 테이블처럼 보지만, 물리적으로는 월 단위 child partition.
    조회 시 partition_date 조건 포함 필수.
    """

    __tablename__ = "raw_object"
    __table_args__ = (
        PrimaryKeyConstraint("raw_object_id", "partition_date", name="pk_raw_object"),
        CheckConstraint(
            "object_type IN ('JSON','XML','CSV','HTML','PDF','IMAGE','DB_ROW','RECEIPT_IMAGE')",
            name="ck_raw_object_object_type",
        ),
        CheckConstraint(
            "status IN ('RECEIVED','PROCESSED','FAILED','DISCARDED')",
            name="ck_raw_object_status",
        ),
        {
            "schema": "raw",
            "postgresql_partition_by": "RANGE (partition_date)",
        },
    )

    raw_object_id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    job_id: Mapped[int | None] = mapped_column(BigInteger)  # FK to run.ingest_job (after 0004)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_uri: Mapped[str | None] = mapped_column(Text)
    # none_as_null=True : Python None → SQL NULL (기본값은 JSON 'null' 리터럴 저장).
    # 대용량 body 가 Object Storage 로 빠졌을 때 payload_json 은 진짜 NULL 이어야 함.
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    partition_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="RECEIVED")


class ContentHashIndex(Base):
    """전역 content_hash unique 인덱스 (raw_object PK 가 partition 포함이라 별도 보존)."""

    __tablename__ = "content_hash_index"
    __table_args__ = {"schema": "raw"}

    content_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    raw_object_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    partition_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OcrResult(Base):
    __tablename__ = "ocr_result"
    __table_args__ = {"schema": "raw"}

    ocr_result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_object_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    partition_date: Mapped[date] = mapped_column(Date, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    text_content: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    layout_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    engine_name: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RawWebPage(Base):
    __tablename__ = "raw_web_page"
    __table_args__ = {"schema": "raw"}

    page_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    html_object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str | None] = mapped_column(Text)


class DbSnapshot(Base):
    __tablename__ = "db_snapshot"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('SNAPSHOT','INCREMENTAL','CDC')",
            name="ck_db_snapshot_mode",
        ),
        {"schema": "raw"},
    )

    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watermark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="RUNNING")


class DbCdcEvent(Base):
    """Phase 4.2.3 — wal2json 으로 적재된 CDC 이벤트 1건.

    `cdc_consumer_worker` 가 logical replication slot stream 을 1배치 읽고 INSERT.
    `(source_id, lsn)` UNIQUE — 같은 LSN 재처리 시 중복 차단.
    """

    __tablename__ = "db_cdc_event"
    __table_args__ = (
        CheckConstraint("op IN ('I','U','D')", name="ck_db_cdc_event_op"),
        {"schema": "raw"},
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    op: Mapped[str] = mapped_column(Text, nullable=False)  # CHAR(1) IN ('I','U','D')
    pk_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    lsn: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "ContentHashIndex",
    "DbCdcEvent",
    "DbSnapshot",
    "OcrResult",
    "RawObject",
    "RawWebPage",
]
