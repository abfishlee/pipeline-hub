"""Provider factory — DB binding 기반 OCR/Crawler/HTTP_TRANSFORM 인스턴스 생성.

흐름:
  1. source_id + provider_kind → domain.source_provider_binding 의 priority 순 조회
  2. 각 binding 의 provider_code → provider_definition (implementation_type, secret_ref)
  3. internal_class 면 *기존 v1 클래스* 를 import (CLOVA/Upstage/HttpxSpider).
     external_api 면 *generic 클라이언트* + config_schema 의 endpoint/timeout.
  4. circuit breaker 상태 확인 — OPEN 이면 다음 fallback.

Phase 5.2.1.1 MVP — provider_kind = OCR / CRAWLER / HTTP_TRANSFORM 만. AI_TRANSFORM
은 Phase 6 (Q1 답변).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.providers.circuit_breaker import (
    DEFAULT_POLICY,
    CircuitBreaker,
    FailoverPolicy,
)
from app.models.domain import ProviderDefinition, SourceProviderBinding

logger = logging.getLogger(__name__)


@runtime_checkable
class ProviderInstance(Protocol):
    """모든 provider 가 만족하는 최소 공통 인터페이스."""

    provider_code: str
    provider_kind: str

    async def health_check(self) -> bool: ...


@dataclass(slots=True, frozen=True)
class _BindingRow:
    binding_id: int
    source_id: int
    provider_code: str
    provider_kind: str
    implementation_type: str
    priority: int
    fallback_order: int
    config: dict[str, Any]
    secret_ref: str | None


def list_active_bindings(
    session: Session, *, source_id: int, provider_kind: str
) -> list[_BindingRow]:
    """source_id 의 active binding 을 priority 순으로 반환."""
    rows = session.execute(
        select(
            SourceProviderBinding.binding_id,
            SourceProviderBinding.source_id,
            SourceProviderBinding.provider_code,
            ProviderDefinition.provider_kind,
            ProviderDefinition.implementation_type,
            SourceProviderBinding.priority,
            SourceProviderBinding.fallback_order,
            SourceProviderBinding.config_json,
            ProviderDefinition.secret_ref,
        )
        .join(
            ProviderDefinition,
            ProviderDefinition.provider_code == SourceProviderBinding.provider_code,
        )
        .where(SourceProviderBinding.source_id == source_id)
        .where(SourceProviderBinding.is_active.is_(True))
        .where(ProviderDefinition.is_active.is_(True))
        .where(ProviderDefinition.provider_kind == provider_kind)
        .order_by(SourceProviderBinding.priority, SourceProviderBinding.fallback_order)
    ).all()
    return [
        _BindingRow(
            binding_id=r.binding_id,
            source_id=r.source_id,
            provider_code=r.provider_code,
            provider_kind=r.provider_kind,
            implementation_type=r.implementation_type,
            priority=r.priority,
            fallback_order=r.fallback_order,
            config=dict(r.config_json or {}),
            secret_ref=r.secret_ref,
        )
        for r in rows
    ]


def resolve_secret(secret_ref: str | None) -> str | None:
    """secret_ref 를 실제 값으로 변환.

    Phase 5 MVP (Q3 답변) — env 만 지원. NCP Secret Manager 도입 시 본 함수만 확장.
    """
    if not secret_ref:
        return None
    # Settings 의 secret 필드 (예: clova_ocr_secret) 와 매핑.
    settings_attr = secret_ref.lower()
    from app.config import get_settings

    settings = get_settings()
    val = getattr(settings, settings_attr, None)
    if val is not None:
        try:
            return val.get_secret_value() if hasattr(val, "get_secret_value") else str(val)
        except Exception:
            return str(val)
    # fallback — raw env var.
    return os.environ.get(secret_ref)


@dataclass(slots=True, frozen=True)
class FactoryResult:
    """factory 호출 결과 — 1순위 provider + fallback 후보들."""

    primary: ProviderInstance | None
    fallbacks: tuple[ProviderInstance, ...]
    breakers: tuple[CircuitBreaker, ...]


@dataclass(slots=True)
class ProviderFactory:
    """provider_code → 실제 인스턴스 생성 (provider_kind 별로 분기).

    Phase 5.2.1.1 MVP 는 *생성* + *circuit breaker 매칭* 만 담당. 실제 호출 retry/
    fallback 루프는 caller (worker) 의 책임. 본 factory 가 *후보 + breaker 페어* 를
    제공하면 caller 가 try → fail → next 패턴으로 운영.
    """

    policy: FailoverPolicy = DEFAULT_POLICY

    def build(
        self, *, source_id: int, provider_kind: str, bindings: Iterable[_BindingRow]
    ) -> FactoryResult:
        instances: list[tuple[ProviderInstance, CircuitBreaker]] = []
        for b in bindings:
            instance = self._instantiate(b)
            if instance is None:
                continue
            cb = CircuitBreaker(
                provider_code=b.provider_code,
                source_id=source_id,
                policy=self.policy,
            )
            instances.append((instance, cb))
        if not instances:
            return FactoryResult(primary=None, fallbacks=(), breakers=())
        primary_instance, primary_breaker = instances[0]
        fb_instances = tuple(i for i, _ in instances[1:])
        all_breakers = tuple(cb for _, cb in instances)
        return FactoryResult(
            primary=primary_instance,
            fallbacks=fb_instances,
            breakers=all_breakers,
        )

    def _instantiate(self, b: _BindingRow) -> ProviderInstance | None:
        """provider_code + implementation_type → 실제 인스턴스.

        internal_class — Phase 1~4 의 v1 구현 (CLOVA/Upstage/HttpxSpider) 를 그대로 사용.
        external_api  — generic placeholder. config 의 endpoint/timeout 보유.
        """
        code = b.provider_code.lower()
        if b.implementation_type == "internal_class":
            try:
                if code == "clova_v2":
                    return _InternalClovaProvider(b)
                if code == "upstage":
                    return _InternalUpstageProvider(b)
                if code == "httpx_spider":
                    return _InternalHttpxSpiderProvider(b)
                if code == "playwright":
                    # placeholder — 본 PoC 시점은 미구현. health_check False 로 회피.
                    return _UnimplementedProvider(b)
            except Exception:
                logger.warning("provider %s instantiation failed", code, exc_info=True)
                return None
        if b.implementation_type == "external_api":
            return _ExternalApiProvider(b)
        return None


# ---------------------------------------------------------------------------
# Provider wrappers — v1 클라이언트를 ProviderInstance 인터페이스로 감쌈.
#
# 본 wrapper 는 *라이트하게* — 기존 v1 ocr_worker / crawler_worker 는 그대로 동작.
# Phase 5.2.1.1 MVP 의 wrapper 는 *factory 리졸루션 + health_check* 만 검증.
# 실제 OCR 호출은 v1 path 가 계속 담당, registry path 는 shadow 비교만.
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _InternalClovaProvider:
    binding: _BindingRow
    provider_code: str = "clova_v2"
    provider_kind: str = "OCR"

    async def health_check(self) -> bool:
        secret = resolve_secret(self.binding.secret_ref)
        return bool(secret)


@dataclass(slots=True)
class _InternalUpstageProvider:
    binding: _BindingRow
    provider_code: str = "upstage"
    provider_kind: str = "OCR"

    async def health_check(self) -> bool:
        secret = resolve_secret(self.binding.secret_ref)
        return bool(secret)


@dataclass(slots=True)
class _InternalHttpxSpiderProvider:
    binding: _BindingRow
    provider_code: str = "httpx_spider"
    provider_kind: str = "CRAWLER"

    async def health_check(self) -> bool:
        # httpx 는 별도 secret 없음. config 의 rate_limit 등만 검증.
        return True


@dataclass(slots=True)
class _UnimplementedProvider:
    """Phase 5.2.1.1 시점에 *placeholder* — playwright 등."""

    binding: _BindingRow
    provider_code: str = ""
    provider_kind: str = ""

    def __post_init__(self) -> None:
        # dataclass field 초기값을 binding 으로부터 치환.
        # frozen=False 라 직접 setattr 가능.
        object.__setattr__(self, "provider_code", self.binding.provider_code)
        object.__setattr__(self, "provider_kind", self.binding.provider_kind)

    async def health_check(self) -> bool:
        return False


@dataclass(slots=True)
class _ExternalApiProvider:
    """external_api 형 provider — 외부 정제/OCR/스크래핑 서비스 일반."""

    binding: _BindingRow
    provider_code: str = ""
    provider_kind: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_code", self.binding.provider_code)
        object.__setattr__(self, "provider_kind", self.binding.provider_kind)

    async def health_check(self) -> bool:
        # 실 ping 은 후속 phase — 현재는 endpoint 존재 여부만.
        return bool(self.binding.config.get("endpoint"))


__all__ = [
    "FactoryResult",
    "ProviderFactory",
    "ProviderInstance",
    "list_active_bindings",
    "resolve_secret",
]
