"""v1 노드를 v2 dispatcher 에 노출하는 thin wrapper (Phase 5.1 Wave 2).

Phase 5.1 보완 — DEDUP / DQ_CHECK / NOTIFY / SOURCE_DATA 4종은 *이미 v1 구현이
충분히 generic* 이라 v2 NodeV2Context 만 v1 NodeContext 로 변환 후 그대로 호출.

추가 가드:
  - domain_code 가 ctx 에 있어도 v1 노드는 무시 (v1 은 도메인 무관).
  - sql_guard 같은 v2 가드는 v1 노드가 *이미 수년간 검증된 자체 검증* 을 가짐.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.nodes import (
    NodeContext as V1NodeContext,
)
from app.domain.nodes import (
    NodeError as V1NodeError,
)
from app.domain.nodes import (
    NodeOutput as V1NodeOutput,
)
from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output


def to_v1_context(ctx: NodeV2Context) -> V1NodeContext:
    """NodeV2Context → v1 NodeContext 변환. domain_code/contract_id 는 누락."""
    return V1NodeContext(
        session=ctx.session,
        pipeline_run_id=ctx.pipeline_run_id,
        node_run_id=ctx.node_run_id,
        node_key=ctx.node_key,
        user_id=ctx.user_id,
        upstream_outputs=dict(ctx.upstream_outputs),
    )


def to_v2_output(out: V1NodeOutput) -> NodeV2Output:
    return NodeV2Output(
        status=out.status,
        row_count=out.row_count,
        payload=dict(out.payload),
        error_message=out.error_message,
    )


@dataclass(slots=True, frozen=True)
class V1WrappedRunner:
    """v1 노드 module 을 NodeV2Protocol 형태로 노출."""

    name: str
    node_type: str
    v1_module: Any  # has .run(NodeContext, Mapping) -> NodeOutput

    def run(
        self, context: NodeV2Context, config: Mapping[str, Any]
    ) -> NodeV2Output:
        try:
            v1_ctx = to_v1_context(context)
            out = self.v1_module.run(v1_ctx, config)
        except V1NodeError as exc:
            raise NodeV2Error(str(exc)) from exc
        return to_v2_output(out)


__all__ = ["V1WrappedRunner", "to_v1_context", "to_v2_output"]
