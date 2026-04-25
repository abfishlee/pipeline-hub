"""웹 크롤러 통합 어댑터 (Phase 2.2.8).

도메인은 `CrawlerSpider` Protocol 만 본다 — httpx 기반 단순 spider 외에 향후
playwright 등 다른 구현이 추가될 수 있다.
"""

from __future__ import annotations

from app.integrations.crawler.httpx_spider import HttpxSpider
from app.integrations.crawler.types import (
    CrawlerConfig,
    CrawlerError,
    CrawlerSpider,
    CrawlPage,
    RobotsBlocked,
)

__all__ = [
    "CrawlPage",
    "CrawlerConfig",
    "CrawlerError",
    "CrawlerSpider",
    "HttpxSpider",
    "RobotsBlocked",
]
