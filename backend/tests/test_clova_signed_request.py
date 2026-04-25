"""Unit — CLOVA OCR Document API 의 헤더/본문 모양 검증.

httpx.MockTransport 로 실제 네트워크 호출 없이 client 가 만든 요청을 가로채 검증.
서명 위변조나 헤더 누락은 운영 사고로 직결되니 비싼 통합 테스트가 아니어도 단단히 묶음.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.integrations.clova.client import ClovaOcrProvider
from app.integrations.ocr.types import OcrError


def _make_provider(handler: httpx.MockTransport) -> ClovaOcrProvider:
    client = httpx.AsyncClient(transport=handler)
    return ClovaOcrProvider(
        api_url="https://clova.example/general/ocr",
        secret="it-secret-0425",
        client=client,
        max_retries=1,
    )


@pytest.mark.asyncio
async def test_clova_signs_request_and_parses_success() -> None:
    captured: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "version": "V2",
                "requestId": "req-stub",
                "timestamp": 0,
                "images": [
                    {
                        "uid": "img-1",
                        "name": "receipt",
                        "inferResult": "SUCCESS",
                        "fields": [
                            {"inferText": "사과", "inferConfidence": 0.95},
                            {"inferText": "1,200원", "inferConfidence": 0.88},
                        ],
                    }
                ],
            },
        )

    provider = _make_provider(httpx.MockTransport(respond))
    try:
        resp = await provider.recognize(
            image_bytes=b"\x89PNG-fake", content_type="image/png", request_id="req-stub"
        )
    finally:
        await provider.aclose()

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers.get("x-ocr-secret") == "it-secret-0425"
    assert "application/json" in (headers.get("content-type") or "")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://clova.example/general/ocr"

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["version"] == "V2"
    assert body["lang"] == "ko"
    assert body["requestId"] == "req-stub"
    assert body["images"][0]["format"] == "png"
    assert body["images"][0]["data"] == base64.b64encode(b"\x89PNG-fake").decode("ascii")

    assert resp.provider == "clova"
    assert len(resp.pages) == 1
    page = resp.pages[0]
    assert page.page_no == 1
    assert "사과" in page.text and "1,200원" in page.text
    # 평균 confidence (0.95 + 0.88) / 2 = 0.915
    assert abs(page.confidence - 0.915) < 1e-3


@pytest.mark.asyncio
async def test_clova_4xx_is_permanent_failure_no_retry() -> None:
    calls = {"n": 0}

    def respond(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "invalid secret"}})

    provider = _make_provider(httpx.MockTransport(respond))
    try:
        with pytest.raises(OcrError, match="HTTP 401"):
            await provider.recognize(image_bytes=b"x", content_type="image/jpeg")
    finally:
        await provider.aclose()

    # 재시도 없이 1회만.
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_clova_5xx_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def respond(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "transient"})
        return httpx.Response(
            200,
            json={
                "version": "V2",
                "requestId": "x",
                "images": [
                    {
                        "inferResult": "SUCCESS",
                        "fields": [{"inferText": "ok", "inferConfidence": 0.9}],
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = ClovaOcrProvider(
        api_url="https://clova.example/general/ocr",
        secret="it-secret",
        client=client,
        max_retries=3,
    )
    try:
        resp = await provider.recognize(image_bytes=b"x", content_type="image/jpeg")
    finally:
        await provider.aclose()

    assert calls["n"] == 2
    assert resp.pages[0].confidence == 0.9


@pytest.mark.asyncio
async def test_clova_circuit_breaker_opens_after_repeated_failures() -> None:
    """5회 연속 401 → breaker OPEN → 6번째 호출은 즉시 OcrError (네트워크 호출 없음)."""

    calls = {"n": 0}

    def respond(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "x"})

    provider = _make_provider(httpx.MockTransport(respond))
    try:
        for _ in range(5):
            with pytest.raises(OcrError):
                await provider.recognize(image_bytes=b"x", content_type="image/jpeg")
        # 6번째 — breaker 가 열려 있으므로 요청 자체가 안 나가야 함.
        prev_calls = calls["n"]
        with pytest.raises(OcrError, match="circuit breaker is OPEN"):
            await provider.recognize(image_bytes=b"x", content_type="image/jpeg")
        assert calls["n"] == prev_calls
    finally:
        await provider.aclose()
