"""stg schema ORM models — staging (표준화 전후 가격 관찰).

docs/03_DATA_MODEL.md 3.4 정합. 모든 채널이 공통 스키마로 평탄화되는 영역.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class StandardRecord(Base):
    """채널 무관 공통 표준 레코드 (entity_type 으로 분기)."""

    __tablename__ = "standard_record"
    __table_args__ = {"schema": "stg"}

    record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    raw_object_id: Mapped[int | None] = mapped_column(BigInteger)
    raw_partition: Mapped[date | None] = mapped_column()
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # PRODUCT/PRICE/RETAILER/SELLER
    business_key: Mapped[str | None] = mapped_column(Text)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    load_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceObservation(Base):
    """가격 관찰 전용 (자주 쓰므로 표준 레코드와 별도 컬럼화)."""

    __tablename__ = "price_observation"
    __table_args__ = {"schema": "stg"}

    obs_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.data_source.source_id"), nullable=False
    )
    raw_object_id: Mapped[int | None] = mapped_column(BigInteger)
    raw_partition: Mapped[date | None] = mapped_column()
    retailer_code: Mapped[str | None] = mapped_column(Text)
    seller_name: Mapped[str | None] = mapped_column(Text)
    store_name: Mapped[str | None] = mapped_column(Text)
    product_name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    std_code: Mapped[str | None] = mapped_column(Text, ForeignKey("mart.standard_code.std_code"))
    std_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    grade: Mapped[str | None] = mapped_column(Text)
    package_type: Mapped[str | None] = mapped_column(Text)
    sale_unit: Mapped[str | None] = mapped_column(Text)
    weight_g: Mapped[float | None] = mapped_column(Numeric(12, 2))
    brix: Mapped[float | None] = mapped_column(Numeric(5, 2))
    price_krw: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    discount_price_krw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="KRW")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    standardized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    load_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["PriceObservation", "StandardRecord"]
