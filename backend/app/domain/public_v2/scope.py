"""multi-domain scope 검증 + cache fingerprint (Phase 5.2.7 STEP 10).

핵심:
  * api_key.domain_resource_allowlist (JSONB) 가 도메인별 resource 허용 목록.
  * /public/v2/{domain}/{resource}/* 호출 시 본 모듈이 scope check.
  * 기존 retailer_allowlist 는 자동으로 agri 도메인에 매핑됨 (migration 0044).
  * Q4 — Redis 캐시 키에 domain/resource/scope_hash/schema_version 모두 포함.

JSONB 구조 (Q2 확장형):

    {
      "agri": {
        "resources": {
          "prices": {"retailer_ids": [1, 2]},
          "products": {}
        }
      },
      "pos": {
        "resources": {
          "transactions": {"shop_ids": [100]}
        }
      }
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class DomainScopeError(PermissionError):
    """scope check 실패 — caller 가 403 변환."""


@dataclass(slots=True, frozen=True)
class DomainScope:
    domain_code: str
    resource_code: str
    allowlist: dict[str, list[Any]] = field(default_factory=dict)

    def has_id(self, key: str, value: Any) -> bool:
        """allowlist 의 특정 key (예: 'retailer_ids') 에 value 포함 여부.
        allowlist 가 비어 있으면 *전체 허용* (Phase 5 MVP 단순화 — admin 만 발급).
        """
        if not self.allowlist:
            return True
        ids = self.allowlist.get(key)
        if not ids:
            return True
        return value in ids

    def fingerprint(self) -> str:
        """scope hash — Redis cache key 의 일부."""
        canonical = json.dumps(
            {
                "d": self.domain_code,
                "r": self.resource_code,
                "a": {k: sorted(v) for k, v in self.allowlist.items()},
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def map_v1_to_v2_compat(
    domain_resource_allowlist: Mapping[str, Any] | None,
    retailer_allowlist: list[int] | None,
) -> dict[str, Any]:
    """v1 의 retailer_allowlist 가 비어있지 않으면 *agri 도메인* allowlist 로 자동 매핑.

    Phase 5 호환 (Q1) — Phase 7 제거 검토.
    """
    base: dict[str, Any] = dict(domain_resource_allowlist or {})
    if retailer_allowlist:
        agri = dict(base.get("agri") or {})
        resources = dict(agri.get("resources") or {})
        prices = dict(resources.get("prices") or {})
        if not prices.get("retailer_ids"):
            prices["retailer_ids"] = list(retailer_allowlist)
            resources["prices"] = prices
            agri["resources"] = resources
            base["agri"] = agri
    return base


def api_key_has_domain(
    domain_resource_allowlist: Mapping[str, Any] | None,
    *,
    domain_code: str,
) -> bool:
    """domain_resource_allowlist 안에 domain_code 가 등록되어 있는지."""
    if not domain_resource_allowlist:
        return False
    return domain_code in domain_resource_allowlist


def extract_domain_allowlist(
    domain_resource_allowlist: Mapping[str, Any] | None,
    *,
    domain_code: str,
    resource_code: str,
) -> DomainScope:
    """domain × resource scope 추출. 등록 없으면 DomainScopeError.

    빈 allowlist (`{"agri":{"resources":{"prices":{}}}}`) 는 *resource 자체는 등록*
    이지만 specific id 제한 없음 (전체 read 허용).
    """
    if not domain_resource_allowlist:
        raise DomainScopeError(
            f"api_key has empty domain_resource_allowlist; cannot access {domain_code}"
        )
    if domain_code not in domain_resource_allowlist:
        raise DomainScopeError(
            f"api_key not authorized for domain {domain_code!r}"
        )
    domain_block = domain_resource_allowlist[domain_code] or {}
    resources = domain_block.get("resources") or {}
    if resource_code not in resources:
        raise DomainScopeError(
            f"api_key not authorized for {domain_code}.{resource_code}"
        )
    block = resources[resource_code] or {}
    allowlist: dict[str, list[Any]] = {}
    for k, v in block.items():
        if isinstance(v, list):
            allowlist[k] = list(v)
    return DomainScope(
        domain_code=domain_code,
        resource_code=resource_code,
        allowlist=allowlist,
    )


def cache_fingerprint(
    *,
    api_version: str,
    domain_code: str,
    resource_code: str,
    route: str,
    query_params: Mapping[str, Any],
    api_key_id: int,
    scope: DomainScope,
    schema_version: int | None = None,
) -> str:
    """Redis cache key 의 표준 fingerprint (Q4 확장).

    포함 요소: api_version / domain / resource / route / query_hash / scope_hash /
    api_key_id / schema_version.
    """
    qh = hashlib.sha256(
        json.dumps(
            {k: query_params[k] for k in sorted(query_params)},
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]
    parts = [
        f"public:{api_version}",
        domain_code,
        resource_code,
        route,
        f"q={qh}",
        f"s={scope.fingerprint()}",
        f"k={api_key_id}",
    ]
    if schema_version is not None:
        parts.append(f"v={schema_version}")
    return ":".join(parts)


__all__ = [
    "DomainScope",
    "DomainScopeError",
    "api_key_has_domain",
    "cache_fingerprint",
    "extract_domain_allowlist",
    "map_v1_to_v2_compat",
]
