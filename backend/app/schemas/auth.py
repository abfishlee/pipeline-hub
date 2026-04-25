"""Pydantic DTOs — 인증 (login / refresh / me)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access token TTL in seconds")


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    login_id: str
    display_name: str
    email: str | None = None
    is_active: bool
    roles: list[str] = Field(default_factory=list)


__all__ = ["LoginRequest", "MeResponse", "TokenPair", "TokenRefreshRequest"]
