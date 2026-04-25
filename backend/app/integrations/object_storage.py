"""Object Storage 어댑터 — MinIO(로컬) / NCP Object Storage(운영) 공통.

ADR-0002 참조. boto3 sync 클라이언트를 `asyncio.to_thread` 로 감싸 async 노출.
본 모듈 외부(도메인/API)는 Protocol `ObjectStorage` 만 본다.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.core.errors import IntegrationError

# S3 multipart 최소 part 크기 (마지막 part 제외).
_S3_MIN_PART_SIZE = 5 * 1024 * 1024  # 5 MiB
# 단일 put 사용 임계치 — 이 이하는 그냥 put_object.
_SINGLE_PUT_THRESHOLD = _S3_MIN_PART_SIZE


@runtime_checkable
class ObjectStorage(Protocol):
    """도메인/API 가 의존하는 추상 인터페이스."""

    @property
    def bucket(self) -> str: ...
    @property
    def uri_scheme(self) -> str: ...

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str: ...

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        content_type: str = "application/octet-stream",
    ) -> str: ...

    async def presigned_put(
        self, key: str, expires_sec: int = 300, content_type: str | None = None
    ) -> str: ...

    async def presigned_get(self, key: str, expires_sec: int = 300) -> str: ...

    async def get_bytes(self, key: str) -> bytes: ...

    def object_uri(self, key: str) -> str: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> bool: ...

    async def ping(self, timeout_sec: float = 5.0) -> bool: ...


# ---------------------------------------------------------------------------
# S3 호환 구현 (MinIO + NCP Object Storage)
# ---------------------------------------------------------------------------
_NCP_ENDPOINT = "https://kr.object.ncloudstorage.com"


class S3CompatibleStorage:
    """MinIO + NCP Object Storage 공통 어댑터.

    URI 스킴:
      - APP_OS_SCHEME=minio → `s3://bucket/key`
      - APP_OS_SCHEME=ncp   → `nos://bucket/key`

    두 환경 모두 path-style addressing + SigV4.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bucket = settings.os_bucket

        # endpoint 결정 — 운영은 NCP, 그 외는 사용자 설정 (MinIO 등).
        endpoint_url = _NCP_ENDPOINT if settings.os_scheme == "ncp" else settings.os_endpoint

        config = Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "adaptive"},
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.os_access_key.get_secret_value(),
            aws_secret_access_key=settings.os_secret_key.get_secret_value(),
            region_name=settings.os_region,
            config=config,
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def uri_scheme(self) -> str:
        return "nos" if self._settings.os_scheme == "ncp" else "s3"

    def object_uri(self, key: str) -> str:
        return f"{self.uri_scheme}://{self._bucket}/{key}"

    # ----- put -----
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        def _put() -> None:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )

        try:
            await asyncio.to_thread(_put)
        except ClientError as exc:
            raise IntegrationError(f"object_storage put failed: {key}") from exc
        return self.object_uri(key)

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        content_type: str = "application/octet-stream",
    ) -> str:
        """Multipart 업로드. 5MB 이하면 단일 put 으로 fallback.

        실패 시 `abort_multipart_upload` 로 부분 업로드 정리.
        """
        # 우선 첫 MIN_PART 만큼 버퍼 — 작으면 그냥 put, 크면 multipart 전환.
        first_buf = bytearray()
        async for chunk in chunks:
            first_buf.extend(chunk)
            if len(first_buf) >= _SINGLE_PUT_THRESHOLD:
                return await self._put_stream_multipart(key, bytes(first_buf), chunks, content_type)
        # 스트림이 작으면 단일 put.
        return await self.put(key, bytes(first_buf), content_type)

    async def _put_stream_multipart(
        self,
        key: str,
        first_buffered: bytes,
        remaining: AsyncIterator[bytes],
        content_type: str,
    ) -> str:
        def _create() -> str:
            resp = self._client.create_multipart_upload(
                Bucket=self._bucket, Key=key, ContentType=content_type
            )
            return str(resp["UploadId"])

        upload_id = await asyncio.to_thread(_create)

        parts: list[dict[str, Any]] = []
        part_num = 1
        buf = bytearray(first_buffered)

        async def _flush_part(data: bytes) -> None:
            nonlocal part_num

            def _upload() -> str:
                resp = self._client.upload_part(
                    Bucket=self._bucket,
                    Key=key,
                    PartNumber=part_num,
                    UploadId=upload_id,
                    Body=data,
                )
                return str(resp["ETag"])

            etag = await asyncio.to_thread(_upload)
            parts.append({"PartNumber": part_num, "ETag": etag})
            part_num += 1

        try:
            async for chunk in remaining:
                buf.extend(chunk)
                while len(buf) >= _S3_MIN_PART_SIZE:
                    # 정확히 MIN_PART 만 잘라 part 로 전송.
                    await _flush_part(bytes(buf[:_S3_MIN_PART_SIZE]))
                    del buf[:_S3_MIN_PART_SIZE]
            if buf:
                # 마지막 part — 5MB 미만 허용.
                await _flush_part(bytes(buf))

            def _complete() -> None:
                self._client.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )

            await asyncio.to_thread(_complete)
        except Exception as exc:

            def _abort() -> None:
                self._client.abort_multipart_upload(
                    Bucket=self._bucket, Key=key, UploadId=upload_id
                )

            # abort 실패는 삼킴 (주 예외 보존).
            with contextlib.suppress(ClientError):
                await asyncio.to_thread(_abort)
            raise IntegrationError(f"object_storage multipart upload failed: {key}") from exc

        return self.object_uri(key)

    # ----- presigned -----
    async def presigned_put(
        self, key: str, expires_sec: int = 300, content_type: str | None = None
    ) -> str:
        def _gen() -> str:
            params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
            if content_type:
                params["ContentType"] = content_type
            return str(
                self._client.generate_presigned_url(
                    "put_object", Params=params, ExpiresIn=expires_sec
                )
            )

        return await asyncio.to_thread(_gen)

    async def presigned_get(self, key: str, expires_sec: int = 300) -> str:
        def _gen() -> str:
            return str(
                self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_sec,
                )
            )

        return await asyncio.to_thread(_gen)

    async def get_bytes(self, key: str) -> bytes:
        """단일 GET — OCR 워커에서 영수증 bytes 직접 다운로드용. 큰 객체는 stream API 권장."""

        def _get() -> bytes:
            try:
                resp = self._client.get_object(Bucket=self._bucket, Key=key)
                body: Any = resp["Body"]
                data = body.read()
                # botocore 의 StreamingBody.close 는 idempotent.
                with contextlib.suppress(Exception):
                    body.close()
                return bytes(data)
            except ClientError as exc:
                raise IntegrationError(f"object_storage.get_bytes failed: {exc}") from exc

        return await asyncio.to_thread(_get)

    # ----- state -----
    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise

        try:
            return await asyncio.to_thread(_head)
        except ClientError as exc:
            raise IntegrationError(f"object_storage head failed: {key}") from exc

    async def delete(self, key: str) -> bool:
        def _del() -> bool:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            return True

        try:
            return await asyncio.to_thread(_del)
        except ClientError as exc:
            raise IntegrationError(f"object_storage delete failed: {key}") from exc

    async def ping(self, timeout_sec: float = 5.0) -> bool:
        """head_bucket — S3 공통 가볍고 권한 낮은 연결 체크."""

        def _head() -> None:
            self._client.head_bucket(Bucket=self._bucket)

        try:
            await asyncio.wait_for(asyncio.to_thread(_head), timeout=timeout_sec)
            return True
        except (TimeoutError, Exception):
            return False


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """프로세스 1개 어댑터 싱글톤. settings 변경 시 재기동 필요."""
    return S3CompatibleStorage(get_settings())


def reset_object_storage_cache() -> None:
    """테스트/설정 교체용. 운영 코드에서 호출 금지."""
    get_object_storage.cache_clear()


__all__ = [
    "ObjectStorage",
    "S3CompatibleStorage",
    "get_object_storage",
    "reset_object_storage_cache",
]
