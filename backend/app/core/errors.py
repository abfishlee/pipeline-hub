"""Domain exception hierarchy.

API 레이어는 이 예외들을 HTTP status 로 변환한다 (app/main.py 의 핸들러).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class — 모든 도메인 예외의 루트."""

    http_status: int = 500
    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    http_status = 404
    code = "NOT_FOUND"


class ConflictError(DomainError):
    """중복/이미 존재/동시 수정 충돌."""

    http_status = 409
    code = "CONFLICT"


class ValidationError(DomainError):
    """비즈니스 유효성 실패 (Pydantic 수준 이후)."""

    http_status = 422
    code = "VALIDATION_ERROR"


class PermissionError(DomainError):
    http_status = 403
    code = "FORBIDDEN"


class AuthenticationError(DomainError):
    http_status = 401
    code = "UNAUTHENTICATED"


class IntegrationError(DomainError):
    """외부 서비스(CLOVA, Object Storage 등) 호출 실패."""

    http_status = 502
    code = "UPSTREAM_FAILURE"


class RateLimitedError(DomainError):
    http_status = 429
    code = "RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after_seconds = retry_after_seconds


# 별칭 — Phase 4.2.5 의 호출자는 RateLimitError 로 사용.
RateLimitError = RateLimitedError


class PayloadTooLargeError(DomainError):
    """요청 본문이 엔드포인트 제한을 초과 (예: 영수증 10MB 초과)."""

    http_status = 413
    code = "PAYLOAD_TOO_LARGE"


__all__ = [
    "AuthenticationError",
    "ConflictError",
    "DomainError",
    "IntegrationError",
    "NotFoundError",
    "PayloadTooLargeError",
    "PermissionError",
    "RateLimitError",
    "RateLimitedError",
    "ValidationError",
]
