"""API Key schemas (Phase 4.2.5).

scope 정의:
  - prices.read       — /public/v1/prices/* 만
  - products.read     — /public/v1/products + /standard-codes
  - aggregates.read   — /public/v1/prices/daily + /prices/series
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PublicApiScope = Literal["prices.read", "products.read", "aggregates.read"]


class ApiKeyCreate(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    scope: list[PublicApiScope] = Field(default_factory=list)
    retailer_allowlist: list[int] = Field(default_factory=list)
    rate_limit_per_min: int = Field(default=60, ge=0, le=100_000)
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    """평문 secret 미포함 — 발급 시 1회만 ApiKeyCreated 로 노출."""

    model_config = ConfigDict(from_attributes=True)

    api_key_id: int
    key_prefix: str
    client_name: str
    scope: list[str]
    retailer_allowlist: list[int]
    rate_limit_per_min: int
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    """발급 응답 — `secret` 평문 1회 노출."""

    secret: str


__all__ = [
    "ApiKeyCreate",
    "ApiKeyCreated",
    "ApiKeyOut",
    "PublicApiScope",
]
