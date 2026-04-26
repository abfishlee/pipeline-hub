"""domain schema ORM (Phase 5.2.1).

ADR-0017 의 *Hybrid* 결정에 따라 v2 generic resource 의 *데이터 테이블* (도메인별 mart
등) 은 reflection 으로 다루고, *registry 메타 테이블* (본 모듈) 은 정적 ORM 으로 유지.
이 분리가 Phase 5.2.0 의 가드레일 + Phase 5.2.4 의 ETL UX 가 일관된 typed API 위에서
동작하기 위한 토대.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class DomainDefinition(Base):
    __tablename__ = "domain_definition"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_domain_definition_status",
        ),
        CheckConstraint(
            "domain_code ~ '^[a-z][a-z0-9_]{1,30}$'",
            name="ck_domain_code_format",
        ),
        {"schema": "domain"},
    )

    domain_code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schema_yaml: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResourceDefinition(Base):
    __tablename__ = "resource_definition"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_resource_definition_status",
        ),
        UniqueConstraint(
            "domain_code", "resource_code", "version", name="uq_resource_definition_code"
        ),
        {"schema": "domain"},
    )

    resource_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    resource_code: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_table: Mapped[str | None] = mapped_column(Text)
    fact_table: Mapped[str | None] = mapped_column(Text)
    standard_code_namespace: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_table: Mapped[str | None] = mapped_column(Text)
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StandardCodeNamespace(Base):
    __tablename__ = "standard_code_namespace"
    __table_args__ = (
        UniqueConstraint("domain_code", "name", name="uq_standard_code_namespace"),
        {"schema": "domain"},
    )

    namespace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    std_code_table: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceContract(Base):
    __tablename__ = "source_contract"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_source_contract_status",
        ),
        CheckConstraint(
            "compatibility_mode IN ('backward','forward','full','none')",
            name="ck_source_contract_compat",
        ),
        UniqueConstraint(
            "source_id", "domain_code", "resource_code", "schema_version",
            name="uq_source_contract_id_version",
        ),
        {"schema": "domain"},
    )

    contract_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    resource_code: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    compatibility_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="backward")
    resource_selector_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FieldMapping(Base):
    __tablename__ = "field_mapping"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_field_mapping_status",
        ),
        UniqueConstraint(
            "contract_id", "target_table", "target_column", name="uq_field_mapping_target"
        ),
        {"schema": "domain"},
    )

    mapping_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domain.source_contract.contract_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_table: Mapped[str] = mapped_column(Text, nullable=False)
    target_column: Mapped[str] = mapped_column(Text, nullable=False)
    transform_expr: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LoadPolicy(Base):
    __tablename__ = "load_policy"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('append_only','upsert','scd_type_2','current_snapshot')",
            name="ck_load_policy_mode",
        ),
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_load_policy_status",
        ),
        UniqueConstraint("resource_id", "version", name="uq_load_policy_resource_version"),
        {"schema": "domain"},
    )

    policy_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domain.resource_definition.resource_id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    key_columns: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    partition_expr: Mapped[str | None] = mapped_column(Text)
    scd_options_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    statement_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=60000)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DqRule(Base):
    __tablename__ = "dq_rule"
    __table_args__ = (
        CheckConstraint(
            "rule_kind IN ('row_count_min','null_pct_max','unique_columns',"
            "              'reference','range','custom_sql')",
            name="ck_dq_rule_kind",
        ),
        CheckConstraint(
            "severity IN ('INFO','WARN','ERROR','BLOCK')",
            name="ck_dq_rule_severity",
        ),
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_dq_rule_status",
        ),
        {"schema": "domain"},
    )

    rule_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    target_table: Mapped[str] = mapped_column(Text, nullable=False)
    rule_kind: Mapped[str] = mapped_column(Text, nullable=False)
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="ERROR")
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    sample_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_scan_rows: Mapped[int | None] = mapped_column(BigInteger)
    incremental_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderDefinition(Base):
    __tablename__ = "provider_definition"
    __table_args__ = (
        CheckConstraint(
            "provider_kind IN ('OCR','CRAWLER','AI_TRANSFORM','HTTP_TRANSFORM')",
            name="ck_provider_kind",
        ),
        CheckConstraint(
            "implementation_type IN ('internal_class','external_api')",
            name="ck_provider_impl",
        ),
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_]{1,30}$'",
            name="ck_provider_code_format",
        ),
        {"schema": "domain"},
    )

    provider_code: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_type: Mapped[str] = mapped_column(Text, nullable=False)
    config_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    secret_ref: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceProviderBinding(Base):
    __tablename__ = "source_provider_binding"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "provider_code", "priority", name="uq_source_provider_priority"
        ),
        {"schema": "domain"},
    )

    binding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.provider_definition.provider_code"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fallback_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SqlAsset(Base):
    """등록·승인된 SQL artifact (Phase 5.2.2 STEP 5).

    SQL_ASSET_TRANSFORM 노드의 backing — *PUBLISHED 만 production 실행 허용*.
    INLINE 노드와 달리 검증·이력·재현이 필요한 SQL 은 본 테이블에 등록.
    """

    __tablename__ = "sql_asset"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_sql_asset_status",
        ),
        CheckConstraint(
            "asset_code ~ '^[a-z][a-z0-9_]{1,62}$'",
            name="ck_sql_asset_code_format",
        ),
        UniqueConstraint("asset_code", "version", name="uq_sql_asset_code_version"),
        {"schema": "domain"},
    )

    asset_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_code: Mapped[str] = mapped_column(Text, nullable=False)
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    output_table: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MartDesignDraft(Base):
    """Mart Designer 의 migration 초안 (Phase 5.2.4 STEP 7 Q2).

    UI 가 컬럼/타입/key/partition 폼 → DDL 텍스트 + diff 요약 → DRAFT 등록.
    상태머신 (DRAFT→REVIEW→APPROVED→PUBLISHED→ROLLED_BACK) 은 ctl.approval_request
    가 이력 보관.
    """

    __tablename__ = "mart_design_draft"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED','ROLLED_BACK')",
            name="ck_mart_design_draft_status",
        ),
        {"schema": "domain"},
    )

    draft_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    target_table: Mapped[str] = mapped_column(Text, nullable=False)
    ddl_text: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InboundChannel(Base):
    """외부 시스템 push 채널 등록 (Phase 7 Wave 1A).

    크롤링 업체 / OCR 업체 / 소상공인 업로드 등 외부에서 우리에게 push 하는
    데이터를 받기 위한 채널 정의. HMAC SHA256 + replay window 로 인증.
    """

    __tablename__ = "inbound_channel"
    __table_args__ = (
        CheckConstraint(
            "channel_kind IN ('WEBHOOK','FILE_UPLOAD','OCR_RESULT','CRAWLER_RESULT')",
            name="ck_inbound_channel_kind",
        ),
        CheckConstraint(
            "auth_method IN ('hmac_sha256','api_key','mtls')",
            name="ck_inbound_channel_auth",
        ),
        CheckConstraint(
            "status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')",
            name="ck_inbound_channel_status",
        ),
        {"schema": "domain"},
    )

    channel_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    channel_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    domain_code: Mapped[str] = mapped_column(
        Text, ForeignKey("domain.domain_definition.domain_code"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    channel_kind: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    auth_method: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="hmac_sha256"
    )

    expected_content_type: Mapped[str | None] = mapped_column(Text)
    max_payload_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10485760"
    )
    rate_limit_per_min: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="100"
    )
    replay_window_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="300"
    )

    workflow_id: Mapped[int | None] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "DomainDefinition",
    "DqRule",
    "FieldMapping",
    "InboundChannel",
    "LoadPolicy",
    "MartDesignDraft",
    "ProviderDefinition",
    "ResourceDefinition",
    "SourceContract",
    "SourceProviderBinding",
    "SqlAsset",
    "StandardCodeNamespace",
]
