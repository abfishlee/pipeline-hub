"""v2 provider registry — DB 기반 OCR/Crawler/HTTP_TRANSFORM provider 선택 + circuit
breaker (Phase 5.2.1.1).

ADR-0017 의 Hybrid 결정과 정합 — provider 정의/binding 은 정적 ORM (registry meta),
provider 호출은 abstract interface 기반.
"""

from __future__ import annotations

from app.domain.providers.circuit_breaker import (
    DEFAULT_POLICY,
    CircuitBreaker,
    CircuitState,
    FailoverPolicy,
)
from app.domain.providers.factory import (
    ProviderFactory,
    ProviderInstance,
    list_active_bindings,
    resolve_secret,
)
from app.domain.providers.shadow import (
    ShadowResult,
    record_shadow_diff,
    shadow_run_async,
)

__all__ = [
    "DEFAULT_POLICY",
    "CircuitBreaker",
    "CircuitState",
    "FailoverPolicy",
    "ProviderFactory",
    "ProviderInstance",
    "ShadowResult",
    "list_active_bindings",
    "record_shadow_diff",
    "resolve_secret",
    "shadow_run_async",
]
