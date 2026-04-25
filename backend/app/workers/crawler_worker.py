"""크롤러 워커 actor (Phase 2.2.8).

`process_crawl_event(source_code, url)` — Airflow `system_ingest_<source>` DAG (Phase
2.2.3 후속) 가 매 fetch_interval_sec 마다 활성 CRAWLER source 와 seed_urls 조합으로
enqueue 한다.

Actor 는 얇음 — domain 호출만. dedup 은 content_hash 기반(도메인) 이라 별도
consume_idempotent 불필요. 같은 url 이 동시 fetch 되어도 한 쪽이 dedup outcome 으로
귀결.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from app.config import get_settings
from app.db.sync_session import get_sync_sessionmaker
from app.domain.crawl import fetch_and_store
from app.integrations.crawler import CrawlerConfig, HttpxSpider
from app.integrations.object_storage import get_object_storage
from app.workers import pipeline_actor


@pipeline_actor(queue_name="crawler", max_retries=3, time_limit=300_000)
def process_crawl_event(source_code: str, url: str) -> dict[str, Any]:
    """1 URL fetch → raw_web_page 적재. 결과 통계 dict."""
    sm = get_sync_sessionmaker()
    settings = get_settings()
    spider = HttpxSpider(
        CrawlerConfig(
            user_agent=settings.crawler_user_agent,
            timeout_sec=settings.crawler_timeout_sec,
            respect_robots=settings.crawler_respect_robots,
        )
    )
    try:
        with sm() as session:
            outcome = fetch_and_store(
                session,
                get_object_storage(),
                spider,
                source_code=source_code,
                url=url,
            )
            session.commit()
        return {
            "source_code": outcome.source_code,
            "url": outcome.url,
            "status": outcome.status,
            "page_id": outcome.page_id,
            "content_hash": outcome.content_hash,
        }
    finally:
        with suppress(Exception):
            import asyncio

            asyncio.run(spider.aclose())


__all__ = ["process_crawl_event"]
