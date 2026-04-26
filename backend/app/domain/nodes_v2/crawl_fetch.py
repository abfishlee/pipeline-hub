"""CRAWL_FETCH v2 노드 — provider registry 기반 crawler (Phase 5.1 Wave 2).

OCR_TRANSFORM 와 동일 패턴. Provider Registry 의 CRAWLER kind 사용.

config:
  - `target_url`: str (필수)
  - `crawler_options`: dict (선택, ex: `{"timeout_sec": 30}`)
  - `dry_run`: bool (default False)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output
from app.domain.providers.factory import (
    ProviderFactory,
    list_active_bindings,
)

name = "CRAWL_FETCH"
node_type = "CRAWL_FETCH"


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    if context.source_id is None:
        raise NodeV2Error(
            "CRAWL_FETCH requires context.source_id (provider binding 조회)"
        )
    target_url = str(config.get("target_url") or "").strip()
    if not target_url:
        raise NodeV2Error("CRAWL_FETCH requires target_url")
    dry_run = bool(config.get("dry_run", False))

    bindings = list_active_bindings(
        context.session, source_id=context.source_id, provider_kind="CRAWLER"
    )
    if not bindings:
        return NodeV2Output(
            status="failed",
            error_message=f"no active CRAWLER binding for source_id={context.source_id}",
            payload={"reason": "no_binding"},
        )

    factory = ProviderFactory()
    result = factory.build(
        source_id=context.source_id, provider_kind="CRAWLER", bindings=bindings
    )
    if result.primary is None:
        return NodeV2Output(
            status="failed",
            error_message="no provider instance could be created",
            payload={"reason": "no_provider"},
        )

    if dry_run:
        return NodeV2Output(
            status="success",
            row_count=0,
            payload={
                "dry_run": True,
                "primary_provider": result.primary.provider_code,
                "fallback_providers": [p.provider_code for p in result.fallbacks],
                "target_url": target_url,
            },
        )

    return NodeV2Output(
        status="success",
        row_count=0,
        payload={
            "primary_provider": result.primary.provider_code,
            "fallback_providers": [p.provider_code for p in result.fallbacks],
            "target_url": target_url,
            "note": "binding resolved; actual crawl call still handled by v1 crawler_worker until cutover",
        },
    )


__all__ = ["name", "node_type", "run"]
