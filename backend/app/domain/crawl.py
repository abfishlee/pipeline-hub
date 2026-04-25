"""크롤러 도메인 (Phase 2.2.8).

흐름:
  1. `ctl.data_source` 에서 source_code 로드 (`source_type=CRAWLER`).
  2. spider.fetch(url) 호출 (async — sync worker 에서 asyncio.run 으로 감쌈).
  3. content_hash 계산 → 같은 (source_id, content_hash) 의 raw_web_page 가 이미
     있으면 dedup outcome 반환.
  4. Object Storage 업로드 (`crawl/<source_code>/<yyyy>/<mm>/<dd>/<hash>.html`).
  5. `raw.raw_web_page` INSERT.
  6. `run.event_outbox`(`crawler.page.fetched`, kind="crawl") 발행.

호출자가 commit 책임 (consume_idempotent 가 트랜잭션 닫음).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import metrics
from app.integrations.crawler import (
    CrawlerError,
    CrawlerSpider,
    CrawlPage,
    RobotsBlocked,
)
from app.integrations.object_storage import ObjectStorage
from app.models.ctl import DataSource
from app.models.raw import RawWebPage
from app.models.run import EventOutbox

CrawlOutcomeStatus = Literal["fetched", "dedup", "blocked_by_robots", "error"]


@dataclass(slots=True, frozen=True)
class CrawlOutcome:
    source_code: str
    url: str
    status: CrawlOutcomeStatus
    page_id: int | None = None
    content_hash: str | None = None
    html_object_uri: str | None = None
    http_status: int | None = None


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_key(source_code: str, content_hash: str, fetched_at: datetime) -> str:
    y = fetched_at.strftime("%Y")
    m = fetched_at.strftime("%m")
    d = fetched_at.strftime("%d")
    return f"crawl/{source_code}/{y}/{m}/{d}/{content_hash}.html"


def fetch_and_store(
    session: Session,
    storage: ObjectStorage,
    spider: CrawlerSpider,
    *,
    source_code: str,
    url: str,
) -> CrawlOutcome:
    ds = session.execute(
        select(DataSource).where(DataSource.source_code == source_code)
    ).scalar_one_or_none()
    if ds is None:
        raise CrawlerError(f"data_source not found: {source_code}")
    if ds.source_type != "CRAWLER":
        raise CrawlerError(f"source {source_code} is not type=CRAWLER (got {ds.source_type})")
    if not ds.is_active:
        raise CrawlerError(f"source {source_code} is inactive")

    started = time.perf_counter()
    try:
        page: CrawlPage = asyncio.run(spider.fetch(url))
    except RobotsBlocked:
        metrics.crawler_pages_fetched_total.labels(
            source_code=source_code, outcome="blocked_by_robots"
        ).inc()
        return CrawlOutcome(source_code=source_code, url=url, status="blocked_by_robots")
    except CrawlerError:
        metrics.crawler_pages_fetched_total.labels(source_code=source_code, outcome="error").inc()
        raise
    finally:
        metrics.crawler_fetch_duration_seconds.labels(source_code=source_code).observe(
            time.perf_counter() - started
        )

    fetched_at = (
        datetime.fromtimestamp(page.fetched_at_unix, UTC)
        if page.fetched_at_unix
        else datetime.now(UTC)
    )
    chash = _content_hash(page.html_bytes)

    # dedup — 같은 source 의 동일 content_hash 가 이미 있으면 skip.
    existing = session.execute(
        select(RawWebPage)
        .where(RawWebPage.source_id == ds.source_id)
        .where(RawWebPage.content_hash == chash)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        metrics.crawler_pages_fetched_total.labels(source_code=source_code, outcome="dedup").inc()
        return CrawlOutcome(
            source_code=source_code,
            url=url,
            status="dedup",
            page_id=existing.page_id,
            content_hash=chash,
            html_object_uri=existing.html_object_uri,
            http_status=page.http_status,
        )

    # Object Storage 업로드 (sync 컨텍스트라 asyncio.run).
    key = _object_key(source_code, chash, fetched_at)
    object_uri = asyncio.run(storage.put(key, page.html_bytes, content_type="text/html"))

    row = RawWebPage(
        source_id=ds.source_id,
        url=url,
        http_status=page.http_status,
        html_object_uri=object_uri,
        response_headers=dict(page.headers),
        fetched_at=fetched_at,
        content_hash=chash,
        parser_version=spider.name,
    )
    session.add(row)
    session.flush()

    session.add(
        EventOutbox(
            aggregate_type="crawler_page",
            aggregate_id=str(row.page_id),
            event_type="crawler.page.fetched",
            payload_json={
                "page_id": row.page_id,
                "source_id": ds.source_id,
                "source_code": source_code,
                "kind": "crawl",
                "url": url,
                "http_status": page.http_status,
                "content_hash": chash,
                "html_object_uri": object_uri,
                "bytes_size": len(page.html_bytes),
            },
        )
    )

    metrics.crawler_pages_fetched_total.labels(source_code=source_code, outcome="fetched").inc()

    return CrawlOutcome(
        source_code=source_code,
        url=url,
        status="fetched",
        page_id=row.page_id,
        content_hash=chash,
        html_object_uri=object_uri,
        http_status=page.http_status,
    )


__all__ = ["CrawlOutcome", "CrawlOutcomeStatus", "fetch_and_store"]
