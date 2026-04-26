"""Shadow runner — v1 chain 과 registry path 병렬 실행 후 diff 적재 (Q2 답변).

흐름 (예: OCR):
  1. v1 worker 가 v1 OcrProvider chain (CLOVA → Upstage) 으로 *primary 결과* 산출.
  2. shadow runner 가 *동일 입력* 으로 registry path 시도. 실패해도 v1 path 영향 0.
  3. 결과 비교 (text 길이 / confidence / provider 일치) → audit 적재.
  4. 1주 비교 후 *registry path 가 v1 chain 만큼 안정* 이면 cutover (feature flag).

본 모듈은 *infrastructure* — 실제 v1 worker hook 은 5.2.1.1 의 후속 commit 에서
`shadow_run_async()` 호출 추가. STEP 4 MVP 는 인프라 + 단위 검증.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ShadowResult:
    v1_provider: str
    v1_success: bool
    registry_provider: str | None
    registry_success: bool
    matched: bool
    diff_summary: str | None
    duration_ms_v1: int
    duration_ms_registry: int


def record_shadow_diff(
    *,
    source_id: int,
    operation: str,
    v1_provider: str,
    v1_success: bool,
    registry_provider: str | None,
    registry_success: bool,
    matched: bool,
    diff_summary: str | None = None,
    duration_ms_v1: int = 0,
    duration_ms_registry: int = 0,
) -> None:
    """v1 vs registry 결과 비교를 audit 에 적재 (best-effort, fail-silent)."""
    try:
        sm = get_sync_sessionmaker()
        with sm() as session:
            session.execute(
                text(
                    "INSERT INTO domain.provider_health "
                    "(provider_code, source_id, state, last_error, occurred_at) "
                    "VALUES (:pc, :sid, :state, :err, :ts)"
                ),
                {
                    "pc": registry_provider or v1_provider,
                    "sid": source_id,
                    "state": "CLOSED" if registry_success else "OPEN",
                    "err": (
                        f"shadow:{operation} matched={matched} "
                        f"v1={v1_success} reg={registry_success} "
                        f"diff={diff_summary or 'none'}"
                    )[:1000],
                    "ts": datetime.now(UTC),
                },
            )
            session.commit()
    except Exception:
        logger.exception("shadow.record_failed")


async def shadow_run_async(
    *,
    primary_callable: Any,  # Awaitable
    registry_callable: Any | None,
    source_id: int,
    operation: str,
    v1_provider_label: str,
    registry_provider_label: str | None,
) -> tuple[Any, ShadowResult]:
    """v1 callable + registry callable 을 *병렬* 실행 후 비교.

    primary_callable 의 결과는 caller 에 *그대로 반환* (운영 동작 보존).
    registry_callable 은 best-effort — 예외/실패해도 primary 영향 0.
    """
    import time as _time

    started_v1 = _time.perf_counter()
    primary_result: Any = None
    primary_error: Exception | None = None
    try:
        primary_result = await primary_callable()
    except Exception as exc:  # caller 에 다시 던질 것.
        primary_error = exc
    duration_ms_v1 = int((_time.perf_counter() - started_v1) * 1000)

    duration_ms_registry = 0
    registry_result: Any = None
    registry_error: Exception | None = None
    if registry_callable is not None:
        started_reg = _time.perf_counter()
        try:
            registry_result = await asyncio.wait_for(registry_callable(), timeout=30.0)
        except Exception as exc:
            registry_error = exc
        duration_ms_registry = int((_time.perf_counter() - started_reg) * 1000)

    matched = primary_error is None and registry_error is None and (
        # 매우 단순한 비교 — caller 가 추후 더 정밀한 비교 추가 가능.
        type(primary_result) is type(registry_result)
    )

    diff_summary = None
    if not matched:
        diff_summary = (
            f"primary_err={type(primary_error).__name__ if primary_error else None} "
            f"registry_err={type(registry_error).__name__ if registry_error else None}"
        )

    record_shadow_diff(
        source_id=source_id,
        operation=operation,
        v1_provider=v1_provider_label,
        v1_success=primary_error is None,
        registry_provider=registry_provider_label,
        registry_success=registry_error is None,
        matched=matched,
        diff_summary=diff_summary,
        duration_ms_v1=duration_ms_v1,
        duration_ms_registry=duration_ms_registry,
    )

    if primary_error is not None:
        raise primary_error

    result = ShadowResult(
        v1_provider=v1_provider_label,
        v1_success=True,
        registry_provider=registry_provider_label,
        registry_success=registry_error is None,
        matched=matched,
        diff_summary=diff_summary,
        duration_ms_v1=duration_ms_v1,
        duration_ms_registry=duration_ms_registry,
    )
    return primary_result, result


__all__ = ["ShadowResult", "record_shadow_diff", "shadow_run_async"]
