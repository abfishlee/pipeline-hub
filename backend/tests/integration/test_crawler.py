"""크롤러 도메인 통합 테스트 — 실 PG, stub spider/storage.

실 MinIO/네트워크 의존 회피 — Object Storage 는 InMemory stub, spider 는
미리 정의된 응답 반환. 도메인 자체의 분기(fetched/dedup/blocked) 만 검증.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.crawl import fetch_and_store
from app.integrations.crawler import (
    CrawlerError,
    CrawlPage,
    RobotsBlocked,
)
from app.models.ctl import DataSource
from app.models.raw import RawWebPage
from app.models.run import EventOutbox


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------
class _StubStorage:
    bucket = "stub-bucket"
    uri_scheme = "s3"

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        self.put_calls.append((key, data, content_type))
        return f"s3://{self.bucket}/{key}"

    def object_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    async def put_stream(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def presigned_put(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def presigned_get(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def get_bytes(self, *_a: object, **_kw: object) -> bytes:  # pragma: no cover
        raise NotImplementedError

    async def exists(self, *_a: object, **_kw: object) -> bool:  # pragma: no cover
        return True

    async def delete(self, *_a: object, **_kw: object) -> bool:  # pragma: no cover
        return True

    async def ping(self, *_a: object, **_kw: object) -> bool:  # pragma: no cover
        return True


class _StubSpider:
    def __init__(
        self,
        *,
        html: bytes = b"<html>stub</html>",
        http_status: int = 200,
        raise_robots: bool = False,
        raise_error: bool = False,
    ) -> None:
        self.name = "stub-spider"
        self._html = html
        self._http_status = http_status
        self._raise_robots = raise_robots
        self._raise_error = raise_error
        self.calls = 0

    async def fetch(self, url: str) -> CrawlPage:
        self.calls += 1
        if self._raise_robots:
            raise RobotsBlocked(f"robots disallow: {url}")
        if self._raise_error:
            raise CrawlerError("stub failure")
        return CrawlPage(
            url=url,
            html_bytes=self._html,
            http_status=self._http_status,
            headers={"Content-Type": "text/html"},
            fetched_at_unix=datetime.now(UTC).timestamp(),
        )

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def crawler_source() -> Iterator[DataSource]:
    sm = get_sync_sessionmaker()
    code = f"IT-CR-{secrets.token_hex(4).upper()}"
    with sm() as session:
        ds = DataSource(
            source_code=code,
            source_name="crawler IT",
            source_type="CRAWLER",
            is_active=True,
            config_json={
                "spider_kind": "httpx",
                "seed_urls": ["https://example.test/page-1"],
                "respect_robots": True,
                "fetch_interval_sec": 600,
            },
        )
        session.add(ds)
        session.commit()
        session.refresh(ds)
        source_id = ds.source_id
    yield ds
    with sm() as session:
        session.execute(
            delete(EventOutbox).where(EventOutbox.payload_json["source_code"].astext == code)
        )
        session.execute(delete(RawWebPage).where(RawWebPage.source_id == source_id))
        session.execute(delete(DataSource).where(DataSource.source_id == source_id))
        session.commit()
    dispose_sync_engine()


# ---------------------------------------------------------------------------
# 1. fetched 경로
# ---------------------------------------------------------------------------
def test_fetch_uploads_to_storage_and_inserts_raw_web_page(
    crawler_source: DataSource,
) -> None:
    sm = get_sync_sessionmaker()
    storage = _StubStorage()
    spider = _StubSpider(html=b"<html>hello</html>")

    with sm() as session:
        outcome = fetch_and_store(
            session,
            storage,  # type: ignore[arg-type]
            spider,  # type: ignore[arg-type]
            source_code=crawler_source.source_code,
            url="https://example.test/page-1",
        )
        session.commit()

    assert outcome.status == "fetched"
    assert outcome.page_id is not None
    assert outcome.html_object_uri is not None
    assert outcome.html_object_uri.startswith("s3://stub-bucket/crawl/")

    # storage put 호출 1회.
    assert len(storage.put_calls) == 1
    key, data, ctype = storage.put_calls[0]
    assert key.endswith(".html")
    assert data == b"<html>hello</html>"
    assert ctype == "text/html"

    with sm() as session:
        rows: list[Any] = list(
            session.execute(
                select(RawWebPage).where(RawWebPage.source_id == crawler_source.source_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].http_status == 200
        assert rows[0].content_hash == outcome.content_hash

        events = (
            session.execute(
                select(EventOutbox).where(EventOutbox.event_type == "crawler.page.fetched")
            )
            .scalars()
            .all()
        )
        assert any(e.payload_json.get("page_id") == outcome.page_id for e in events)


# ---------------------------------------------------------------------------
# 2. dedup 경로 — 같은 content_hash 재요청
# ---------------------------------------------------------------------------
def test_second_fetch_with_same_content_hits_dedup(
    crawler_source: DataSource,
) -> None:
    sm = get_sync_sessionmaker()
    storage = _StubStorage()
    spider = _StubSpider(html=b"<html>same</html>")

    with sm() as session:
        first = fetch_and_store(
            session,
            storage,  # type: ignore[arg-type]
            spider,  # type: ignore[arg-type]
            source_code=crawler_source.source_code,
            url="https://example.test/dup",
        )
        session.commit()
    assert first.status == "fetched"

    with sm() as session:
        second = fetch_and_store(
            session,
            storage,  # type: ignore[arg-type]
            spider,  # type: ignore[arg-type]
            source_code=crawler_source.source_code,
            url="https://example.test/dup",
        )
        session.commit()

    assert second.status == "dedup"
    assert second.page_id == first.page_id
    # 두 번째 호출에도 spider 는 호출됐지만 storage 는 1번만(dedup 으로 skip).
    assert spider.calls == 2
    assert len(storage.put_calls) == 1

    with sm() as session:
        rows = (
            session.execute(
                select(RawWebPage).where(RawWebPage.source_id == crawler_source.source_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 3. robots 차단
# ---------------------------------------------------------------------------
def test_robots_blocked_returns_outcome_without_raise(
    crawler_source: DataSource,
) -> None:
    sm = get_sync_sessionmaker()
    storage = _StubStorage()
    spider = _StubSpider(raise_robots=True)

    with sm() as session:
        outcome = fetch_and_store(
            session,
            storage,  # type: ignore[arg-type]
            spider,  # type: ignore[arg-type]
            source_code=crawler_source.source_code,
            url="https://example.test/secret",
        )
        session.commit()

    assert outcome.status == "blocked_by_robots"
    assert outcome.page_id is None
    assert storage.put_calls == []

    with sm() as session:
        rows = (
            session.execute(
                select(RawWebPage).where(RawWebPage.source_id == crawler_source.source_id)
            )
            .scalars()
            .all()
        )
        assert rows == []
