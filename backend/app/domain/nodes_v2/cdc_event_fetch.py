"""CDC_EVENT_FETCH v2 노드 — Phase 7 Wave 1B stub (Phase 9 정식 구현 예정).

PostgreSQL logical replication slot (`wal2json`) 또는 Debezium 으로부터 변경
이벤트를 받아 sandbox 로 적재하는 노드.

본 stub 은 *노드 등록 + dispatcher 라우팅* 만 보장. 실제 슬롯 구독 / 변경 적용은
Phase 9 backlog (사용자 § 5 — CDC_EVENT_FETCH 정리).

==============================================================================
Phase 8.4 — 정식 구현 조건 (CLAUDE.md § 3 정책 정합):
  *CDC 소스 3개 초과* 또는 *일 트래픽 500K rows 초과* 시 본 stub 을 정식
  구현으로 대체. 현재는 시범 운영을 위해 *Canvas 배치는 가능*하지만 dry-run /
  실행은 stub 응답 (event_count=0) 만 반환.

  Phase 9 정식 구현 항목:
    - app/integrations/cdc/wal2json_consumer.py — pg_replication_slot stream
    - LSN 기반 incremental (ctl.cdc_subscription.last_committed_lsn 활용)
    - INSERT / UPDATE / DELETE 분기 처리 + raw.db_cdc_event 적재
    - retry / DLQ 정책 (slot lag 임계 초과 시 알람)
==============================================================================

config:
  - `replication_slot_name`: str (필수, stub 에서는 검증만)
  - `dry_run`: bool

향후 Phase 9 에서 보강:
  - app/integrations/cdc/wal2json_consumer.py 와 통합
  - LSN 기반 incremental
  - INSERT/UPDATE/DELETE 분기 처리
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.domain.nodes_v2 import NodeV2Context, NodeV2Error, NodeV2Output

logger = logging.getLogger(__name__)

name = "CDC_EVENT_FETCH"
node_type = "CDC_EVENT_FETCH"


def run(
    context: NodeV2Context, config: Mapping[str, Any]
) -> NodeV2Output:
    slot_name = config.get("replication_slot_name")
    if not slot_name:
        raise NodeV2Error("CDC_EVENT_FETCH: replication_slot_name required")

    logger.info(
        "cdc_event_fetch.stub_invoked",
        extra={"slot": slot_name, "domain": context.domain_code},
    )

    # Phase 8.1 stub — 실제 wal2json 구독은 Phase 9 backlog.
    return NodeV2Output(
        status="success",
        row_count=0,
        payload={
            "replication_slot_name": str(slot_name),
            "domain_code": context.domain_code,
            "note": (
                "Phase 8.1 stub — full implementation pending. "
                "See app/integrations/cdc/wal2json_consumer.py for "
                "underlying consumer."
            ),
            "stub": True,
        },
    )


__all__ = ["name", "node_type", "run"]
