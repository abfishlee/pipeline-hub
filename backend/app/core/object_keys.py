"""Object Storage 키 생성 헬퍼.

경로 규칙:
  {category}/{source_code}/{YYYY}/{MM}/{DD}/{uuid}.{ext}

카테고리별 prefix 로 수명주기 정책(archive/삭제) 차등 적용이 용이하다.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Final

# S3 key 안전 문자 (source_code 외 부분 검증) — 영숫자/대시/언더스코어/슬래시/점.
_EXT_SAFE_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")

_ALLOWED_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"raw", "receipt", "ocr", "crawl", "archive", "tmp"}
)


def _normalize_ext(ext: str) -> str:
    """확장자 소문자 + 앞 점 제거. 영숫자만 허용."""
    cleaned = ext.lower().lstrip(".")
    if not _EXT_SAFE_RE.match(cleaned):
        raise ValueError(f"invalid extension: {ext!r}")
    return cleaned


def _base_key(category: str, source_code: str, when: date | datetime, ext: str) -> str:
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError(f"unknown category {category!r}; allowed: {sorted(_ALLOWED_CATEGORIES)}")
    if not source_code:
        raise ValueError("source_code required")
    ext_norm = _normalize_ext(ext)
    # datetime / date 둘 다 받아 .year/.month/.day 로 안전 접근.
    y, m, d = when.year, when.month, when.day
    uid = uuid.uuid4().hex
    return f"{category}/{source_code}/{y:04d}/{m:02d}/{d:02d}/{uid}.{ext_norm}"


def raw_key(source_code: str, when: date | datetime, ext: str) -> str:
    """일반 원천 파일 (API 응답 JSON, 대형 CSV 등)."""
    return _base_key("raw", source_code, when, ext)


def receipt_key(source_code: str, when: date | datetime, ext: str = "jpg") -> str:
    """소비자 영수증 이미지."""
    return _base_key("receipt", source_code, when, ext)


def ocr_image_key(source_code: str, when: date | datetime, ext: str) -> str:
    """OCR 대상 이미지 (마트 전단 등)."""
    return _base_key("ocr", source_code, when, ext)


def crawl_html_key(source_code: str, when: date | datetime) -> str:
    """크롤링 원본 HTML 스냅샷."""
    return _base_key("crawl", source_code, when, "html")


def archive_key(source_code: str, when: date | datetime, ext: str) -> str:
    """13개월 경과 raw 를 archive prefix 로 이동할 때 쓰는 키."""
    return _base_key("archive", source_code, when, ext)


__all__ = [
    "archive_key",
    "crawl_html_key",
    "ocr_image_key",
    "raw_key",
    "receipt_key",
]
