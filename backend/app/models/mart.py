"""mart schema ORM models — service-facing master tables.

docs/03_DATA_MODEL.md 3.5 정합. price_fact 는 월 파티션 (BRIN + product/seller 인덱스).
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
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class StandardCode(Base):
    """농림축산식품부 / aT 기반 표준 품목 코드."""

    __tablename__ = "standard_code"
    __table_args__ = {"schema": "mart"}

    std_code: Mapped[str] = mapped_column(Text, primary_key=True)
    category_lv1: Mapped[str] = mapped_column(Text, nullable=False)
    category_lv2: Mapped[str | None] = mapped_column(Text)
    category_lv3: Mapped[str | None] = mapped_column(Text)
    item_name_ko: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    default_unit: Mapped[str | None] = mapped_column(Text)
    source_authority: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RetailerMaster(Base):
    __tablename__ = "retailer_master"
    __table_args__ = (
        CheckConstraint(
            "retailer_type IN ('MART','SSM','LOCAL','ONLINE','TRAD_MARKET','APP')",
            name="ck_retailer_master_type",
        ),
        {"schema": "mart"},
    )

    retailer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    retailer_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    retailer_name: Mapped[str] = mapped_column(Text, nullable=False)
    retailer_type: Mapped[str] = mapped_column(Text, nullable=False)
    business_no: Mapped[str | None] = mapped_column(Text)
    head_office_addr: Mapped[str | None] = mapped_column(Text)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SellerMaster(Base):
    __tablename__ = "seller_master"
    __table_args__ = (
        UniqueConstraint("retailer_id", "seller_code", name="uq_seller_master_retailer_code"),
        CheckConstraint("channel IN ('OFFLINE','ONLINE')", name="ck_seller_master_channel"),
        {"schema": "mart"},
    )

    seller_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    retailer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mart.retailer_master.retailer_id")
    )
    seller_code: Mapped[str] = mapped_column(Text, nullable=False)
    seller_name: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    region_sido: Mapped[str | None] = mapped_column(Text)
    region_sigungu: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    # geo_point: PostgreSQL POINT 타입은 별도. 마이그레이션에서 추가.
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductMaster(Base):
    __tablename__ = "product_master"
    __table_args__ = (
        UniqueConstraint(
            "std_code",
            "grade",
            "package_type",
            "sale_unit_norm",
            "weight_g",
            name="uq_product_master_business_key",
        ),
        {"schema": "mart"},
    )

    product_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    std_code: Mapped[str] = mapped_column(
        Text, ForeignKey("mart.standard_code.std_code"), nullable=False
    )
    grade: Mapped[str | None] = mapped_column(Text)
    package_type: Mapped[str | None] = mapped_column(Text)
    sale_unit_norm: Mapped[str | None] = mapped_column(Text)
    weight_g: Mapped[float | None] = mapped_column(Numeric(12, 2))
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 2))


class ProductMapping(Base):
    __tablename__ = "product_mapping"
    __table_args__ = (
        CheckConstraint(
            "match_method IN ('EMBEDDING','RULE','HUMAN','ALIAS')",
            name="ck_product_mapping_match_method",
        ),
        {"schema": "mart"},
    )

    mapping_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    retailer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mart.retailer_master.retailer_id"), nullable=False
    )
    retailer_product_code: Mapped[str | None] = mapped_column(Text)
    raw_product_name: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mart.product_master.product_id"), nullable=False
    )
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    verified_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceFact(Base):
    """파티션 테이블 — RANGE(partition_date), append-heavy."""

    __tablename__ = "price_fact"
    __table_args__ = (
        PrimaryKeyConstraint("price_id", "partition_date", name="pk_price_fact"),
        {
            "schema": "mart",
            "postgresql_partition_by": "RANGE (partition_date)",
        },
    )

    price_id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mart.product_master.product_id"), nullable=False
    )
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mart.seller_master.seller_id"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_krw: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    discount_price_krw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    unit_price_per_kg: Mapped[float | None] = mapped_column(Numeric(14, 2))
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_object_id: Mapped[int | None] = mapped_column(BigInteger)
    partition_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceDailyAgg(Base):
    """일별 집계 — 매일 00:30 Airflow DAG 가 UPSERT (Phase 2)."""

    __tablename__ = "price_daily_agg"
    __table_args__ = (
        PrimaryKeyConstraint(
            "agg_date", "std_code", "retailer_id", "region_sido", name="pk_price_daily_agg"
        ),
        {"schema": "mart"},
    )

    agg_date: Mapped[date] = mapped_column(Date, nullable=False)
    std_code: Mapped[str] = mapped_column(
        Text, ForeignKey("mart.standard_code.std_code"), nullable=False
    )
    retailer_id: Mapped[int | None] = mapped_column(BigInteger)
    region_sido: Mapped[str | None] = mapped_column(Text)
    min_price_krw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    avg_price_krw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    max_price_krw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    median_price_krw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    obs_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MasterEntityHistory(Base):
    __tablename__ = "master_entity_history"
    __table_args__ = {"schema": "mart"}

    history_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    changed_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "MasterEntityHistory",
    "PriceDailyAgg",
    "PriceFact",
    "ProductMapping",
    "ProductMaster",
    "RetailerMaster",
    "SellerMaster",
    "StandardCode",
]
