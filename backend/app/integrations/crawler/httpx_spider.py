"""httpx.AsyncClient 기반 단순 spider (Phase 2.2.8).

기능:
  - User-Agent 강제 (Settings 의 `crawler_user_agent`).
  - robots.txt 존중 — `urllib.robotparser` 로 fetchable 여부 확인 + per-host TTL 캐시.
  - 재시도/회로차단 — OCR 패키지의 `CircuitBreaker` 재사용. 5xx/네트워크 → backoff,
    4xx → 영구 실패.

운영 시 주의:
  - playwright/selenium 같은 동적 페이지 크롤은 별도 spider 추가. 현재는 정적 HTML.
  - 한 번에 한 URL 만 — concurrency/queueing 은 dramatiq + 큐가 담당.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.integrations.crawler.types import (
    CrawlerConfig,
    CrawlerError,
    CrawlPage,
    RobotsBlocked,
)
from app.integrations.ocr.circuit_breaker import CircuitBreaker

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class _RobotsCache:
    """per-host robots.txt 결과 캐시. TTL 경과 시 재조회."""

    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        # host → (parser, fetched_at, ok)
        self._entries: dict[str, tuple[RobotFileParser, float, bool]] = {}

    async def is_allowed(self, client: httpx.AsyncClient, user_agent: str, url: str) -> bool:
        parsed = urlparse(url)
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        now = time.monotonic()

        cached = self._entries.get(host_key)
        if cached is not None and (now - cached[1]) < self._ttl:
            parser, _, ok = cached
            return ok and parser.can_fetch(user_agent, url)

        # robots.txt fetch — 실패 시 보수적으로 허용 (대다수 사이트가 robots 미제공).
        robots_url = f"{host_key}/robots.txt"
        parser = RobotFileParser()
        ok = True
        try:
            resp = await client.get(robots_url, follow_redirects=True)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500:
                # 404/403 → robots 미존재 == 모든 path 허용.
                parser.parse([])
            else:
                # 5xx — 일시적이라 가정. 캐시는 짧게.
                parser.parse([])
                ok = False
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout):
            parser.parse([])
            ok = False

        self._entries[host_key] = (parser, now, ok)
        return ok and parser.can_fetch(user_agent, url)


class HttpxSpider:
    """`CrawlerSpider` 구현. AsyncClient 1개를 lifecycle 동안 보유."""

    name = "httpx"

    def __init__(
        self,
        config: CrawlerConfig,
        *,
        client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=config.timeout_sec, write=10.0, pool=5.0),
            headers={"User-Agent": config.user_agent},
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._breaker = breaker or CircuitBreaker(failure_threshold=5, cooldown_sec=30.0)
        self._robots = _RobotsCache(ttl_sec=config.robots_cache_ttl_sec)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, url: str) -> CrawlPage:
        if not url:
            raise CrawlerError("empty url")
        if not self._breaker.allow():
            raise CrawlerError("crawler circuit breaker is OPEN")

        if self._config.respect_robots:
            allowed = await self._robots.is_allowed(self._client, self._config.user_agent, url)
            if not allowed:
                raise RobotsBlocked(f"robots.txt disallows fetching {url}")

        last_exc: Exception | None = None
        backoff = 0.5
        started = time.time()

        for _attempt in range(self._config.max_retries):
            try:
                resp = await self._client.get(url)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_exc = exc
            else:
                if 200 <= resp.status_code < 300:
                    self._breaker.record_success()
                    return CrawlPage(
                        url=str(resp.url),
                        html_bytes=resp.content,
                        http_status=resp.status_code,
                        headers={k: v for k, v in resp.headers.items()},
                        fetched_at_unix=started,
                    )
                if resp.status_code in _RETRYABLE_STATUS:
                    last_exc = CrawlerError(f"crawler HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    # 영구 실패 — 4xx (404/403/410 등). 즉시 raise.
                    self._breaker.record_failure()
                    raise CrawlerError(f"crawler HTTP {resp.status_code}: {resp.text[:200]}")

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        self._breaker.record_failure()
        raise CrawlerError(f"crawler all retries exhausted: {last_exc}")


__all__ = ["HttpxSpider"]
