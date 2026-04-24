"""Content hashing & idempotency key helpers.

`raw.raw_object.content_hash` 전역 중복 방지에 사용되는 SHA-256.
스트리밍 해시 지원 (대용량 파일 대비).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

_HASH_ALGO = "sha256"
CHUNK_SIZE = 64 * 1024  # 64KB


def sha256_bytes(data: bytes) -> str:
    """단건 bytes 해시 (hex)."""
    return hashlib.new(_HASH_ALGO, data).hexdigest()


def sha256_str(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_stream(chunks: Iterable[bytes]) -> str:
    """generator 로 오는 bytes 청크를 스트리밍 해시."""
    h = hashlib.new(_HASH_ALGO)
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()


def content_hash_of_json(payload: Any) -> str:
    """JSON 직렬화 후 해시 (키 정렬 + 공백 제거로 동일성 보장).

    UNIX 서로 다른 파서 이슈를 피하려 ensure_ascii=False + separators=('',':').
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256_str(canonical)


_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_.:\-]{8,128}$")


def normalize_idempotency_key(raw_key: str | None) -> str | None:
    """Idempotency-Key 헤더 정규화.

    공백 제거 + 패턴 검증. 형식에 맞지 않으면 None 반환(호출부에서 에러 판단).
    """
    if raw_key is None:
        return None
    cleaned = raw_key.strip()
    if not _IDEMPOTENCY_PATTERN.match(cleaned):
        return None
    return cleaned


__all__ = [
    "CHUNK_SIZE",
    "content_hash_of_json",
    "normalize_idempotency_key",
    "sha256_bytes",
    "sha256_str",
    "sha256_stream",
]
