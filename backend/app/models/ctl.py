"""ctl schema ORM models — system control / sources / users.

docs/03_DATA_MODEL.md 3.2 정합.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = {"schema": "ctl"}

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    __tablename__ = "role"
    __table_args__ = {"schema": "ctl"}

    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role_id"),
        {"schema": "ctl"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ctl.app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ctl.role.role_id", ondelete="CASCADE"),
        nullable=False,
    )


class DataSource(Base):
    __tablename__ = "data_source"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('API','OCR','DB','CRAWLER','CROWD','RECEIPT','APP')",
            name="data_source_source_type_check",
        ),
        {"schema": "ctl"},
    )

    source_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    retailer_id: Mapped[int | None] = mapped_column(BigInteger)  # soft FK to mart.retailer_master
    owner_team: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Phase 2.2.7 — DB-to-DB 증분 수집의 진행 상태(last_cursor / last_run_at / last_count).
    watermark: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    schedule_cron: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    connectors: Mapped[list[Connector]] = relationship(back_populates="source")


class Connector(Base):
    __tablename__ = "connector"
    __table_args__ = (
        CheckConstraint(
            "connector_kind IN ('PG','MYSQL','ORACLE','MSSQL','HTTP','S3')",
            name="connector_kind_check",
        ),
        {"schema": "ctl"},
    )

    connector_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    connector_kind: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)  # NCP Secret Manager key
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped[DataSource] = relationship(back_populates="connectors")


class ApiKey(Base):
    __tablename__ = "api_key"
    __table_args__ = {"schema": "ctl"}

    api_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)  # Argon2id of full key
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["ApiKey", "AppUser", "Connector", "DataSource", "Role", "UserRole"]
