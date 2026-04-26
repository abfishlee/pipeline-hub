"""Pydantic DTOs — 사용자/역할 CRUD."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# email 은 단순 str 로 받고 저장 시 간단 포맷 검증 (pydantic[email] 의존 추가 회피).
# 엄격한 검증이 필요해지면 Phase 4 Public API 에서 email-validator 도입.
class UserCreate(BaseModel):
    login_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=256)
    password: str = Field(min_length=8, max_length=128)
    role_codes: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=256)
    is_active: bool | None = None
    # 비밀번호 변경은 별도 API (/v1/users/{id}/password) — Phase 1.2.4 이후 추가


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    login_id: str
    display_name: str
    email: str | None
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    created_at: datetime


class RoleAssign(BaseModel):
    role_codes: list[str] = Field(min_length=1, max_length=16)


class RoleOut(BaseModel):
    """ctl.role 1행 — 사용 가능한 역할 카탈로그 (Phase 4.0.5)."""

    model_config = ConfigDict(from_attributes=True)

    role_id: int
    role_code: str
    role_name: str
    description: str | None


__all__ = ["RoleAssign", "RoleOut", "UserCreate", "UserOut", "UserUpdate"]
