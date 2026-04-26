"""HTTP — `/v2/inbound-channels` (Phase 7 Wave 1A — 외부 push 채널 CRUD).

외부 시스템 (크롤러 / OCR 업체 / 소상공인 업로드 등) 의 push 채널을 등록·관리.
실제 push 데이터 수신은 `/v1/inbound/{channel_code}` 별도 라우트.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.models.domain import DomainDefinition, InboundChannel

router = APIRouter(
    prefix="/v2/inbound-channels",
    tags=["v2-inbound-channels"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class InboundChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_id: int
    channel_code: str
    domain_code: str
    name: str
    description: str | None
    channel_kind: str
    secret_ref: str
    auth_method: str
    expected_content_type: str | None
    max_payload_bytes: int
    rate_limit_per_min: int
    replay_window_sec: int
    workflow_id: int | None
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InboundChannelIn(BaseModel):
    channel_code: str = Field(
        min_length=2, max_length=63, pattern=r"^[a-z][a-z0-9_]{1,62}$"
    )
    domain_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    channel_kind: str = Field(
        pattern=r"^(WEBHOOK|FILE_UPLOAD|OCR_RESULT|CRAWLER_RESULT)$"
    )
    secret_ref: str = Field(min_length=1, max_length=200)
    auth_method: str = Field(
        default="hmac_sha256", pattern=r"^(hmac_sha256|api_key|mtls)$"
    )
    expected_content_type: str | None = None
    max_payload_bytes: int = Field(default=10_485_760, ge=1024, le=1_073_741_824)
    rate_limit_per_min: int = Field(default=100, ge=1, le=100_000)
    replay_window_sec: int = Field(default=300, ge=30, le=3600)
    workflow_id: int | None = None


class InboundChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    secret_ref: str | None = Field(default=None, min_length=1, max_length=200)
    expected_content_type: str | None = None
    max_payload_bytes: int | None = Field(default=None, ge=1024, le=1_073_741_824)
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=100_000)
    replay_window_sec: int | None = Field(default=None, ge=30, le=3600)
    workflow_id: int | None = None
    is_active: bool | None = None


class StatusTransitionRequest(BaseModel):
    target_status: str = Field(pattern=r"^(REVIEW|APPROVED|PUBLISHED|DRAFT)$")


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        try:
            res = fn(session)
            session.commit()
            return res
        except Exception:
            session.rollback()
            raise


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[InboundChannelOut])
async def list_channels(
    domain_code: str | None = None,
    channel_kind: str | None = None,
    status: str | None = None,
) -> list[InboundChannelOut]:
    def _do(s: Session) -> list[InboundChannelOut]:
        q = select(InboundChannel).order_by(InboundChannel.channel_code)
        if domain_code:
            q = q.where(InboundChannel.domain_code == domain_code)
        if channel_kind:
            q = q.where(InboundChannel.channel_kind == channel_kind)
        if status:
            q = q.where(InboundChannel.status == status)
        rows = s.execute(q).scalars().all()
        return [InboundChannelOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/{channel_id}", response_model=InboundChannelOut)
async def get_channel(channel_id: int) -> InboundChannelOut:
    def _do(s: Session) -> InboundChannelOut:
        m = s.get(InboundChannel, channel_id)
        if m is None:
            raise HTTPException(404, detail=f"channel {channel_id} not found")
        return InboundChannelOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post("", response_model=InboundChannelOut, status_code=201)
async def create_channel(
    body: InboundChannelIn, user: CurrentUserDep
) -> InboundChannelOut:
    def _do(s: Session) -> InboundChannelOut:
        if s.get(DomainDefinition, body.domain_code) is None:
            raise HTTPException(404, detail=f"domain {body.domain_code} not found")
        dup = s.execute(
            select(InboundChannel).where(
                InboundChannel.channel_code == body.channel_code
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                409,
                detail=f"channel_code {body.channel_code!r} already exists",
            )
        m = InboundChannel(
            channel_code=body.channel_code,
            domain_code=body.domain_code,
            name=body.name,
            description=body.description,
            channel_kind=body.channel_kind,
            secret_ref=body.secret_ref,
            auth_method=body.auth_method,
            expected_content_type=body.expected_content_type,
            max_payload_bytes=body.max_payload_bytes,
            rate_limit_per_min=body.rate_limit_per_min,
            replay_window_sec=body.replay_window_sec,
            workflow_id=body.workflow_id,
            status="DRAFT",
            is_active=True,
            created_by=user.user_id,
        )
        s.add(m)
        s.flush()
        return InboundChannelOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.patch("/{channel_id}", response_model=InboundChannelOut)
async def update_channel(
    channel_id: int, body: InboundChannelUpdate, user: CurrentUserDep
) -> InboundChannelOut:
    del user

    def _do(s: Session) -> InboundChannelOut:
        m = s.get(InboundChannel, channel_id)
        if m is None:
            raise HTTPException(404, detail=f"channel {channel_id} not found")
        if m.status != "DRAFT":
            raise HTTPException(
                409,
                detail=(
                    f"channel status={m.status} — DRAFT 만 직접 수정 가능. "
                    "PUBLISHED 는 새 channel_code 로 등록."
                ),
            )
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(m, field_name, value)
        s.flush()
        return InboundChannelOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(channel_id: int) -> Response:
    def _do(s: Session) -> None:
        m = s.get(InboundChannel, channel_id)
        if m is None:
            raise HTTPException(404, detail=f"channel {channel_id} not found")
        if m.status == "PUBLISHED":
            raise HTTPException(
                409,
                detail="PUBLISHED channel 은 삭제 불가 — DRAFT 로 transition 후",
            )
        s.delete(m)

    await asyncio.to_thread(_run_in_sync, _do)
    return Response(status_code=204)


@router.post("/{channel_id}/transition", response_model=InboundChannelOut)
async def transition_channel(
    channel_id: int, body: StatusTransitionRequest, user: CurrentUserDep
) -> InboundChannelOut:
    valid: dict[str, set[str]] = {
        "DRAFT": {"REVIEW"},
        "REVIEW": {"APPROVED", "DRAFT"},
        "APPROVED": {"PUBLISHED", "DRAFT"},
        "PUBLISHED": {"DRAFT"},
    }

    def _do(s: Session) -> InboundChannelOut:
        m = s.get(InboundChannel, channel_id)
        if m is None:
            raise HTTPException(404, detail=f"channel {channel_id} not found")
        if body.target_status not in valid.get(m.status, set()):
            raise HTTPException(
                422,
                detail=(
                    f"transition {m.status}→{body.target_status} not allowed. "
                    f"valid: {sorted(valid.get(m.status, set()))}"
                ),
            )
        if body.target_status == "APPROVED":
            m.approved_by = user.user_id
        m.status = body.target_status
        s.flush()
        return InboundChannelOut.model_validate(m)

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
