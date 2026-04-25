"""Crawler 추상 타입 — 도메인이 의존하는 인터페이스.

다른 spider 구현(예: playwright headless browser) 도입 시 같은 Protocol 만 만족하면
도메인 변경 없이 끼워 넣을 수 있다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class CrawlerError(Exception):
    """크롤러 호출 실패. caller 가 일시/영구 분리."""


class RobotsBlocked(CrawlerError):
    """robots.txt 가 해당 URL 의 fetch 를 금지. 영구 실패로 분류 — 재시도 X."""


@dataclass(slots=True, frozen=True)
class CrawlerConfig:
    user_agent: str
    timeout_sec: float = 15.0
    respect_robots: bool = True
    max_retries: int = 3
    # robots.txt fetch 캐시 TTL (초). 호스트별 1회 조회 후 캐시.
    robots_cache_ttl_sec: float = 3600.0


@dataclass(slots=True, frozen=True)
class CrawlPage:
    """spider.fetch 의 결과 — 1 URL = 1 페이지."""

    url: str
    html_bytes: bytes
    http_status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    fetched_at_unix: float = 0.0


@runtime_checkable
class CrawlerSpider(Protocol):
    """도메인이 보는 단일 인터페이스."""

    name: str

    async def fetch(self, url: str) -> CrawlPage: ...

    async def aclose(self) -> None: ...
