"""Upstage Document OCR 클라이언트 (Phase 2.2.4 폴백 provider).

API 형태(Upstage `/v1/document-ai/ocr`):
  - POST {base_url}/v1/document-ai/ocr
  - 헤더: `Authorization: Bearer <api_key>`
  - 본문: multipart/form-data — `document`(file), `model`(default `ocr`)
  - 응답: `{"pages":[{"text":..., "confidence":..., "id":1, "words":[...]}]}`

CLOVA 가 일시 장애일 때 도메인이 두 번째 후보로 호출. 같은 `OcrProvider` 계약.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.integrations.ocr.circuit_breaker import CircuitBreaker
from app.integrations.ocr.types import OcrError, OcrPage, OcrResponse

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class UpstageOcrProvider:
    name = "upstage"

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 2,  # 폴백이라 재시도 횟수는 적게.
        breaker: CircuitBreaker | None = None,
    ) -> None:
        if not api_url or not api_key:
            raise ValueError("Upstage api_url and api_key are required")
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None
        self._max_retries = max_retries
        self._breaker = breaker or CircuitBreaker(failure_threshold=5, cooldown_sec=30.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def recognize(
        self,
        *,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
        request_id: str | None = None,
    ) -> OcrResponse:
        del request_id  # Upstage 는 idempotency 헤더 비요구.
        if not self._breaker.allow():
            raise OcrError("upstage circuit breaker is OPEN")

        files = {"document": ("receipt", image_bytes, content_type or "image/jpeg")}
        data = {"model": "ocr"}
        last_exc: Exception | None = None
        backoff = 0.5
        started = time.perf_counter()

        for _attempt in range(self._max_retries):
            try:
                resp = await self._client.post(
                    f"{self._api_url}/v1/document-ai/ocr",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    self._breaker.record_success()
                    return _parse_response(resp.json(), int((time.perf_counter() - started) * 1000))
                if resp.status_code in _RETRYABLE_STATUS:
                    last_exc = OcrError(f"upstage HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    self._breaker.record_failure()
                    raise OcrError(f"upstage HTTP {resp.status_code}: {resp.text[:200]}")

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        self._breaker.record_failure()
        raise OcrError(f"upstage all retries exhausted: {last_exc}")


def _parse_response(payload: dict[str, Any], duration_ms: int) -> OcrResponse:
    pages_in = payload.get("pages") or []
    if not pages_in:
        raise OcrError("upstage response: no pages")
    pages: list[OcrPage] = []
    for idx, p in enumerate(pages_in, start=1):
        text = str(p.get("text", "")).strip()
        conf_raw = p.get("confidence")
        try:
            confidence = float(conf_raw) if conf_raw is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        pages.append(
            OcrPage(
                page_no=int(p.get("id", idx)),
                text=text,
                confidence=round(confidence, 4),
                layout={"words": p.get("words", [])},
            )
        )
    return OcrResponse(
        provider="upstage",
        engine_version=str(payload.get("modelVersion", "")),
        pages=tuple(pages),
        duration_ms=duration_ms,
    )


__all__ = ["UpstageOcrProvider"]
