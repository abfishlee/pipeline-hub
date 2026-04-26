"""Phase 5.2.7 STEP 10 — public/v2 domain-aware helper.

multi-domain api_key scope check + RLS GUC + cache fingerprint 확장.
"""

from __future__ import annotations

from app.domain.public_v2.scope import (
    DomainScope,
    DomainScopeError,
    api_key_has_domain,
    cache_fingerprint,
    extract_domain_allowlist,
    map_v1_to_v2_compat,
)

__all__ = [
    "DomainScope",
    "DomainScopeError",
    "api_key_has_domain",
    "cache_fingerprint",
    "extract_domain_allowlist",
    "map_v1_to_v2_compat",
]
