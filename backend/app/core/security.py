"""JWT issue/verify + password hashing (Argon2id).

Phase 1.2.4(인증)에서 본격 사용.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.config import Settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    """Argon2id 해시."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(
    subject: str | int,
    *,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.jwt_access_ttl_min)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(subject: str | int, *, settings: Settings) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(days=settings.jwt_refresh_ttl_days)
    payload = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "refresh",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str, *, settings: Settings) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        raise AuthenticationError("invalid or expired token") from exc


__all__ = [
    "JWT_ALGORITHM",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
