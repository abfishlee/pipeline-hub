"""HMAC SHA256 signature verification with replay protection (Phase 7 Wave 1A).

외부 시스템 (크롤러 / OCR / 소상공인 업로드) 의 push 인증을 위한 표준 verifier.

Stripe Webhook 패턴 채택:
  - timestamp 가 payload 와 함께 signed (replay protection)
  - replay window ±N초 (기본 300 = ±5분)
  - constant-time 비교 (timing attack 방지)

Headers (외부가 보내야 할 값):
  X-Signature: hmac-sha256=<hex>
  X-Timestamp: <unix epoch seconds>
  X-Idempotency-Key: <unique string per event>

서명 대상 문자열:
  f"{timestamp}.{raw_body_bytes.decode('utf-8')}"
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass

_SIG_PREFIX = "hmac-sha256="
_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class HmacVerificationError(ValueError):
    """검증 실패 — caller 가 401 로 변환."""


@dataclass(slots=True, frozen=True)
class HmacResult:
    """검증 성공 시 반환되는 정보."""

    timestamp: int
    signature_hex: str


def parse_signature_header(header_value: str | None) -> str:
    """`hmac-sha256=<hex>` 에서 hex 만 추출. 형식 오류 시 raise."""
    if not header_value:
        raise HmacVerificationError("missing X-Signature header")
    if not header_value.startswith(_SIG_PREFIX):
        raise HmacVerificationError(
            f"signature must start with '{_SIG_PREFIX}' (got prefix: "
            f"{header_value[:20]!r})"
        )
    sig_hex = header_value[len(_SIG_PREFIX) :].strip()
    if not _HEX_RE.match(sig_hex):
        raise HmacVerificationError(
            "signature must be 64-char hex (sha256)"
        )
    return sig_hex


def parse_timestamp_header(header_value: str | None) -> int:
    """unix epoch seconds 정수 변환. 형식 오류 시 raise."""
    if not header_value:
        raise HmacVerificationError("missing X-Timestamp header")
    try:
        return int(header_value)
    except (ValueError, TypeError) as exc:
        raise HmacVerificationError(
            f"timestamp must be integer epoch seconds (got: {header_value!r})"
        ) from exc


def compute_signature(
    *,
    secret: str,
    timestamp: int,
    payload: bytes,
) -> str:
    """`hex(HMAC-SHA256(secret, f"{timestamp}.{payload}"))`."""
    if not secret:
        raise HmacVerificationError("empty secret")
    msg = f"{timestamp}.".encode() + payload
    return hmac.new(
        secret.encode("utf-8"),
        msg=msg,
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_hmac_signature(
    *,
    payload: bytes,
    signature_header: str | None,
    timestamp_header: str | None,
    secret: str,
    replay_window_sec: int = 300,
    now: int | None = None,
) -> HmacResult:
    """검증 main entry. 실패 시 HmacVerificationError raise.

    글로벌 표준 (Stripe / GitHub Webhook):
      1. timestamp 형식 검증 + 변환
      2. replay window 검증 (|now - timestamp| ≤ replay_window_sec)
      3. signature 형식 검증
      4. expected signature 계산 + constant-time 비교
    """
    if replay_window_sec <= 0 or replay_window_sec > 3600:
        raise HmacVerificationError(
            f"replay_window_sec out of bounds: {replay_window_sec}"
        )

    ts = parse_timestamp_header(timestamp_header)
    now_epoch = now if now is not None else int(time.time())
    delta = abs(now_epoch - ts)
    if delta > replay_window_sec:
        raise HmacVerificationError(
            f"timestamp outside replay window — delta={delta}s, "
            f"max={replay_window_sec}s"
        )

    sig_hex = parse_signature_header(signature_header)
    expected_hex = compute_signature(
        secret=secret, timestamp=ts, payload=payload
    )
    if not hmac.compare_digest(expected_hex, sig_hex):
        raise HmacVerificationError(
            "signature mismatch — secret or payload tampered"
        )

    return HmacResult(timestamp=ts, signature_hex=sig_hex)


__all__ = [
    "HmacResult",
    "HmacVerificationError",
    "compute_signature",
    "parse_signature_header",
    "parse_timestamp_header",
    "verify_hmac_signature",
]
