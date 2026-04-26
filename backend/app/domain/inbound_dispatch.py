"""Inbound event → workflow trigger dispatcher (Phase 7 Wave 6 — minimal).

InboundChannel 에 workflow_id 가 연결되어 있으면 envelope status=RECEIVED 인
이벤트를 발견 시 해당 workflow 의 새 pipeline_run 을 trigger.

본 dispatcher 는 Phase 7 Wave 6 의 *최소 구현* — Dramatiq actor / outbox 정식
통합은 Wave 6 본격 구현 시 보강.

엔드포인트 호출 패턴:
  POST /v2/operations/dispatch-pending  — pending RECEIVED envelope 일괄 처리
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DispatchResult:
    envelope_id: int
    channel_code: str
    workflow_id: int | None
    pipeline_run_id: int | None
    status: str
    error: str | None = None


def dispatch_received_envelopes(
    session: Session, *, limit: int = 50
) -> list[DispatchResult]:
    """RECEIVED envelope 들을 PROCESSING 으로 전환하고 workflow trigger.

    InboundChannel.workflow_id 가 NULL 이면 envelope 만 PROCESSING 으로 두고 skip
    (수동 처리). 향후 Wave 6 정식 구현에서 outbox + Dramatiq 로 전환.
    """
    rows = session.execute(
        text(
            """
            SELECT e.envelope_id, e.channel_code, e.channel_id, e.domain_code,
                   c.workflow_id
              FROM audit.inbound_event e
              JOIN domain.inbound_channel c ON e.channel_id = c.channel_id
             WHERE e.status = 'RECEIVED'
               AND c.is_active = true
               AND c.status = 'PUBLISHED'
             ORDER BY e.received_at
             LIMIT :lim
            """
        ),
        {"lim": min(max(limit, 1), 500)},
    ).all()

    results: list[DispatchResult] = []
    for r in rows:
        envelope_id = int(r.envelope_id)
        wf_id = int(r.workflow_id) if r.workflow_id else None
        if wf_id is None:
            session.execute(
                text(
                    "UPDATE audit.inbound_event "
                    "SET status='PROCESSING', processed_at=now() "
                    "WHERE envelope_id = :eid"
                ),
                {"eid": envelope_id},
            )
            results.append(
                DispatchResult(
                    envelope_id=envelope_id,
                    channel_code=str(r.channel_code),
                    workflow_id=None,
                    pipeline_run_id=None,
                    status="manual",
                    error="no workflow_id binding (manual handling)",
                )
            )
            continue

        try:
            run_row = session.execute(
                text(
                    "INSERT INTO run.pipeline_run "
                    "(workflow_id, run_date, status) "
                    "VALUES (:wid, CURRENT_DATE, 'PENDING') "
                    "RETURNING pipeline_run_id"
                ),
                {"wid": wf_id},
            ).first()
            assert run_row is not None
            run_id = int(run_row[0])
            session.execute(
                text(
                    "UPDATE audit.inbound_event "
                    "SET status='PROCESSING', workflow_run_id=:rid, "
                    "    processed_at=now() "
                    "WHERE envelope_id = :eid"
                ),
                {"rid": run_id, "eid": envelope_id},
            )
            results.append(
                DispatchResult(
                    envelope_id=envelope_id,
                    channel_code=str(r.channel_code),
                    workflow_id=wf_id,
                    pipeline_run_id=run_id,
                    status="dispatched",
                )
            )
        except Exception as exc:
            session.execute(
                text(
                    "UPDATE audit.inbound_event "
                    "SET status='FAILED', error_message=:err, "
                    "    processed_at=now() "
                    "WHERE envelope_id = :eid"
                ),
                {"eid": envelope_id, "err": str(exc)[:500]},
            )
            results.append(
                DispatchResult(
                    envelope_id=envelope_id,
                    channel_code=str(r.channel_code),
                    workflow_id=wf_id,
                    pipeline_run_id=None,
                    status="failed",
                    error=str(exc)[:200],
                )
            )

    return results


def fetch_pending_envelope_count(session: Session) -> int:
    return int(
        session.execute(
            text(
                "SELECT COUNT(*) FROM audit.inbound_event WHERE status = 'RECEIVED'"
            )
        ).scalar_one()
    )


__all__: list[str] = [
    "DispatchResult",
    "dispatch_received_envelopes",
    "fetch_pending_envelope_count",
]
