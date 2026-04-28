"""HTTP — `/v1/inbound/{channel_code}` (Phase 7 Wave 1A — 외부 push receiver).

Stripe Webhook 패턴:
  - X-Signature: hmac-sha256=<hex>
  - X-Timestamp: <unix epoch seconds>
  - X-Idempotency-Key: <unique per event>
  - Body: raw bytes (JSON / XML / multipart 등 채널별 다름)

처리:
  1. channel_code 로 InboundChannel 조회 (PUBLISHED + is_active 만)
  2. payload 크기 검증 (max_payload_bytes)
  3. HMAC SHA256 검증 (replay window ±N초)
  4. idempotency 체크 — 같은 (channel_code, idempotency_key) 가 이미 RECEIVED+ 면 409
  5. payload 저장 — small (≤8KB JSON) 은 inline, 그 외는 NCP Object Storage
  6. audit.inbound_event INSERT (status=RECEIVED)
  7. 202 Accepted (async — Wave 6 에서 outbox publish + workflow trigger)

응답:
  202 — 정상 수신
  401 — HMAC 불일치 / replay window 초과 / 누락 헤더
  404 — channel_code 없음 또는 비활성
  409 — 동일 idempotency_key 중복
  413 — payload 초과
  422 — content_type 불일치
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets as secrets_mod
import uuid
from typing import Any

import hmac as _hmac

from fastapi import APIRouter, Header, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.hmac_verifier import HmacVerificationError, verify_hmac_signature
from app.core.request_context import set_request_id
from app.db.sync_session import get_sync_sessionmaker
from app.domain.inbound_contracts import (
    get_contract,
    validate_payload_against_contract,
)
from app.integrations.object_storage import get_object_storage
from app.models.domain import InboundChannel

logger = logging.getLogger(__name__)

# 8KB 이하 JSON 은 inline 저장 (raw payload 빠른 조회).
_INLINE_THRESHOLD_BYTES = 8 * 1024

router = APIRouter(prefix="/v1/inbound", tags=["v1-inbound"])


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


def _resolve_secret(secret_ref: str) -> str:
    """secret_ref → 실제 값. env 우선, 향후 NCP Secret Manager.

    Phase 7 Wave 1A: env only. Phase 7 Wave 2+ 에서 secret manager 통합.
    """
    import os

    val = os.getenv(secret_ref)
    if not val:
        raise HTTPException(
            500,
            detail=f"secret_ref {secret_ref!r} not configured in environment",
        )
    return val


def _build_object_key(
    *, channel_code: str, envelope_id: int, content_type: str
) -> str:
    """object storage 의 raw payload 위치."""
    ext = "bin"
    if "json" in content_type:
        ext = "json"
    elif "xml" in content_type:
        ext = "xml"
    elif "csv" in content_type:
        ext = "csv"
    elif content_type.startswith("image/"):
        ext = content_type.split("/", 1)[1].split(";", 1)[0]
    return f"inbound/{channel_code}/{envelope_id}.{ext}"


def _safe_ip(ip_addr: str | None) -> str | None:
    """INET 컬럼에 캐스팅 가능한 값만 통과 — TestClient 'testclient' 같은 hostname 은
    NULL 처리. ip_address 파싱 실패 시 NULL 반환."""
    if not ip_addr:
        return None
    import ipaddress

    try:
        ipaddress.ip_address(ip_addr)
        return ip_addr
    except ValueError:
        return None


def _record_security_event(
    *, kind: str, ip_addr: str | None, user_agent: str | None, details: dict[str, Any]
) -> None:
    """audit.security_event INSERT — best-effort, 인증 실패 audit."""
    sm = get_sync_sessionmaker()
    try:
        with sm() as session:
            session.execute(
                text(
                    "INSERT INTO audit.security_event "
                    "(kind, severity, ip_addr, user_agent, details_json) "
                    "VALUES (:k, 'WARN', :ip, :ua, CAST(:d AS JSONB))"
                ),
                {
                    "k": kind,
                    "ip": _safe_ip(ip_addr),
                    "ua": user_agent,
                    "d": json.dumps(details),
                },
            )
            session.commit()
    except Exception as exc:
        # security_event 기록 실패는 인증 실패 응답을 가리지 않게 swallow.
        logger.warning("inbound.security_event_insert_failed", exc_info=exc)


@router.post("/{channel_code}", status_code=202)
async def receive_inbound_event(
    request: Request,
    channel_code: str = Path(..., pattern=r"^[a-z][a-z0-9_]{1,62}$"),
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
    x_idempotency_key: str | None = Header(
        default=None, alias="X-Idempotency-Key"
    ),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> JSONResponse:
    """외부 시스템 push receiver (HMAC + idempotency + replay protection)."""
    # ── 1. 헤더 / 메타 ──────────────────────────────────────────────────
    if not x_idempotency_key:
        raise HTTPException(
            422, detail="X-Idempotency-Key header required"
        )
    if len(x_idempotency_key) > 200:
        raise HTTPException(
            422, detail="X-Idempotency-Key too long (max 200)"
        )

    request_id = (
        request.headers.get("X-Request-ID") or uuid.uuid4().hex
    )
    set_request_id(request_id)
    sender_ip = _safe_ip(request.client.host if request.client else None)
    user_agent = request.headers.get("User-Agent")
    content_type = request.headers.get("Content-Type", "application/octet-stream")

    payload = await request.body()
    payload_size = len(payload)

    # ── 2. Channel 조회 ─────────────────────────────────────────────────
    def _load_channel(s: Session) -> InboundChannel:
        from sqlalchemy import select as _select

        m = s.execute(
            _select(InboundChannel).where(
                InboundChannel.channel_code == channel_code
            )
        ).scalar_one_or_none()
        if m is None or not m.is_active:
            raise HTTPException(404, detail=f"channel {channel_code!r} not found or inactive")
        if m.status != "PUBLISHED":
            raise HTTPException(
                404,
                detail=(
                    f"channel {channel_code!r} status={m.status}, "
                    "only PUBLISHED accepts inbound"
                ),
            )
        return m

    channel = await asyncio.to_thread(_run_in_sync, _load_channel)

    # ── 3. payload 크기 + content_type 검증 ────────────────────────────
    if payload_size > channel.max_payload_bytes:
        raise HTTPException(
            413,
            detail=(
                f"payload {payload_size}B exceeds channel max "
                f"{channel.max_payload_bytes}B"
            ),
        )
    if (
        channel.expected_content_type
        and channel.expected_content_type not in content_type
    ):
        raise HTTPException(
            422,
            detail=(
                f"content_type mismatch — expected "
                f"{channel.expected_content_type!r}, got {content_type!r}"
            ),
        )

    # ── 4. HMAC 검증 (auth_method == hmac_sha256) ──────────────────────
    if channel.auth_method == "hmac_sha256":
        try:
            secret = _resolve_secret(channel.secret_ref)
            verify_hmac_signature(
                payload=payload,
                signature_header=x_signature,
                timestamp_header=x_timestamp,
                secret=secret,
                replay_window_sec=channel.replay_window_sec,
            )
        except HmacVerificationError as exc:
            logger.warning(
                "inbound.hmac_failed",
                extra={
                    "channel_code": channel_code,
                    "request_id": request_id,
                    "reason": str(exc),
                },
            )
            raise HTTPException(401, detail=str(exc)) from exc
    elif channel.auth_method == "api_key":
        # Phase 8.4 — channel.secret_ref 가 가리키는 env 의 값과 X-API-Key 헤더를
        # constant-time 비교. 실패 시 audit.security_event(KIND='OTHER') + 401.
        # 외부 OCR/Crawler 업체가 X-API-Key 만 보내는 단순 case 를 지원.
        if not x_api_key:
            _record_security_event(
                kind="OTHER",
                ip_addr=sender_ip,
                user_agent=user_agent,
                details={
                    "reason": "missing_api_key",
                    "channel_code": channel_code,
                    "request_id": request_id,
                },
            )
            raise HTTPException(401, detail="X-API-Key header required")
        try:
            expected = _resolve_secret(channel.secret_ref)
        except HTTPException:
            raise
        if not _hmac.compare_digest(x_api_key, expected):
            _record_security_event(
                kind="OTHER",
                ip_addr=sender_ip,
                user_agent=user_agent,
                details={
                    "reason": "api_key_mismatch",
                    "channel_code": channel_code,
                    "request_id": request_id,
                },
            )
            logger.warning(
                "inbound.api_key_mismatch",
                extra={
                    "channel_code": channel_code,
                    "request_id": request_id,
                },
            )
            raise HTTPException(401, detail="invalid X-API-Key")
    elif channel.auth_method == "mtls":
        # Phase 9 — mTLS (NCP NLB / Ingress 종단 인증서 검증).
        raise HTTPException(
            501,
            detail="auth_method 'mtls' not yet implemented (Phase 9)",
        )

    # ── 5. payload 저장 + envelope INSERT ───────────────────────────────
    is_inline = (
        payload_size <= _INLINE_THRESHOLD_BYTES and "json" in content_type
    )
    payload_inline_dict: dict[str, Any] | None = None
    parsed_json_payload: Any | None = None
    if is_inline:
        try:
            parsed_json_payload = json.loads(payload.decode("utf-8"))
            payload_inline_dict = parsed_json_payload
            if not isinstance(payload_inline_dict, dict):
                # JSON list 등은 dict 로 wrapping
                payload_inline_dict = {"data": payload_inline_dict}
        except (json.JSONDecodeError, UnicodeDecodeError):
            is_inline = False  # JSON 파싱 실패 시 object storage 로 fallback

    if "json" in content_type:
        if parsed_json_payload is None:
            try:
                parsed_json_payload = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise HTTPException(422, detail="invalid JSON payload") from exc

        def _validate_contract(s: Session) -> None:
            contract = get_contract(s, channel_code)
            if contract is None or not contract.get("reject_on_schema_mismatch", True):
                return
            result = validate_payload_against_contract(parsed_json_payload, contract)
            if not result.ok:
                raise HTTPException(
                    422,
                    detail={
                        "message": "payload does not match inbound contract",
                        "errors": result.errors[:20],
                    },
                )

        await asyncio.to_thread(_run_in_sync, _validate_contract)

    object_key: str | None = None
    if not is_inline:
        # 임시 envelope_id 생성용 — INSERT 후 실 id 로 rename 은 Wave 1B 에서.
        # 우선은 random 기반 key 로 저장 후 envelope row 에 기록.
        tmp_id = secrets_mod.token_hex(16)
        object_key = (
            f"inbound/{channel_code}/{tmp_id}." +
            ("json" if "json" in content_type else "bin")
        )
        try:
            storage = get_object_storage()
            await storage.put(object_key, payload, content_type=content_type)
        except Exception as exc:
            logger.error(
                "inbound.object_storage_put_failed",
                extra={"channel_code": channel_code, "request_id": request_id},
                exc_info=exc,
            )
            raise HTTPException(
                500, detail="failed to persist payload to object storage"
            ) from exc

    # envelope INSERT (idempotency UNIQUE 위반 → 409)
    def _insert_envelope(s: Session) -> int:
        try:
            row = s.execute(
                text(
                    "INSERT INTO audit.inbound_event "
                    "(channel_code, channel_id, domain_code, idempotency_key, "
                    " sender_signature, sender_ip, user_agent, request_id, "
                    " content_type, payload_size_bytes, payload_object_key, "
                    " payload_inline, status) "
                    "VALUES (:cc, :cid, :dc, :ik, :sig, :ip, :ua, :rid, :ct, "
                    "        :sz, :ok, CAST(:inline AS JSONB), 'RECEIVED') "
                    "RETURNING envelope_id"
                ),
                {
                    "cc": channel_code,
                    "cid": channel.channel_id,
                    "dc": channel.domain_code,
                    "ik": x_idempotency_key,
                    "sig": x_signature,
                    "ip": sender_ip,
                    "ua": user_agent,
                    "rid": request_id,
                    "ct": content_type,
                    "sz": payload_size,
                    "ok": object_key,
                    "inline": json.dumps(payload_inline_dict) if payload_inline_dict else None,
                },
            ).first()
            assert row is not None
            return int(row[0])
        except Exception as exc:
            # idempotency UNIQUE 위반 식별
            if "uq_inbound_event_idempotency" in str(exc):
                raise HTTPException(
                    409,
                    detail=(
                        f"duplicate idempotency_key {x_idempotency_key!r} "
                        f"for channel {channel_code}"
                    ),
                ) from exc
            raise

    envelope_id = await asyncio.to_thread(_run_in_sync, _insert_envelope)

    # ── 6. 202 Accepted ─────────────────────────────────────────────────
    settings = get_settings()
    return JSONResponse(
        status_code=202,
        content={
            "envelope_id": envelope_id,
            "channel_code": channel_code,
            "received_at": "now",
            "status": "RECEIVED",
            "next_step": (
                "workflow trigger via outbox dispatcher "
                "(Phase 7 Wave 6 — 현재는 수동 trigger)"
            ),
            "request_id": request_id,
            "env": settings.env,
        },
    )


__all__ = ["router"]
