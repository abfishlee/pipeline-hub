"""OCR Provider 추상 인터페이스 + 공통 데이터 타입.

도메인은 이 파일의 타입만 의존. 실 SDK(httpx 호출, 인증, 응답 파싱)는 각 provider
모듈(`clova/`, `upstage/`)에 격리.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class OcrError(Exception):
    """OCR 호출 실패. 일시(transient) 와 영구(permanent) 구분은 조정자(domain)가 정함."""


@dataclass(slots=True, frozen=True)
class BoundingBox:
    """OCR 텍스트 박스의 정규화 좌표 (0~1). provider 별 출력 형식 변환은 client 가 담당."""

    x: float
    y: float
    w: float
    h: float


@dataclass(slots=True, frozen=True)
class OcrPage:
    """페이지 단위 결과 — `raw.ocr_result` 1행에 1:1."""

    page_no: int
    text: str
    confidence: float  # 0.0 ~ 1.0 (DB 컬럼은 NUMERIC(5,2) 라 0~100 으로 변환 후 저장)
    layout: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OcrResponse:
    """provider 1회 호출 결과."""

    provider: str  # 'clova' | 'upstage'
    engine_version: str | None
    pages: Sequence[OcrPage]
    duration_ms: int


@runtime_checkable
class OcrProvider(Protocol):
    """도메인이 의존하는 추상 — 단일 메서드.

    구현체는 인증/재시도/회로차단을 내부에서 처리. 호출자는 OcrError 만 잡으면 됨.
    """

    name: str

    async def recognize(
        self,
        *,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
        request_id: str | None = None,
    ) -> OcrResponse: ...
