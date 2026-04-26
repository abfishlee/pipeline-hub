"""Phase 5.1 Wave 4 — OCR/Crawler v1 worker 의 shadow hook.

목적: v1 worker 가 매 호출마다 *registry binding 도 함께 결정* + audit 적재.
실 OCR/Crawl 호출은 v1 path 그대로 — *cutover 전까지* registry path 는 비교만.

설계 (Q2 답변 — 1주 shadow 후 cutover):
  1. v1 worker 의 process_xxx() 시작 시 본 helper 호출.
  2. helper 가 source_id 의 binding 조회 → primary/fallbacks 결정 → audit.provider_health 적재.
  3. v1 path 는 그대로 진행 → 결과를 caller 에 반환.
  4. STAGING 1주 검토 후 feature flag (`APP_REGISTRY_PRIMARY_OCR=true`) 로 cutover.

단순함을 위해 *sync* 인터페이스. 실 비교는 별도 worker 가 audit 분석 (Phase 5.x).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker
from app.domain.providers.factory import (
    ProviderFactory,
    list_active_bindings,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ShadowBindingDecision:
    source_id: int
    provider_kind: str
    binding_count: int
    primary_provider: str | None
    fallback_providers: tuple[str, ...]
    decided_at: datetime


def record_shadow_binding(
    *,
    source_id: int,
    provider_kind: str,
    v1_provider_used: str | None,
) -> ShadowBindingDecision:
    """v1 worker 가 매 호출마다 호출. registry 가 *어떤 provider 를 골랐는지* 만 audit.

    실 OCR/Crawl 호출은 v1 path 가 진행. v1_provider_used 는 audit 비교용 라벨.
    fail-silent — 본 helper 의 실패는 v1 worker 에 전파 안 됨.
    """
    decision = ShadowBindingDecision(
        source_id=source_id,
        provider_kind=provider_kind,
        binding_count=0,
        primary_provider=None,
        fallback_providers=(),
        decided_at=datetime.now(UTC),
    )
    try:
        sm = get_sync_sessionmaker()
        with sm() as session:
            bindings = list_active_bindings(
                session, source_id=source_id, provider_kind=provider_kind
            )
            factory = ProviderFactory()
            result = factory.build(
                source_id=source_id,
                provider_kind=provider_kind,
                bindings=bindings,
            )
            primary_code = (
                result.primary.provider_code if result.primary is not None else None
            )
            fb_codes = tuple(p.provider_code for p in result.fallbacks)
            decision = ShadowBindingDecision(
                source_id=source_id,
                provider_kind=provider_kind,
                binding_count=len(bindings),
                primary_provider=primary_code,
                fallback_providers=fb_codes,
                decided_at=datetime.now(UTC),
            )
            # provider_health 1행 — registry 의 *결정* 자체를 보존.
            session.execute(
                text(
                    "INSERT INTO domain.provider_health "
                    "(provider_code, source_id, state, last_error, occurred_at) "
                    "VALUES (:pc, :sid, 'CLOSED', :note, :ts)"
                ),
                {
                    "pc": primary_code or v1_provider_used or "unknown",
                    "sid": source_id,
                    "note": (
                        f"shadow_binding:{provider_kind} "
                        f"primary={primary_code} fallbacks={list(fb_codes)} "
                        f"v1_used={v1_provider_used}"
                    )[:1000],
                    "ts": decision.decided_at,
                },
            )
            session.commit()
    except Exception:
        logger.warning(
            "shadow_binding.failed source=%s kind=%s",
            source_id,
            provider_kind,
            exc_info=True,
        )
    return decision


__all__ = ["ShadowBindingDecision", "record_shadow_binding"]
