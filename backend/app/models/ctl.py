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
    # Phase 4.2.3 — DB CDC 활성화 토글 (slot 가동 여부와 별개, 운영자 의도 표시).
    cdc_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    # Phase 4.2.4 — RLS allowlist (api_key 별 허용 retailer_id 셋).
    # **DEPRECATED Phase 5.2.7** — agri 도메인의 domain_resource_allowlist 로
    # 자동 매핑됨 (migration 0044). Phase 7 에서 제거 검토.
    retailer_allowlist: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default="{}"
    )
    # Phase 5.2.7 STEP 10 — multi-domain scope (확장형).
    # 형식: {"agri":{"resources":{"prices":{"retailer_ids":[1,2]}}},
    #        "pos": {"resources":{"transactions":{"shop_ids":[100]}}}}
    domain_resource_allowlist: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # Phase 4.2.5 — Public API 메타 (manage 라우트 + audit 결합).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CdcSubscription(Base):
    """Phase 4.2.3 — wal2json logical replication slot 메타 + lag.

    `data_source.cdc_enabled=true` 토글 후 `scripts/setup_cdc_slot.sql` 가
    `pg_create_logical_replication_slot` 으로 slot 을 생성하면 본 테이블의
    `enabled=true` 로 대응. cdc_consumer_worker 가 slot 에서 stream 을 읽어
    `raw.db_cdc_event` INSERT.
    """

    __tablename__ = "cdc_subscription"
    __table_args__ = (
        CheckConstraint("plugin IN ('wal2json')", name="ck_cdc_subscription_plugin"),
        {"schema": "ctl"},
    )

    subscription_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False, unique=True
    )
    slot_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    plugin: Mapped[str] = mapped_column(Text, nullable=False, default="wal2json")
    publication_name: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_committed_lsn: Mapped[str | None] = mapped_column(Text)
    last_lag_bytes: Mapped[int | None] = mapped_column(BigInteger)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_lsn: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PartitionArchiveLog(Base):
    """Phase 4.2.7 — partition archive 이력. detect → archive → restore."""

    __tablename__ = "partition_archive_log"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','COPYING','COPIED','DETACHED','DROPPED','RESTORED','FAILED')",
            name="ck_partition_archive_status",
        ),
        {"schema": "ctl"},
    )

    archive_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    partition_name: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(Text)
    object_uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_to: Mapped[str | None] = mapped_column(Text)
    archived_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id")
    )
    restored_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserDomainRole(Base):
    """user × domain 권한 매트릭스 (Phase 5.2.4 STEP 7).

    role 위계: VIEWER < EDITOR < APPROVER < ADMIN.
    전역 ADMIN(ctl.role) 은 모든 도메인 ADMIN 권한 자동 보유 — 본 테이블 미경유.
    """

    __tablename__ = "user_domain_role"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "domain_code"),
        CheckConstraint(
            "role IN ('VIEWER','EDITOR','APPROVER','ADMIN')",
            name="ck_user_domain_role_role",
        ),
        {"schema": "ctl"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id", ondelete="CASCADE")
    )
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublishChecklistRun(Base):
    """publish 시점의 7항목 체크리스트 결과 (Phase 5.2.4 STEP 7 Q5)."""

    __tablename__ = "publish_checklist_run"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('source_contract','field_mapping','dq_rule',"
            "                'mart_load_policy','sql_asset','load_policy')",
            name="ck_pcr_entity_type",
        ),
        {"schema": "ctl"},
    )

    checklist_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    domain_code: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id")
    )
    checks_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    all_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_check_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DryRunRecord(Base):
    """dry-run 결과 보존 (Phase 5.2.4 STEP 7 Q4)."""

    __tablename__ = "dry_run_record"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('field_mapping','load_target','dq_rule','sql_asset',"
            "         'mart_designer','custom')",
            name="ck_dry_run_kind",
        ),
        {"schema": "ctl"},
    )

    dry_run_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    domain_code: Mapped[str | None] = mapped_column(Text)
    target_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    row_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    errors: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "ApiKey",
    "AppUser",
    "CdcSubscription",
    "Connector",
    "DataSource",
    "DryRunRecord",
    "PartitionArchiveLog",
    "PublishChecklistRun",
    "Role",
    "UserDomainRole",
    "UserRole",
]
