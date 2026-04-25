"""HyperCLOVA Studio 임베딩 API 클라이언트 (Phase 2.2.5).

API 형태(NCP CLOVA Studio Embedding-Med):
  - POST {APP_HYPERCLOVA_API_URL}{APP_HYPERCLOVA_EMBEDDING_APP}
  - 헤더: `Authorization: Bearer <APP_HYPERCLOVA_API_KEY>`,
          `Content-Type: application/json`,
          `X-NCP-CLOVASTUDIO-REQUEST-ID: <uuid>` (선택, 로그 추적)
  - 본문: `{"text": "..."}`
  - 응답: `{"status": {"code": "20000"}, "result": {"embedding": [..]}}`

도메인은 `EmbeddingClient` Protocol 만 본다 — 테스트 stub 가 같은 인터페이스를 구현.

재시도/회로차단:
  - 5xx, ConnectError, ReadTimeout → 일시 실패 → exponential backoff 3회
  - 4xx → 영구 실패 (즉시 raise)
  - circuit breaker: 5회 연속 실패 → 30s 차단
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Protocol, runtime_checkable

import httpx

from app.integrations.ocr.circuit_breaker import CircuitBreaker

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class EmbeddingError(Exception):
    """임베딩 호출 실패. 일시/영구 구분은 caller 가 처리."""


@runtime_checkable
class EmbeddingClient(Protocol):
    """도메인이 의존하는 추상 인터페이스 — 단일 메서드."""

    name: str
    dimension: int

    async def embed(self, text: str) -> list[float]: ...


class HyperClovaEmbeddingClient:
    name = "hyperclova"

    def __init__(
        self,
        *,
        api_url: str,
        embedding_app: str,
        api_key: str,
        dimension: int = 1536,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        if not api_url or not api_key:
            raise ValueError("HyperCLOVA api_url and api_key are required")
        self.dimension = dimension
        self._endpoint = api_url.rstrip("/") + "/" + embedding_app.lstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        self._owns_client = client is None
        self._max_retries = max_retries
        self._breaker = breaker or CircuitBreaker(failure_threshold=5, cooldown_sec=30.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        if not text:
            raise EmbeddingError("empty text")
        if not self._breaker.allow():
            raise EmbeddingError("hyperclova circuit breaker is OPEN")

        last_exc: Exception | None = None
        backoff = 0.5
        for _attempt in range(self._max_retries):
            try:
                resp = await self._client.post(
                    self._endpoint,
                    json={"text": text},
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "X-NCP-CLOVASTUDIO-REQUEST-ID": secrets.token_hex(8),
                    },
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    self._breaker.record_success()
                    return _parse_embedding(resp.json(), expected_dim=self.dimension)
                if resp.status_code in _RETRYABLE_STATUS:
                    last_exc = EmbeddingError(
                        f"hyperclova HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                else:
                    self._breaker.record_failure()
                    raise EmbeddingError(f"hyperclova HTTP {resp.status_code}: {resp.text[:200]}")

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        self._breaker.record_failure()
        raise EmbeddingError(f"hyperclova all retries exhausted: {last_exc}")


def _parse_embedding(payload: dict[str, Any], *, expected_dim: int) -> list[float]:
    status = payload.get("status") or {}
    if status.get("code") not in (None, "20000"):
        raise EmbeddingError(f"hyperclova status={status}")
    result = payload.get("result") or {}
    vec = result.get("embedding")
    if not isinstance(vec, list) or not vec:
        raise EmbeddingError("hyperclova response: missing embedding")
    if len(vec) != expected_dim:
        raise EmbeddingError(
            f"hyperclova embedding dim mismatch: got {len(vec)} expected {expected_dim}"
        )
    try:
        return [float(x) for x in vec]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError(f"hyperclova embedding contains non-float: {exc}") from exc


__all__ = ["EmbeddingClient", "EmbeddingError", "HyperClovaEmbeddingClient"]
