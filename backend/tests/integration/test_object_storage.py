"""Object Storage 통합 테스트 — MinIO 실 엔드포인트 대상.

docker-compose 가 MinIO 를 띄워 놓은 상태에서 실행. 미접속 시 skip.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import httpx
import pytest

from app.config import Settings
from app.core import object_keys
from app.integrations import object_storage as os_module
from app.integrations.object_storage import S3CompatibleStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _require_object_storage_reachable(integration_settings: Settings) -> None:
    """MinIO head_bucket 성공 보장. 실패 시 모듈 전체 skip.

    sync 방식으로 구현 — session-scope 에서 event loop 상태 오염 회피.
    """
    storage = S3CompatibleStorage(integration_settings)
    try:
        storage._client.head_bucket(Bucket=integration_settings.os_bucket)
    except Exception as exc:
        pytest.skip(f"Object Storage unreachable ({exc}) — run `make dev-up` first")


@pytest.fixture
def storage(integration_settings: Settings) -> S3CompatibleStorage:
    """새 인스턴스 — lru_cache 오염 방지."""
    os_module.reset_object_storage_cache()
    return S3CompatibleStorage(integration_settings)


@pytest.fixture
def test_key_prefix() -> str:
    return f"it-test/{uuid.uuid4().hex}"


@pytest.fixture
def cleanup_keys(storage: S3CompatibleStorage) -> Iterator[list[str]]:
    """테스트 종료 시 키 delete (sync boto3 호출 — async loop 의존 제거)."""
    keys: list[str] = []
    yield keys
    for k in keys:
        with contextlib.suppress(Exception):
            storage._client.delete_object(Bucket=storage.bucket, Key=k)


# ---------------------------------------------------------------------------
# Basic I/O
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_and_presigned_get_roundtrip(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
    cleanup_keys: list[str],
) -> None:
    key = f"{test_key_prefix}/hello.txt"
    cleanup_keys.append(key)
    payload = b"hello-object-storage-2026-04-25"

    uri = await storage.put(key, payload, content_type="text/plain")
    assert uri.startswith(("s3://", "nos://"))
    assert uri.endswith(f"/{key}")

    # presigned_get 로 외부 다운로드 흐름 검증.
    url = await storage.presigned_get(key, expires_sec=60)
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
    assert r.status_code == 200
    assert r.content == payload


@pytest.mark.asyncio
async def test_exists_true_and_false(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
    cleanup_keys: list[str],
) -> None:
    key = f"{test_key_prefix}/exists-check.bin"
    cleanup_keys.append(key)

    assert await storage.exists(key) is False

    await storage.put(key, b"x")
    assert await storage.exists(key) is True


@pytest.mark.asyncio
async def test_delete_removes_object(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
) -> None:
    key = f"{test_key_prefix}/to-delete.bin"
    await storage.put(key, b"to be deleted")
    assert await storage.exists(key) is True

    await storage.delete(key)
    assert await storage.exists(key) is False


# ---------------------------------------------------------------------------
# Presigned PUT (외부 client 업로드 흐름)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_presigned_put_flow(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
    cleanup_keys: list[str],
) -> None:
    key = f"{test_key_prefix}/presigned-upload.json"
    cleanup_keys.append(key)
    payload = b'{"message": "from presigned PUT"}'

    upload_url = await storage.presigned_put(key, expires_sec=60, content_type="application/json")

    async with httpx.AsyncClient() as client:
        r = await client.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code in (200, 201), r.text

    # 서버 측에서 객체 확인.
    assert await storage.exists(key) is True

    # 내용 검증.
    get_url = await storage.presigned_get(key, expires_sec=60)
    async with httpx.AsyncClient() as client:
        r = await client.get(get_url)
    assert r.status_code == 200
    assert r.content == payload


# ---------------------------------------------------------------------------
# 대용량 + 체크섬
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_1mb_and_verify_sha256(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
    cleanup_keys: list[str],
) -> None:
    """1MB 파일 put → presigned_get 다운로드 → SHA-256 동등성 확인."""
    key = f"{test_key_prefix}/1mb.bin"
    cleanup_keys.append(key)
    payload = os.urandom(1024 * 1024)
    expected_sha = hashlib.sha256(payload).hexdigest()

    await storage.put(key, payload, content_type="application/octet-stream")

    url = await storage.presigned_get(key, expires_sec=60)
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
    assert r.status_code == 200
    actual_sha = hashlib.sha256(r.content).hexdigest()
    assert actual_sha == expected_sha
    assert len(r.content) == 1024 * 1024


@pytest.mark.asyncio
async def test_put_stream_multipart_10mb(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
    cleanup_keys: list[str],
) -> None:
    """10MB 스트림 → multipart upload (part 2개 이상) → SHA-256 동등성."""
    key = f"{test_key_prefix}/10mb-stream.bin"
    cleanup_keys.append(key)

    total_size = 10 * 1024 * 1024
    chunk_size = 1 * 1024 * 1024  # 1MB 청크 → multipart 에서 버퍼링
    # 재현 가능한 바이트 시퀀스 (deterministic)
    seed = b"IT_OS_STREAM_CHUNK_"
    payload = (seed * (total_size // len(seed) + 1))[:total_size]
    expected_sha = hashlib.sha256(payload).hexdigest()

    async def _chunks() -> AsyncIterator[bytes]:
        for i in range(0, total_size, chunk_size):
            yield payload[i : i + chunk_size]

    uri = await storage.put_stream(key, _chunks(), content_type="application/octet-stream")
    assert uri.endswith(f"/{key}")
    assert await storage.exists(key)

    url = await storage.presigned_get(key, expires_sec=60)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url)
    assert r.status_code == 200
    assert len(r.content) == total_size
    assert hashlib.sha256(r.content).hexdigest() == expected_sha


@pytest.mark.asyncio
async def test_put_stream_small_fallback_to_single_put(
    storage: S3CompatibleStorage,
    test_key_prefix: str,
    cleanup_keys: list[str],
) -> None:
    """5MB 미만 스트림 → multipart 대신 단일 put 으로 fallback."""
    key = f"{test_key_prefix}/small-stream.bin"
    cleanup_keys.append(key)
    payload = b"small " * 100  # 600 bytes

    async def _chunks() -> AsyncIterator[bytes]:
        for i in range(0, len(payload), 50):
            yield payload[i : i + 50]

    await storage.put_stream(key, _chunks(), content_type="text/plain")

    url = await storage.presigned_get(key)
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
    assert r.content == payload


# ---------------------------------------------------------------------------
# URI format + key helpers
# ---------------------------------------------------------------------------
def test_object_uri_format_minio(integration_settings: Settings) -> None:
    """APP_OS_SCHEME=minio → 's3://' 스킴."""
    storage = S3CompatibleStorage(integration_settings)
    uri = storage.object_uri("foo/bar.txt")
    # 통합 테스트 환경은 .env 에 os_scheme=minio 가정.
    assert uri.startswith(("s3://", "nos://"))
    assert uri.endswith("/foo/bar.txt")


def test_raw_key_structure() -> None:
    when = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    key = object_keys.raw_key("EMART_API", when, "json")
    # raw/EMART_API/2026/04/25/{uuid}.json
    parts = key.split("/")
    assert parts[0] == "raw"
    assert parts[1] == "EMART_API"
    assert parts[2] == "2026"
    assert parts[3] == "04"
    assert parts[4] == "25"
    assert parts[5].endswith(".json")
    assert len(parts[5].split(".")[0]) == 32  # uuid4 hex


def test_receipt_key_prefix() -> None:
    when = datetime(2026, 4, 25, tzinfo=UTC)
    key = object_keys.receipt_key("RECEIPT_APP", when, "jpg")
    assert key.startswith("receipt/RECEIPT_APP/2026/04/25/")
    assert key.endswith(".jpg")


def test_crawl_key_defaults_to_html() -> None:
    key = object_keys.crawl_html_key("COUPANG_CRAWL", datetime(2026, 4, 25, tzinfo=UTC))
    assert key.startswith("crawl/COUPANG_CRAWL/2026/04/25/")
    assert key.endswith(".html")


def test_invalid_extension_rejected() -> None:
    with pytest.raises(ValueError, match="invalid extension"):
        object_keys.raw_key("FOO", datetime(2026, 4, 25, tzinfo=UTC), "has space")


def test_unknown_category_rejected() -> None:
    with pytest.raises(ValueError, match="unknown category"):
        object_keys._base_key("nonexistent", "FOO", datetime(2026, 4, 25, tzinfo=UTC), "txt")


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ping_returns_true_against_live_minio(
    storage: S3CompatibleStorage,
) -> None:
    assert await storage.ping(timeout_sec=3.0) is True
