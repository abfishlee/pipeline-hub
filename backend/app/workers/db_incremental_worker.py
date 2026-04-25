"""DB-to-DB 증분 수집 워커 (Phase 2.2.7).

`process_db_incremental_event(source_code)` actor 가 enqueue 되면 도메인 호출.
트리거:
  - 1차: Airflow `system_ingest_db_incremental` DAG (Phase 2.2.3 후속) 가 매 10분마다
    각 활성 DB source 에 대해 `.send(source_code=...)`.
  - 2차(임시): 운영자가 콘솔/CLI 에서 직접 send.

watermark 자체가 진행 보장이라 별도 `consume_idempotent` 불필요. 단, dramatiq 큐에서
같은 source_code 가 2건 동시에 실행되면 동일 row 를 둘 다 fetch 시도 → content_hash
중복으로 한 쪽이 dedup 처리. 큐 동시성은 Airflow scheduler 가 1회/주기 보장.
"""

from __future__ import annotations

from typing import Any

from app.db.sync_session import get_sync_sessionmaker
from app.domain.db_incremental import DbIncrementalOutcome, pull_incremental
from app.workers import pipeline_actor


@pipeline_actor(queue_name="db_incremental", max_retries=3, time_limit=300_000)
def process_db_incremental_event(
    source_code: str,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """1회 incremental fetch + 적재. 결과 통계 dict."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        outcome: DbIncrementalOutcome = pull_incremental(
            session,
            source_code=source_code,
            batch_size=batch_size,
        )
        session.commit()
    return {
        "source_code": outcome.source_code,
        "pulled": outcome.pulled_count,
        "inserted": outcome.inserted_count,
        "deduped": outcome.deduped_count,
        "last_cursor": str(outcome.last_cursor) if outcome.last_cursor is not None else None,
    }


__all__ = ["process_db_incremental_event"]
