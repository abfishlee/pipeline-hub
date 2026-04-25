"""Visual ETL 노드 실행자 (Phase 3.2.2).

각 노드는 `NodeProtocol.run(context, config) -> NodeOutput` 단일 인터페이스를
만족한다. Worker(`pipeline_node_worker._execute_node`) 가 node_type 별로
적절한 모듈의 `run` 을 호출.

설계 메모:
  - 노드 함수는 **sync** — Worker 가 sync session 위에서 동작. 외부 IO(예: Slack
    webhook) 가 필요한 노드만 함수 내부에서 `asyncio.run` 으로 감싼다.
  - 실패는 `NodeError` 또는 `NodeOutput(status='failed')` 둘 다 가능.
    `NodeError` 는 actor 가 retry/DLQ 에 회부하고, `failed` 는 비즈니스 실패
    (DQ 위반 등 — 정상 흐름) 로 노드는 FAILED 종결, downstream 은 SKIPPED.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from sqlalchemy.orm import Session

NodeStatus = Literal["success", "failed"]


class NodeError(Exception):
    """노드 실행 실패 — actor 가 retry/DLQ. 비즈니스 실패는 NodeOutput 으로."""


@dataclass(slots=True, frozen=True)
class NodeContext:
    """노드 실행 시 도메인이 제공하는 모든 의존성."""

    session: Session
    pipeline_run_id: int
    node_run_id: int
    node_key: str
    user_id: int | None
    upstream_outputs: Mapping[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class NodeOutput:
    status: NodeStatus
    row_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


@runtime_checkable
class NodeProtocol(Protocol):
    """모든 노드 모듈이 만족해야 하는 단일 시그니처."""

    name: str

    def run(self, context: NodeContext, config: Mapping[str, Any]) -> NodeOutput: ...


# 등록 — pipeline_node_worker 가 dispatch 시 사용. 노드 타입 → callable.
def get_node_runner(node_type: str) -> NodeProtocol:
    """`node_type` 에 매칭되는 runner 반환.

    매번 import 해서 단일 점입점 유지. 미지원 타입은 `NodeError`.
    """
    from app.domain.nodes import (
        dedup,
        dq_check,
        load_master,
        notify,
        source_api,
        sql_transform,
    )

    registry: dict[str, NodeProtocol] = {
        "NOOP": _noop_runner,
        "SOURCE_API": source_api,
        "SQL_TRANSFORM": sql_transform,
        "DEDUP": dedup,
        "DQ_CHECK": dq_check,
        "LOAD_MASTER": load_master,
        "NOTIFY": notify,
    }
    runner = registry.get(node_type)
    if runner is None:
        raise NodeError(f"unsupported node_type: {node_type}")
    return runner


class _NoopRunner:
    name = "NOOP"

    def run(self, context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
        del context, config
        return NodeOutput(status="success", row_count=0, payload={"noop": True})


_noop_runner = _NoopRunner()


__all__ = [
    "NodeContext",
    "NodeError",
    "NodeOutput",
    "NodeProtocol",
    "NodeStatus",
    "get_node_runner",
]
