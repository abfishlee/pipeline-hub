"""Phase 5.2.2 — FUNCTION_TRANSFORM 노드의 *허용 함수 레지스트리*.

generic 노드 카탈로그의 핵심 가드: 사용자가 mapping 의 `transform_expr` 또는
FUNCTION_TRANSFORM 노드 config 에 임의 함수 호출을 적을 수 있게 하되, **부작용 없는
순수 함수** allowlist 만 실행되도록 강제. eval/exec 절대 금지.

자세한 구조는 `app.domain.functions.registry` 참고.
"""

from __future__ import annotations

from app.domain.functions.registry import (
    FUNCTION_REGISTRY,
    FunctionCallError,
    FunctionSpec,
    apply_expression,
    call_function,
    list_functions,
)

__all__ = [
    "FUNCTION_REGISTRY",
    "FunctionCallError",
    "FunctionSpec",
    "apply_expression",
    "call_function",
    "list_functions",
]
