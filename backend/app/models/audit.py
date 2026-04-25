"""audit schema ORM models — access / SQL execution / download logs.

docs/03_DATA_MODEL.md 3.9 정합. access_log 는 월 파티션.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class AccessLog(Base):
    __tablename__ = "access_log"
    __table_args__ = (
        PrimaryKeyConstraint("log_id", "occurred_at", name="pk_access_log"),
        {
            "schema": "audit",
            "postgresql_partition_by": "RANGE (occurred_at)",
        },
    )

    log_id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    api_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.api_key.api_key_id"))
    method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SqlExecutionLog(Base):
    __tablename__ = "sql_execution_log"
    __table_args__ = (
        CheckConstraint(
            "execution_kind IN ('PREVIEW','SANDBOX','APPROVED','SCHEDULED')",
            name="ck_sql_execution_log_kind",
        ),
        CheckConstraint(
            "status IN ('SUCCESS','FAILED','BLOCKED','PENDING_APPROVAL')",
            name="ck_sql_execution_log_status",
        ),
        {"schema": "audit"},
    )

    sql_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id"), nullable=False
    )
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(Text, nullable=False)
    execution_kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_schema: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class DownloadLog(Base):
    __tablename__ = "download_log"
    __table_args__ = {"schema": "audit"}

    download_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    api_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.api_key.api_key_id"))
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_ref: Mapped[str] = mapped_column(Text, nullable=False)
    byte_count: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["AccessLog", "DownloadLog", "SqlExecutionLog"]
