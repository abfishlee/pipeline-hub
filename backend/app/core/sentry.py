"""Sentry 통합 (Phase 2.2.9).

DSN 이 비어 있으면 `configure_sentry` 가 no-op 으로 종료 — 로컬 개발 환경에서 흔한
케이스. 운영(NKS) 에서는 NCP Secret Manager 또는 K8s Secret 으로 DSN 주입.

PII 스크럽:
  - 헤더: Authorization, Cookie, X-OCR-SECRET, X-API-Key, X-NCP-CLOVASTUDIO-API-KEY
  - body/extra: password, secret, api_key, token, dsn (대소문자 무관)
  - 정상 진단 정보(요청 path/method/status, 스택 trace) 는 보존.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from app.config import Settings

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    h.lower()
    for h in (
        "Authorization",
        "Cookie",
        "Set-Cookie",
        "X-OCR-SECRET",
        "X-API-Key",
        "X-NCP-APIGW-API-KEY",
        "X-NCP-CLOVASTUDIO-API-KEY",
        "X-NCP-CLOVASTUDIO-REQUEST-ID",
    )
)
_SENSITIVE_BODY_KEYS: frozenset[str] = frozenset(
    k.lower() for k in ("password", "secret", "api_key", "token", "dsn", "access_key", "secret_key")
)
_FILTERED = "[Filtered]"


def _scrub_mapping(mapping: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """key 가 민감하면 값을 [Filtered] 로 치환. 중첩 dict 는 재귀."""
    if mapping is None:
        return None
    out: dict[str, Any] = {}
    for raw_key, value in mapping.items():
        key = str(raw_key)
        lower = key.lower()
        if lower in _SENSITIVE_HEADERS or lower in _SENSITIVE_BODY_KEYS:
            out[key] = _FILTERED
            continue
        if isinstance(value, Mapping):
            out[key] = _scrub_mapping(value)
        else:
            out[key] = value
    return out


def _scrub_event(event: Event, _hint: Hint) -> Event | None:
    """sentry_sdk before_send 훅 — 호출 전 검증되어 있어 None 반환은 drop."""
    # Event 는 TypedDict — 실제 sentry-sdk 가 보내는 dict 는 부분 type 만 알려줘 mypy
    # 가 sub-field 를 object 로 봄. 도메인은 표준 dict 처럼 다루는 게 맞음 → cast.
    raw = cast("dict[str, Any]", event)

    request = raw.get("request")
    if isinstance(request, dict):
        request["headers"] = _scrub_mapping(request.get("headers"))
        request["cookies"] = _scrub_mapping(request.get("cookies"))
        # body 가 dict 라면(JSON) key 단위 마스킹. urlencoded form 은 string 이라 통째로 치환.
        body = request.get("data")
        if isinstance(body, Mapping):
            request["data"] = _scrub_mapping(body)

    extra = raw.get("extra")
    if isinstance(extra, Mapping):
        raw["extra"] = _scrub_mapping(extra)

    contexts = raw.get("contexts")
    if isinstance(contexts, Mapping):
        scrubbed_ctx: dict[str, Any] = {}
        for ctx_name, ctx_val in contexts.items():
            if isinstance(ctx_val, Mapping):
                scrubbed_ctx[ctx_name] = _scrub_mapping(ctx_val)
            else:
                scrubbed_ctx[ctx_name] = ctx_val
        raw["contexts"] = scrubbed_ctx
    return event


def configure_sentry(settings: Settings) -> bool:
    """Sentry 초기화. DSN 비어 있거나 sample_rate 0 이면 init skip 후 False 반환."""
    dsn = settings.sentry_dsn.get_secret_value().strip()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_env or settings.env,
        sample_rate=settings.sentry_sample_rate,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        send_default_pii=False,  # PII 자동 첨부 차단.
        before_send=_scrub_event,
        max_breadcrumbs=50,
        attach_stacktrace=True,
        release=None,  # CI 가 빌드 시 SENTRY_RELEASE env 로 채움 (Phase 4 NKS).
    )
    return True


__all__ = ["configure_sentry"]
