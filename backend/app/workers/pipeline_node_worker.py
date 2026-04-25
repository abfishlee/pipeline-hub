"""Pipeline 노드 실행 worker (Phase 3.2.1).

`process_node_event(node_run_id, run_date_iso)` actor 가 enqueue 되면 노드 1개를
실행하고 `complete_node` 로 결과를 보고. Phase 3.2.1 한정으로 NOOP 노드만 처리
(즉시 SUCCESS). 다른 type 은 Phase 3.2.2 에서 분기 추가.

idempotent: 같은 `event_id` 가 재처리되면 `processed_event` 마킹으로 skip.
"""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Any

from app.core.events import RedisPubSub
from app.db.sync_session import get_sync_sessionmaker
from app.domain.idempotent_consume import consume_idempotent
from app.domain.pipeline_runtime import complete_node, mark_node_running
from app.models.run import NodeRun
from app.workers import pipeline_actor


def _execute_node(node_run: NodeRun) -> dict[str, Any] | None:
    """노드 타입별 실제 작업 디스패치. Phase 3.2.1 한정 NOOP 만."""
    if node_run.node_type == "NOOP":
        return {"noop": True, "node_key": node_run.node_key}
    raise NotImplementedError(f"node_type={node_run.node_type} not implemented (Phase 3.2.2 후속)")


@pipeline_actor(queue_name="pipeline_node", max_retries=3, time_limit=120_000)
def process_node_event(
    event_id: str,
    node_run_id: int,
    run_date_iso: str,
) -> dict[str, Any]:
    """노드 1건 실행. event_id 는 idempotent 키 (보통 `node-run-{id}-attempt-{n}`)."""
    del run_date_iso  # 미사용 — node_run_id 만으로 식별. signature 호환용.
    sm = get_sync_sessionmaker()
    pubsub = RedisPubSub.from_settings()

    def _handler(session: object) -> dict[str, Any]:
        # 1) RUNNING 마킹
        nr = mark_node_running(
            session,  # type: ignore[arg-type]
            node_run_id=node_run_id,
            pubsub=pubsub,
        )

        # 2) 노드 실행 — 실패 시 caller (consume_idempotent) 가 rollback 해서
        #    상태가 다시 PENDING/READY 로 돌아간다. 다음 enqueue 에서 재시도.
        try:
            output = _execute_node(nr)
        except Exception as exc:
            complete_node(
                session,  # type: ignore[arg-type]
                node_run_id=node_run_id,
                status="FAILED",
                error_message=str(exc)[:2000],
                pubsub=pubsub,
            )
            return {"status": "FAILED", "error": str(exc)[:200]}

        # 3) SUCCESS 마킹 + 후속 노드 dispatch.
        completion = complete_node(
            session,  # type: ignore[arg-type]
            node_run_id=node_run_id,
            status="SUCCESS",
            output_json=output,
            pubsub=pubsub,
        )
        return {
            "status": "SUCCESS",
            "pipeline_status": completion.pipeline_status,
            "next_ready": list(completion.next_ready_node_run_ids),
        }

    try:
        with sm() as session:
            result = consume_idempotent(
                session,
                event_id=event_id,
                consumer_name="pipeline-node-worker",
                handler=_handler,
            )
        if not result.processed:
            return {"status": "skipped_idempotent", "event_id": event_id}
        out = result.value
        assert out is not None
        out["event_id"] = event_id
        out["node_run_id"] = node_run_id

        # 4) next_ready 노드들도 actor 로 enqueue (자가 fan-out).
        next_ready = out.get("next_ready") or []
        if isinstance(next_ready, list):
            for next_id in next_ready:
                process_node_event.send(
                    event_id=f"node-run-{next_id}-{datetime.utcnow().isoformat()}",
                    node_run_id=int(next_id),
                    run_date_iso=_today_iso(),
                )
        return out
    finally:
        pubsub.close()


def _today_iso() -> str:
    return DateType.today().isoformat()


__all__ = ["process_node_event"]
