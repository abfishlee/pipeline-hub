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


__all__ = [
    "DomainDefinition",
    "DqRule",
    "FieldMapping",
    "LoadPolicy",
    "ProviderDefinition",
    "ResourceDefinition",
    "SourceContract",
    "SourceProviderBinding",
    "StandardCodeNamespace",
]
