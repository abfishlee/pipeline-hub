"""HyperCLOVA (NCP CLOVA Studio) 통합 어댑터 (Phase 2.2.5)."""

from __future__ import annotations

from app.integrations.hyperclova.client import (
    EmbeddingClient,
    HyperClovaEmbeddingClient,
)

__all__ = ["EmbeddingClient", "HyperClovaEmbeddingClient"]
