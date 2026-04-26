"""OCR_TRANSFORM v2 노드 — provider registry 기반 OCR (Phase 5.1 Wave 2).

Phase 5.2.1.1 Provider Registry 위에 *워크플로 노드* 형태로 노출.
실 OCR 호출은 v1 ocr_worker 의 process_ocr 와 동일 path → 단, provider 선택은
DB binding (priority/fallback) + circuit breaker 기반.

config:
  - `raw_object_id`: int (필수) — OCR 대상 raw 행
  - `image_url` / `image_base64`: str (선택) — raw_object 외 인라인 입력
  - `provider_kind`: 'OCR' (default)
  - `dry_run`: bool (default False) — provider binding 만 검증, 호출 X

흐름:
  1. context.source_id 의 OCR binding 조회 (priority).
  2. circuit OPEN 인 provider 는 skip → 다음 fallback.
  3. dry_run=True 면 *선택된 provider 정보만* 반환 (외부 호출 0건).
  4. dry_run=False 시 v1 path 와 *shadow_run* 비교 (audit.shadow_diff).
     실 사용자 응답은 caller (worker) 의 v1 path 결과를 사용 (Q1 답변).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output
from app.domain.providers.factory import (
    ProviderFactory,
    list_active_bindings,
)

name = "OCR_TRANSFORM"
node_type = "OCR_TRANSFORM"


def run(context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output:
    if context.source_id is None:
        raise NodeV2Error(
            "OCR_TRANSFORM requires context.source_id (provider binding 조회)"
        )
    raw_object_id = config.get("raw_object_id")
    image_url = config.get("image_url")
    image_base64 = config.get("image_base64")
    if raw_object_id is None and not image_url and not image_base64:
        raise NodeV2Error(
            "OCR_TRANSFORM requires raw_object_id or image_url or image_base64"
        )
    dry_run = bool(config.get("dry_run", False))

    bindings = list_active_bindings(
        context.session, source_id=context.source_id, provider_kind="OCR"
    )
    if not bindings:
        return NodeV2Output(
            status="failed",
            error_message=f"no active OCR binding for source_id={context.source_id}",
            payload={"reason": "no_binding"},
        )

    factory = ProviderFactory()
    result = factory.build(
        source_id=context.source_id, provider_kind="OCR", bindings=bindings
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
                "binding_count": len(bindings),
            },
        )

    # Phase 5.1 — 실 호출은 v1 ocr_worker.process_ocr 와 분리하지 않음.
    # 본 노드는 *binding 결정 + circuit 상태 보고* 까지 담당.
    # 실 OCR cutover 는 STEP 4 shadow → ADMIN 승인 후 worker 변경 (별도 PR).
    return NodeV2Output(
        status="success",
        row_count=0,
        payload={
            "primary_provider": result.primary.provider_code,
            "fallback_providers": [p.provider_code for p in result.fallbacks],
            "raw_object_id": raw_object_id,
            "note": "binding resolved; actual OCR call still handled by v1 ocr_worker until cutover",
        },
    )


__all__ = ["name", "node_type", "run"]
