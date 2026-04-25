"""아주 작은 in-memory circuit breaker — OCR provider 가용성 보호.

영구 장애 provider 에 매번 timeout 대기를 쌓지 않게 한다. 다중 프로세스 환경에서는
프로세스마다 독립이라 완벽하지 않지만, Phase 2 단일 worker-ocr 에선 충분. Phase 4
스케일아웃 시 redis 기반으로 교체 검토.
"""

from __future__ import annotations

import time
from threading import Lock


class CircuitBreaker:
    """consecutive failure threshold 기반 — half-open 으로 완화 후 자동 복구.

    상태:
      - CLOSED: 정상. 호출 허용. 실패 시 카운터++.
      - OPEN: 차단. cooldown_sec 동안 호출 불가 → OcrError.
      - HALF_OPEN: cooldown 경과. 다음 호출 1회 시도. 성공 시 CLOSED, 실패 시 OPEN 재진입.
    """

    def __init__(self, *, failure_threshold: int = 5, cooldown_sec: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            # cooldown 경과 → half-open 진입, 1회 시도 허용.
            return (time.monotonic() - self._opened_at) >= self._cooldown_sec

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold and self._opened_at is None:
                self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None and not self.allow()


__all__ = ["CircuitBreaker"]
