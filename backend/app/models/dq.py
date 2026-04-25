"""dq schema ORM — Data Quality (Phase 3.2.2~)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class QualityResult(Base):
    """DQ_CHECK 노드의 검사 결과. 실패 row 는 운영자가 dashboard 에서 추적."""

    __tablename__ = "quality_result"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO','WARN','ERROR','BLOCK')",
            name="ck_dq_severity",
        ),
        CheckConstraint(
            "check_kind IN ('row_count_min','null_pct_max','unique_columns','custom_sql')",
            name="ck_dq_check_kind",
        ),
        {"schema": "dq"},
    )

    quality_result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int | None] = mapped_column(BigInteger)
    node_run_id: Mapped[int | None] = mapped_column(BigInteger)
    target_table: Mapped[str] = mapped_column(Text, nullable=False)
    check_kind: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="WARN")
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["QualityResult"]
