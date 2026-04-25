"""CLOVA OCR Document API 클라이언트.

API 형태(NCP CLOVA OCR Document/Template):
  - POST {APP_CLOVA_OCR_URL}
  - 헤더: `X-OCR-SECRET: {APP_CLOVA_OCR_SECRET}`, `Content-Type: application/json`
  - 본문: JSON, base64 image, requestId, version="V2", timestamp, lang
  - 응답: `{"version": "V2", "requestId": ..., "images": [{ "fields": [...], "inferResult": "SUCCESS" }]}`

여기서는 단순화: 1회 호출 = 1 이미지 → 1 페이지. 다중 페이지(PDF) 는 Phase 2.2.6
crawler/document 도입 시 batch 형태로 확장.

재시도/회로차단:
  - HTTP 5xx, ConnectError, ReadTimeout → 일시 실패 → exponential backoff 3회
  - 4xx (인증/요청 오류) → 영구 실패, 즉시 OcrError raise (회로 점수 +1)
  - circuit breaker: 5회 연속 실패 → 30s 차단
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import time
from typing import Any

import httpx

from app.integrations.ocr.circuit_breaker import CircuitBreaker
from app.integrations.ocr.types import OcrError, OcrPage, OcrResponse

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class ClovaOcrProvider:
    """`OcrProvider` 구현. httpx.AsyncClient 1개 재사용 — 호출자가 lifecycle 관리."""

    name = "clova"

    def __init__(
        self,
        *,
        api_url: str,
        secret: str,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        if not api_url or not secret:
            raise ValueError("CLOVA api_url and secret are required")
        self._api_url = api_url
        self._secret = secret
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None
        self._max_retries = max_retries
        self._breaker = breaker or CircuitBreaker(failure_threshold=5, cooldown_sec=30.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _build_request(
        self, image_bytes: bytes, content_type: str, request_id: str | None
    ) -> dict[str, Any]:
        # CLOVA 가 받는 image format = jpg/jpeg/png/pdf (확장자 식별)
        fmt = _content_type_to_format(content_type)
        return {
            "version": "V2",
            "requestId": request_id or secrets.token_hex(8),
            "timestamp": int(time.time() * 1000),
            "lang": "ko",
            "images": [
                {
                    "format": fmt,
                    "name": "receipt",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            ],
        }

    async def recognize(
        self,
        *,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
        request_id: str | None = None,
    ) -> OcrResponse:
        if not self._breaker.allow():
            raise OcrError("clova circuit breaker is OPEN")

        body = self._build_request(image_bytes, content_type, request_id)
        last_exc: Exception | None = None
        backoff = 0.5
        started = time.perf_counter()

        for _attempt in range(self._max_retries):
            try:
                resp = await self._client.post(
                    self._api_url,
                    json=body,
                    headers={
                        "X-OCR-SECRET": self._secret,
                        "Content-Type": "application/json",
                    },
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    self._breaker.record_success()
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    return _parse_response(resp.json(), duration_ms)
                if resp.status_code in _RETRYABLE_STATUS:
                    last_exc = OcrError(f"clova HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    # 영구 실패 — 즉시 종료.
                    self._breaker.record_failure()
                    raise OcrError(f"clova HTTP {resp.status_code}: {resp.text[:200]}")

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        self._breaker.record_failure()
        raise OcrError(f"clova all retries exhausted: {last_exc}")


def _content_type_to_format(content_type: str) -> str:
    ct = content_type.lower()
    if "png" in ct:
        return "png"
    if "pdf" in ct:
        return "pdf"
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    raise OcrError(f"clova: unsupported content_type {content_type}")


def _parse_response(payload: dict[str, Any], duration_ms: int) -> OcrResponse:
    """CLOVA V2 응답 → OcrResponse.

    confidence 는 이미지 단위 평균. fields 의 inferConfidence(0~1) 를 평균.
    """
    images = payload.get("images") or []
    if not images:
        raise OcrError("clova response: no images")
    pages: list[OcrPage] = []
    for idx, image in enumerate(images, start=1):
        if image.get("inferResult") not in ("SUCCESS", None):
            raise OcrError(f"clova inferResult={image.get('inferResult')}")
        fields = image.get("fields") or []
        if fields:
            confs = [float(f.get("inferConfidence", 0.0)) for f in fields if "inferConfidence" in f]
            avg_conf = sum(confs) / len(confs) if confs else 0.0
            text = " ".join(str(f.get("inferText", "")) for f in fields).strip()
        else:
            avg_conf = 0.0
            text = ""
        pages.append(
            OcrPage(
                page_no=idx,
                text=text,
                confidence=round(avg_conf, 4),
                layout={"fields": fields},
            )
        )
    return OcrResponse(
        provider="clova",
        engine_version=str(payload.get("version", "V2")),
        pages=tuple(pages),
        duration_ms=duration_ms,
    )


__all__ = ["ClovaOcrProvider"]
