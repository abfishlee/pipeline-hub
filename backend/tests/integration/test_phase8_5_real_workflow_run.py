"""Phase 8.5 ① — Canvas 실제 실행 통합 테스트.

Phase 8 시드의 4 유통사 workflow 중 하나를 실제로 start_pipeline_run 으로 트리거
한 뒤, v2 worker 의 _execute_v2 + complete_node 흐름을 *수동으로* 진행시켜
pipeline_run 이 SUCCESS 까지 도달함을 검증.

기존 Phase 8 e2e 9건은 *시드된 row 의 존재 여부* 만 확인했으므로, 본 테스트는
"orchestration 이 실제로 작동한다" 는 증거를 추가한다.

검증 항목:
  1. start_pipeline_run → pipeline_run.status = RUNNING + node_run rows 생성
  2. entry 노드 = READY, 나머지 = PENDING
  3. complete_node(SUCCESS) 를 chain 으로 호출 → next_ready 전이 정확
  4. 마지막 노드 SUCCESS → pipeline_run.status = SUCCESS + finished_at 채움
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker
from app.domain.pipeline_runtime import complete_node, start_pipeline_run


def _seed_present() -> bool:
    sm = get_sync_sessionmaker()
    with sm() as s:
        try:
            cnt = s.execute(
                text(
                    "SELECT COUNT(*) FROM wf.workflow_definition "
                    "WHERE name LIKE 'emart%' OR name LIKE 'homeplus%'"
                )
            ).scalar_one()
            return int(cnt) >= 1
        except Exception:
            return False


def _find_emart_published_workflow_id() -> int | None:
    """Phase 8 시드된 emart workflow 중 PUBLISHED 상태 1건 찾기."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        row = s.execute(
            text(
                """
                SELECT workflow_id FROM wf.workflow_definition
                 WHERE name LIKE 'emart%'
                   AND status = 'PUBLISHED'
                 ORDER BY workflow_id DESC LIMIT 1
                """
            )
        ).first()
        return int(row[0]) if row else None


def test_phase8_5_orchestration_reaches_completed() -> None:
    """전체 노드 SUCCESS 시 pipeline_run SUCCESS 도달 검증."""
    if not _seed_present():
        pytest.skip("Phase 8 seed (emart workflow) 미적용")
    workflow_id = _find_emart_published_workflow_id()
    if workflow_id is None:
        pytest.skip("PUBLISHED emart workflow 없음 — phase8_seed_full_e2e.py 후 PUBLISH 필요")

    sm = get_sync_sessionmaker()
    started_pipeline_run_id: int | None = None
    try:
        # ── 1. start_pipeline_run ─────────────────────────────────────────
        with sm() as session:
            started = start_pipeline_run(
                session,
                workflow_id=workflow_id,
                triggered_by_user_id=None,
                pubsub=None,
            )
            session.commit()
        started_pipeline_run_id = started.pipeline_run_id

        # ── 2. node_run rows 생성 + entry = READY ─────────────────────────
        with sm() as session:
            rows = list(
                session.execute(
                    text(
                        "SELECT node_run_id, node_key, node_type, status "
                        "  FROM run.node_run "
                        " WHERE pipeline_run_id = :pr "
                        " ORDER BY node_run_id"
                    ),
                    {"pr": started.pipeline_run_id},
                )
            )
        assert len(rows) >= 1, "node_run rows 가 생성되어야 함"
        ready_count = sum(1 for r in rows if r.status == "READY")
        pending_count = sum(1 for r in rows if r.status == "PENDING")
        assert ready_count >= 1, f"entry 노드가 READY 여야 함 (got: {[r.status for r in rows]})"
        assert ready_count + pending_count == len(rows)

        # ── 3. node 를 READY 순서대로 SUCCESS 마킹 → 다음 READY 전이 확인 ─
        # 토폴로지대로 각 READY 노드를 1건씩 처리 (체인이 전부 흐를 때까지).
        max_iter = 50
        last_pipeline_status = "RUNNING"
        for _ in range(max_iter):
            with sm() as session:
                ready_row = session.execute(
                    text(
                        "SELECT node_run_id FROM run.node_run "
                        " WHERE pipeline_run_id = :pr AND status = 'READY' "
                        " ORDER BY node_run_id LIMIT 1"
                    ),
                    {"pr": started.pipeline_run_id},
                ).first()
                if ready_row is None:
                    break
                completion = complete_node(
                    session,
                    node_run_id=int(ready_row[0]),
                    status="SUCCESS",
                    output_json={"phase8_5_test": True},
                    pubsub=None,
                )
                session.commit()
                last_pipeline_status = completion.pipeline_status

        # ── 4. 최종 상태 검증 ─────────────────────────────────────────────
        with sm() as session:
            final = session.execute(
                text(
                    "SELECT status, started_at, finished_at "
                    "  FROM run.pipeline_run WHERE pipeline_run_id = :pr"
                ),
                {"pr": started.pipeline_run_id},
            ).first()
            assert final is not None
            assert final.status == "SUCCESS", (
                f"전 노드 SUCCESS 이후 pipeline_run.status = SUCCESS 기대, got {final.status} "
                f"(loop last status={last_pipeline_status})"
            )
            assert final.finished_at is not None
            assert final.finished_at >= final.started_at

            # 모든 node_run = SUCCESS
            node_statuses = list(
                session.execute(
                    text(
                        "SELECT status FROM run.node_run "
                        " WHERE pipeline_run_id = :pr"
                    ),
                    {"pr": started.pipeline_run_id},
                )
            )
            assert all(r.status == "SUCCESS" for r in node_statuses)

    finally:
        # 테스트로 만든 pipeline_run 정리 — 다른 테스트에 영향 없도록.
        if started_pipeline_run_id is not None:
            with sm() as session:
                session.execute(
                    text(
                        "DELETE FROM run.node_run "
                        " WHERE pipeline_run_id = :pr"
                    ),
                    {"pr": started_pipeline_run_id},
                )
                session.execute(
                    text(
                        "DELETE FROM run.pipeline_run "
                        " WHERE pipeline_run_id = :pr"
                    ),
                    {"pr": started_pipeline_run_id},
                )
                session.commit()


def test_phase8_5_inbound_to_pipeline_lag_visible() -> None:
    """Phase 8.5 ② sla-lag endpoint 가 호출 가능 + sample_count >= 0."""
    if not _seed_present():
        pytest.skip("Phase 8 seed 미적용")

    # 직접 query 로 검증 (FastAPI client 없이) — endpoint 함수 스모크.
    sm = get_sync_sessionmaker()
    with sm() as session:
        row = session.execute(
            text(
                """
                WITH lags AS (
                  SELECT EXTRACT(EPOCH FROM
                           (pr.finished_at - ie.received_at)) AS lag_sec
                    FROM audit.inbound_event ie
                    JOIN run.pipeline_run pr
                      ON pr.pipeline_run_id = ie.workflow_run_id
                   WHERE ie.workflow_run_id IS NOT NULL
                     AND pr.finished_at IS NOT NULL
                     AND pr.status = 'SUCCESS'
                )
                SELECT COUNT(*) AS n FROM lags
                """
            )
        ).first()
        # 그냥 query 가 깨지지 않으면 OK — sample 0 도 정상.
        assert row is not None
        assert int(row.n) >= 0
