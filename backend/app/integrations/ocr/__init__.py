"""OCR 통합 어댑터 (Phase 2.2.4).

도메인은 `OcrProvider` Protocol 만 본다 — CLOVA / Upstage 구현은 이 패키지 내부에
숨김. 폴백 전략은 도메인이 구성: `[ClovaOcrProvider(...), UpstageOcrProvider(...)]`
순으로 시도.
"""

from __future__ import annotations

from app.integrations.ocr.types import (
    BoundingBox,
    OcrError,
    OcrPage,
    OcrProvider,
    OcrResponse,
)

__all__ = [
    "BoundingBox",
    "OcrError",
    "OcrPage",
    "OcrProvider",
    "OcrResponse",
]
