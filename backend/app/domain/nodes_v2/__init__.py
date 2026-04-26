"""v2 generic 노드 카탈로그 (Phase 5.2.2).

v1 의 7노드 (`SOURCE_API/SQL_TRANSFORM/DEDUP/DQ_CHECK/LOAD_MASTER/NOTIFY/NOOP`) 를
**generic 화** — 도메인 의존이 사라진 13+ 노드.

5.2.2 STEP 5 범위 (Q1 답변 — v1 워크플로 자동 마이그 X, *신규 워크플로만* 새 카탈로그):

  generic 코어 6종 (본 STEP):
    1. MAP_FIELDS            — field_mapping registry 기반 col → col 변환
    2. SQL_INLINE_TRANSFORM  — sandbox-only inline SELECT (Q2)
    3. SQL_ASSET_TRANSFORM   — APPROVED sql_asset 만 production publish (Q2)
    4. HTTP_TRANSFORM        — secret_ref 기반 외부 정제 API 호출 (Q3)
    5. FUNCTION_TRANSFORM    — allowlist 함수만 행 단위 적용 (Q4)
    6. LOAD_TARGET           — load_policy 기반 generic 적재

  *호환 + 미구현 placeholder*:
    DEDUP / DQ_CHECK / NOTIFY / SOURCE_DATA — v1 모듈 참조 또는 thin wrapper.
    OCR_TRANSFORM / CRAWL_FETCH — STEP 4 follow-up (provider shadow hooks).
    STANDARDIZE — STEP 6 (Q5 namespace + per-(namespace,provider,dimension) vector).

각 노드는 **NodeV2Protocol.run(ctx, config) → NodeV2Output** 를 만족. v1 의
`get_node_runner` 와 분리해 v2 worker 가 따로 dispatch.

설계 메모:
  - context 는 v1 `NodeContext` 와 동일 모양 + `domain_code` / `contract_id` 추가.
  - 가드: SQL_INLINE / SQL_ASSET / LOAD_TARGET 은 본 노드 진입 전에 `sql_guard.guard_sql`
    호출. 통과한 sql 만 실행.
  - DRY-RUN: pipeline_run_id 가 음수면 dry-run (caller 가 negative ID 로 표시).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from sqlalchemy.orm import Session

NodeV2Status = Literal["success", "failed"]


class NodeV2Error(Exception):
    """v2 노드 인프라 실패 — actor 가 retry/DLQ. 비즈니스 실패는 NodeV2Output 사용."""


@dataclass(slots=True, frozen=True)
class NodeV2Context:
    """v2 generic 노드 실행 시 도메인이 제공하는 의존성.

    v1 NodeContext 와의 차이:
      * domain_code / contract_id 가 *항상 결정됨* (v1 은 mart 직접 참조여서 무관계).
      * upstream_outputs 는 v1 과 동일 — 노드 간 데이터 전달은 sandbox table FQDN.
    """

    session: Session
    pipeline_run_id: int
    node_run_id: int
    node_key: str
    domain_code: str
    contract_id: int | None = None
    source_id: int | None = None
    user_id: int | None = None
    upstream_outputs: Mapping[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class NodeV2Output:
    status: NodeV2Status
    row_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


@runtime_checkable
class NodeV2Protocol(Protocol):
    """v2 노드 모듈이 만족해야 하는 단일 시그니처."""

    name: str
    node_type: str

    def run(self, context: NodeV2Context, config: Mapping[str, Any]) -> NodeV2Output: ...


def get_v2_runner(node_type: str) -> NodeV2Protocol:
    """node_type → runner. 미지원/placeholder 는 NodeV2Error."""
    from app.domain.nodes_v2 import (
        function_transform,
        http_transform,
        load_target,
        map_fields,
        sql_asset_transform,
        sql_inline_transform,
    )

    registry: dict[str, NodeV2Protocol] = {
        "MAP_FIELDS": map_fields,
        "SQL_INLINE_TRANSFORM": sql_inline_transform,
        "SQL_ASSET_TRANSFORM": sql_asset_transform,
        "HTTP_TRANSFORM": http_transform,
        "FUNCTION_TRANSFORM": function_transform,
        "LOAD_TARGET": load_target,
    }
    runner = registry.get(node_type)
    if runner is None:
        raise NodeV2Error(f"unsupported v2 node_type: {node_type}")
    return runner


def list_v2_node_types() -> list[str]:
    """문서화 / UX 용 — 등록된 generic node_type 들."""
    return [
        "MAP_FIELDS",
        "SQL_INLINE_TRANSFORM",
        "SQL_ASSET_TRANSFORM",
        "HTTP_TRANSFORM",
        "FUNCTION_TRANSFORM",
        "LOAD_TARGET",
    ]


__all__ = [
    "NodeV2Context",
    "NodeV2Error",
    "NodeV2Output",
    "NodeV2Protocol",
    "NodeV2Status",
    "get_v2_runner",
    "list_v2_node_types",
]
