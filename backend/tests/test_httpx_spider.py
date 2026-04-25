"""Unit — HttpxSpider 의 fetch / robots / 재시도 / breaker 동작.

httpx.MockTransport 로 실 네트워크 차단. spider 자체 행동만 검증.
"""

from __future__ import annotations

import httpx
import pytest

from app.integrations.crawler import (
    CrawlerConfig,
    CrawlerError,
    HttpxSpider,
    RobotsBlocked,
)


def _spider(handler: httpx.MockTransport, *, respect_robots: bool = False) -> HttpxSpider:
    client = httpx.AsyncClient(transport=handler, follow_redirects=True)
    return HttpxSpider(
        CrawlerConfig(
            user_agent="it-spider/1.0",
            timeout_sec=5.0,
            respect_robots=respect_robots,
            max_retries=3,
        ),
        client=client,
    )


@pytest.mark.asyncio
async def test_fetch_returns_html_bytes_and_status_on_200() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html><body>hello</body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    spider = _spider(httpx.MockTransport(respond))
    try:
        page = await spider.fetch("https://example.test/page-1")
    finally:
        await spider.aclose()

    assert page.http_status == 200
    assert b"<html>" in page.html_bytes
    assert page.headers.get("content-type", "").startswith("text/html")
    assert page.url.endswith("/page-1")


@pytest.mark.asyncio
async def test_fetch_4xx_is_permanent_no_retry() -> None:
    calls = {"n": 0}

    def respond(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="not found")

    spider = _spider(httpx.MockTransport(respond))
    try:
        with pytest.raises(CrawlerError, match="HTTP 404"):
            await spider.fetch("https://example.test/missing")
    finally:
        await spider.aclose()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_fetch_5xx_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def respond(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, content=b"<p>ok</p>")

    spider = _spider(httpx.MockTransport(respond))
    try:
        page = await spider.fetch("https://example.test/flaky")
    finally:
        await spider.aclose()
    assert calls["n"] == 2
    assert page.http_status == 200


@pytest.mark.asyncio
async def test_robots_disallow_raises_robots_blocked() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret")
        return httpx.Response(200, content=b"<html/>")

    spider = _spider(httpx.MockTransport(respond), respect_robots=True)
    try:
        with pytest.raises(RobotsBlocked):
            await spider.fetch("https://example.test/secret/page")
        # 다른 경로는 허용되어야 함.
        page = await spider.fetch("https://example.test/public/page")
        assert page.http_status == 200
    finally:
        await spider.aclose()


@pytest.mark.asyncio
async def test_robots_missing_treats_as_allowed() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="not found")
        return httpx.Response(200, content=b"<html/>")

    spider = _spider(httpx.MockTransport(respond), respect_robots=True)
    try:
        page = await spider.fetch("https://example.test/anything")
    finally:
        await spider.aclose()
    assert page.http_status == 200
