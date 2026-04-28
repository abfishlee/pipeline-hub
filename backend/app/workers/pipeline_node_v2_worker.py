"""v2 generic 노드 worker (Phase 5.2.2 STEP 5).

v1 `pipeline_node_worker.process_node_event` 와 *완전 분리*:
  * v1 worker 는 그대로 — 기존 7노드 카탈로그 + mart 직접 적재 흐름.
  * v2 worker 는 generic 6노드 (+ STEP 6+ placeholder) 를 dispatch.
  * 같은 dramatiq broker 에 다른 큐 (`pipeline_node_v2`) — 운영자가 v1/v2 traffic 분리 가능.

flow:
  1. mark_node_running (v1 과 동일 — pipeline_run_id 추적은 공통).
  2. domain_code / contract_id / source_id 를 NodeRun → NodeDefinition → workflow 메타에서
     재구성 (v1 NodeRun 모델은 *generic 컨텍스트* 미내장 → caller 가 trigger 시 inject).
  3. node_type 이 v2 catalog 면 본 worker 가 처리, 아니면 NodeV2Error("not v2 type").

v2 트리거는 별도 PR (STEP 7 ETL UX) 에서 enqueue. 본 STEP 은 worker 자체.
"""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.events import RedisPubSub
from app.db.sync_session import get_sync_sessionmaker
from app.domain.idempotent_consume import consume_idempotent
from app.domain.nodes_v2 import (
    NodeV2Context,
    NodeV2Error,
    NodeV2Output,
    get_v2_runner,
    list_v2_node_types,
)
from app.domain.pipeline_runtime import complete_node, mark_node_running
from app.models.run import NodeRun
from app.models.wf import EdgeDefinition, NodeDefinition
from app.workers import pipeline_actor

V2_NODE_TYPES: frozenset[str] = frozenset(list_v2_node_types())


def _v2_runtime_context(
    config: dict[str, Any], *, fallback_domain: str = "agri"
) -> tuple[str, int | None, int | None]:
    """node config 에서 domain_code / contract_id / source_id 추출.

    Phase 5.2.2 MVP — caller 가 NodeDefinition.config_json 에 명시적으로 주입했다고 가정.
    Phase 5.2.4 ETL UX 가 워크플로 빌드 시 자동 주입.
    """
    domain_code = str(config.get("domain_code") or fallback_domain)
    contract_id = config.get("contract_id")
    source_id = config.get("source_id")
    return (
        domain_code,
        int(contract_id) if contract_id is not None else None,
        int(source_id) if source_id is not None else None,
    )


def _execute_v2(session: Session, node_run: NodeRun) -> NodeV2Output:
    nd = session.get(NodeDefinition, node_run.node_definition_id)
    if nd is None:
        raise NodeV2Error(f"node_definition {node_run.node_definition_id} missing")
    if node_run.node_type not in V2_NODE_TYPES:
        raise NodeV2Error(
            f"node_type {node_run.node_type!r} is not a v2 generic type "
            f"(v2: {sorted(V2_NODE_TYPES)})"
        )
    config: dict[str, Any] = dict(nd.config_json or {})
    domain_code, contract_id, source_id = _v2_runtime_context(config)
    runner = get_v2_runner(node_run.node_type)
    upstream_outputs = _upstream_outputs(session, node_run=node_run, node=nd)
    ctx = NodeV2Context(
        session=session,
        pipeline_run_id=node_run.pipeline_run_id,
        node_run_id=node_run.node_run_id,
        node_key=node_run.node_key,
        domain_code=domain_code,
        contract_id=contract_id,
        source_id=source_id,
        user_id=None,
        upstream_outputs=upstream_outputs,
    )
    return runner.run(ctx, config)


def _upstream_outputs(
    session: Session, *, node_run: NodeRun, node: NodeDefinition
) -> dict[str, dict[str, Any]]:
    edges = (
        session.query(EdgeDefinition)
        .filter(EdgeDefinition.workflow_id == node.workflow_id)
        .filter(EdgeDefinition.to_node_id == node.node_id)
        .all()
    )
    if not edges:
        return {}
    from_ids = [e.from_node_id for e in edges]
    rows = (
        session.query(NodeRun)
        .filter(NodeRun.pipeline_run_id == node_run.pipeline_run_id)
        .filter(NodeRun.run_date == node_run.run_date)
        .filter(NodeRun.node_definition_id.in_(from_ids))
        .all()
    )
    key_by_def = {
        n.node_id: n.node_key
        for n in session.query(NodeDefinition)
        .filter(NodeDefinition.node_id.in_(from_ids))
        .all()
    }
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.status != "SUCCESS":
            continue
        node_key = key_by_def.get(row.node_definition_id)
        if not node_key:
            continue
        payload = row.output_json if isinstance(row.output_json, dict) else {}
        out[node_key] = dict(payload)
    return out


@pipeline_actor(queue_name="pipeline_node_v2", max_retries=3, time_limit=180_000)
def process_v2_node_event(
    event_id: str,
    node_run_id: int,
    run_date_iso: str,
) -> dict[str, Any]:
    """v2 노드 1건 실행. v1 worker 와 같은 idempotent / pubsub / completion 패턴."""
    del run_date_iso
    sm = get_sync_sessionmaker()
    pubsub = RedisPubSub.from_settings()

    def _handler(session: object) -> dict[str, Any]:
        nr = mark_node_running(
            session,  # type: ignore[arg-type]
            node_run_id=node_run_id,
            pubsub=pubsub,
        )
        try:
            output = _execute_v2(session, nr)  # type: ignore[arg-type]
        except NodeV2Error as exc:
            completion = complete_node(
                session,  # type: ignore[arg-type]
                node_run_id=node_run_id,
                status="FAILED",
                error_message=str(exc)[:2000],
                pubsub=pubsub,
            )
            return {
                "status": "FAILED",
                "error": str(exc)[:200],
                "pipeline_status": completion.pipeline_status,
                "next_ready": list(completion.next_ready_node_run_ids),
            }
        except Exception:
            raise

        if output.status == "failed":
            completion = complete_node(
                session,  # type: ignore[arg-type]
                node_run_id=node_run_id,
                status="FAILED",
                error_message=output.error_message,
                output_json=output.payload,
                pubsub=pubsub,
            )
            return {
                "status": "FAILED",
                "error": output.error_message,
                "pipeline_status": completion.pipeline_status,
                "next_ready": list(completion.next_ready_node_run_ids),
            }

        completion = complete_node(
            session,  # type: ignore[arg-type]
            node_run_id=node_run_id,
            status="SUCCESS",
            output_json=output.payload,
            pubsub=pubsub,
        )
        return {
            "status": "SUCCESS",
            "row_count": output.row_count,
            "pipeline_status": completion.pipeline_status,
            "next_ready": list(completion.next_ready_node_run_ids),
        }

    try:
        with sm() as session:
            result = consume_idempotent(
                session,
                event_id=event_id,
                consumer_name="pipeline-node-v2-worker",
                handler=_handler,
            )
        if not result.processed:
            return {"status": "skipped_idempotent", "event_id": event_id}
        out = result.value
        assert out is not None
        out["event_id"] = event_id
        out["node_run_id"] = node_run_id

        next_ready = out.get("next_ready") or []
        if isinstance(next_ready, list):
            for next_id in next_ready:
                process_v2_node_event.send(
                    event_id=f"v2-node-run-{next_id}-{datetime.utcnow().isoformat()}",
                    node_run_id=int(next_id),
                    run_date_iso=DateType.today().isoformat(),
                )
        return out
    finally:
        pubsub.close()


__all__ = ["V2_NODE_TYPES", "process_v2_node_event"]
