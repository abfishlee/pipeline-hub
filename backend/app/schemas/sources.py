"""Pydantic DTOs — `ctl.data_source` CRUD."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# 외부 시스템과 충돌 없는 ASCII 식별자 — 대문자 시작 + 영숫자/언더스코어 3~64자.
SOURCE_CODE_PATTERN = r"^[A-Z][A-Z0-9_]{2,63}$"

SourceType = Literal["API", "OCR", "DB", "CRAWLER", "CROWD", "RECEIPT", "APP"]

SourceCodeStr = Annotated[str, StringConstraints(pattern=SOURCE_CODE_PATTERN, max_length=64)]


def _validate_cron(value: str | None) -> str | None:
    """croniter 기반 cron 표현식 검증. 빈 문자열/None 은 허용 (스케줄 없음)."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "":
        return None
    if not croniter.is_valid(stripped):
        raise ValueError(f"invalid cron expression: {stripped!r}")
    return stripped


class DataSourceCreate(BaseModel):
    source_code: SourceCodeStr
    source_name: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    retailer_id: int | None = Field(default=None, ge=1)
    owner_team: str | None = Field(default=None, max_length=100)
    is_active: bool = True
    config_json: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str | None = Field(default=None, max_length=200)
    cdc_enabled: bool = False

    @field_validator("schedule_cron")
    @classmethod
    def _check_cron(cls, v: str | None) -> str | None:
        return _validate_cron(v)


class DataSourceUpdate(BaseModel):
    """부분 업데이트 — 누락된 필드는 변경하지 않음.

    명시적 None 으로 보내면 nullable 필드는 NULL 로 비움.
    `source_code` 는 변경 불가 (외부 식별자 안정성 보장).
    """

    source_name: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: SourceType | None = None
    retailer_id: int | None = Field(default=None, ge=1)
    owner_team: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    config_json: dict[str, Any] | None = None
    schedule_cron: str | None = Field(default=None, max_length=200)
    cdc_enabled: bool | None = None

    @field_validator("schedule_cron")
    @classmethod
    def _check_cron(cls, v: str | None) -> str | None:
        return _validate_cron(v)


class CdcSubscriptionInfo(BaseModel):
    """Phase 4.2.3 — DataSourceOut 에 임베드되는 CDC slot 메타."""

    model_config = ConfigDict(from_attributes=True)

    subscription_id: int
    slot_name: str
    plugin: str
    enabled: bool
    last_committed_lsn: str | None
    last_lag_bytes: int | None
    last_polled_at: datetime | None


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: int
    source_code: str
    source_name: str
    source_type: SourceType
    retailer_id: int | None
    owner_team: str | None
    is_active: bool
    config_json: dict[str, Any]
    schedule_cron: str | None
    cdc_enabled: bool = False
    cdc: CdcSubscriptionInfo | None = None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "SOURCE_CODE_PATTERN",
    "CdcSubscriptionInfo",
    "DataSourceCreate",
    "DataSourceOut",
    "DataSourceUpdate",
    "SourceType",
]
