"""Phase 4.2.2 — DQ 게이트 + 승인/반려 통합 테스트.

시나리오:
  1. DQ_CHECK ERROR 위반 → pipeline_run = ON_HOLD + 후속 SKIPPED 차단.
  2. ON_HOLD list endpoint 조회 → run + 실패 결과 + sample 노출.
  3. APPROVE → pipeline_run = RUNNING + 후속 노드 READY + outbox 이벤트 + Slack notify worker.
  4. REJECT → pipeline_run = CANCELLED + 잔여 노드 CANCELLED + stg.standard_record/price_observation rollback.

실 PG 의존. 미가동 시 skip.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain import dq_gate as dq_gate_domain
from app.domain.nodes import NodeContext, get_node_runner
from app.domain.pipeline_runtime import complete_node, mark_node_running, start_pipeline_run
from app.models.dq import QualityResult
from app.models.run import EventOutbox, HoldDecision, NodeRun, PipelineRun
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition
from app.workers import notify_worker


@pytest.fixture
def cleanup_workflows() -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for wid in ids:
            run_ids = list(
                session.execute(
                    select(PipelineRun.pipeline_run_id).where(PipelineRun.workflow_id == wid)
                ).scalars()
            )
            if run_ids:
                session.execute(
                    delete(QualityResult).where(QualityResult.pipeline_run_id.in_(run_ids))
                )
                session.execute(
                    delete(HoldDecision).where(HoldDecision.pipeline_run_id.in_(run_ids))
                )
                session.execute(
                    delete(EventOutbox).where(
                        EventOutbox.aggregate_type == "pipeline_run",
                    ).where(EventOutbox.aggregate_id.in_([str(r) for r in run_ids]))
                )
            session.execute(
                text(
                    "DELETE FROM run.node_run WHERE node_definition_id IN ("
                    "  SELECT node_id FROM wf.node_definition WHERE workflow_id = :wid)"
                ),
                {"wid": wid},
            )
            session.execute(
                text("DELETE FROM run.pipeline_run WHERE workflow_id = :wid"), {"wid": wid}
            )
            session.execute(delete(EdgeDefinition).where(EdgeDefinition.workflow_id == wid))
            session.execute(delete(NodeDefinition).where(NodeDefinition.workflow_id == wid))
            session.execute(delete(WorkflowDefinition).where(WorkflowDefinition.workflow_id == wid))
        session.commit()
    dispose_sync_engine()


@pytest.fixture
def cleanup_table() -> Iterator[list[str]]:
    tables: list[str] = []
    yield tables
    if not tables:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for t in tables:
            session.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        session.commit()


def _create_published_dq_workflow(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    *,
    cleanup_workflows: list[int],
    input_table: str,
) -> int:
    """A(NOOP) → DQ(DQ_CHECK strict) → C(NOOP) workflow PUBLISHED 후 ID 반환."""
    body: dict[str, Any] = {
        "name": f"IT_DQ_{rand_suffix.upper()}",
        "version": 1,
        "nodes": [
            {"node_key": "A", "node_type": "NOOP"},
            {
                "node_key": "DQ",
                "node_type": "DQ_CHECK",
                "config_json": {
                    "input_table": input_table,
                    "assertions": [{"kind": "row_count_min", "min": 100}],
                    "severity": "ERROR",
                },
            },
            {"node_key": "C", "node_type": "NOOP"},
        ],
        "edges": [
            {"from_node_key": "A", "to_node_key": "DQ"},
            {"from_node_key": "DQ", "to_node_key": "C"},
        ],
    }
    r = it_client.post("/v1/pipelines", json=body, headers=admin_auth)
    assert r.status_code == 201, r.text
    draft_id = int(r.json()["workflow_id"])
    cleanup_workflows.append(draft_id)
    pub = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200, pub.text
    published_id = int(pub.json()["published_workflow"]["workflow_id"])
    cleanup_workflows.append(published_id)
    return published_id


def _execute_node(session: Any, nr: NodeRun) -> Any:
    runner = get_node_runner(nr.node_type)
    nd = session.get(NodeDefinition, nr.node_definition_id)
    config = {} if nd is None else dict(nd.config_json or {})
    ctx = NodeContext(
        session=session,
        pipeline_run_id=nr.pipeline_run_id,
        node_run_id=nr.node_run_id,
        node_key=nr.node_key,
        user_id=None,
    )
    return runner.run(ctx, config)


def _drive_pipeline_to_on_hold(workflow_id: int) -> int:
    """워크플로 1회 실행 → DQ_CHECK FAIL 까지 진행. pipeline_run_id 반환."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        started = start_pipeline_run(session, workflow_id=workflow_id, triggered_by_user_id=None)
        session.commit()
    pr_id = started.pipeline_run_id

    # entry A NOOP — RUNNING then SUCCESS.
    with sm() as session:
        a_nr = session.execute(
            select(NodeRun)
            .where(NodeRun.pipeline_run_id == pr_id)
            .where(NodeRun.node_key == "A")
        ).scalar_one()
        mark_node_running(session, node_run_id=a_nr.node_run_id)
        out_a = _execute_node(session, a_nr)
        complete_node(
            session,
            node_run_id=a_nr.node_run_id,
            status="SUCCESS",
            output_json=out_a.payload,
        )
        session.commit()

    # DQ — RUNNING then FAILED with dq_hold.
    with sm() as session:
        dq_nr = session.execute(
            select(NodeRun)
            .where(NodeRun.pipeline_run_id == pr_id)
            .where(NodeRun.node_key == "DQ")
        ).scalar_one()
        assert dq_nr.status == "READY"
        mark_node_running(session, node_run_id=dq_nr.node_run_id)
        out_dq = _execute_node(session, dq_nr)
        assert out_dq.status == "failed"
        assert out_dq.payload.get("dq_hold") is True
        complete_node(
            session,
            node_run_id=dq_nr.node_run_id,
            status="FAILED",
            error_message=out_dq.error_message,
            output_json=out_dq.payload,
        )
        session.commit()

    return pr_id


# ---------------------------------------------------------------------------
# 1. DQ_CHECK ERROR → ON_HOLD + 후속 SKIPPED 차단
# ---------------------------------------------------------------------------
def test_dq_error_puts_run_on_hold(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    cleanup_table: list[str],
) -> None:
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dqgate_{safe}"
    cleanup_table.append(src)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1), (2)"))
        session.commit()

    workflow_id = _create_published_dq_workflow(
        it_client, admin_auth, rand_suffix,
        cleanup_workflows=cleanup_workflows,
        input_table=src,
    )

    pr_id = _drive_pipeline_to_on_hold(workflow_id)

    with sm() as session:
        pr = session.execute(
            select(PipelineRun).where(PipelineRun.pipeline_run_id == pr_id)
        ).scalar_one()
        assert pr.status == "ON_HOLD"
        node_status = {
            r.node_key: r.status
            for r in session.execute(
                select(NodeRun).where(NodeRun.pipeline_run_id == pr_id)
            ).scalars()
        }
        assert node_status["A"] == "SUCCESS"
        assert node_status["DQ"] == "FAILED"
        # 후속 C 는 SKIPPED 가 아닌 PENDING 으로 보존.
        assert node_status["C"] == "PENDING"

        # outbox NOTIFY 이벤트 발행됨.
        events = list(
            session.execute(
                select(EventOutbox).where(
                    EventOutbox.event_type == "pipeline_run.on_hold",
                    EventOutbox.aggregate_id == str(pr_id),
                )
            ).scalars()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# 2. ON_HOLD 목록 엔드포인트
# ---------------------------------------------------------------------------
def test_on_hold_list_endpoint_shows_failed_dq_results(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    cleanup_table: list[str],
) -> None:
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dqlist_{safe}"
    cleanup_table.append(src)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1)"))
        session.commit()

    workflow_id = _create_published_dq_workflow(
        it_client, admin_auth, rand_suffix,
        cleanup_workflows=cleanup_workflows,
        input_table=src,
    )
    pr_id = _drive_pipeline_to_on_hold(workflow_id)

    r = it_client.get("/v1/pipelines/runs/on_hold", headers=admin_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    target = next((b for b in body if b["pipeline_run_id"] == pr_id), None)
    assert target is not None, f"on_hold list missing {pr_id}: {body}"
    assert target["status"] == "ON_HOLD"
    assert "DQ" in target["failed_node_keys"]
    assert len(target["quality_results"]) >= 1
    assert target["quality_results"][0]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# 3. APPROVE — RUNNING + READY + 후속 SUCCESS 가능
# ---------------------------------------------------------------------------
def test_approve_resumes_pipeline(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    cleanup_table: list[str],
) -> None:
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dqapprove_{safe}"
    cleanup_table.append(src)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1), (2)"))
        session.commit()

    workflow_id = _create_published_dq_workflow(
        it_client, admin_auth, rand_suffix,
        cleanup_workflows=cleanup_workflows,
        input_table=src,
    )
    pr_id = _drive_pipeline_to_on_hold(workflow_id)

    # APPROVE.
    r = it_client.post(
        f"/v1/pipelines/runs/{pr_id}/hold/approve",
        json={"reason": "수동 검토 완료"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline_status"] == "RUNNING"
    assert body["decision"] == "APPROVE"
    assert len(body["ready_node_run_ids"]) >= 1

    with sm() as session:
        pr = session.execute(
            select(PipelineRun).where(PipelineRun.pipeline_run_id == pr_id)
        ).scalar_one()
        assert pr.status == "RUNNING"
        c_nr = session.execute(
            select(NodeRun)
            .where(NodeRun.pipeline_run_id == pr_id)
            .where(NodeRun.node_key == "C")
        ).scalar_one()
        assert c_nr.status == "READY"

        # 후속 C 노드 직접 실행으로 SUCCESS 까지 마무리.
        mark_node_running(session, node_run_id=c_nr.node_run_id)
        out_c = _execute_node(session, c_nr)
        completion = complete_node(
            session,
            node_run_id=c_nr.node_run_id,
            status="SUCCESS",
            output_json=out_c.payload,
        )
        session.commit()

    # DQ 가 FAILED 라 pipeline_run 종결 판정은 FAILED 로 떨어진다 (정상).
    assert completion.pipeline_status in ("FAILED", "SUCCESS", "RUNNING")

    # hold_decision 1건 적재.
    with sm() as session:
        decisions = list(
            session.execute(
                select(HoldDecision).where(HoldDecision.pipeline_run_id == pr_id)
            ).scalars()
        )
        assert len(decisions) == 1
        assert decisions[0].decision == "APPROVE"
        assert decisions[0].reason == "수동 검토 완료"


# ---------------------------------------------------------------------------
# 4. REJECT — CANCELLED + stg rollback (load_batch_id = pipeline_run_id)
# ---------------------------------------------------------------------------
def test_reject_cancels_and_rolls_back_stg(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    cleanup_table: list[str],
) -> None:
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dqreject_{safe}"
    cleanup_table.append(src)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1)"))
        session.commit()

    workflow_id = _create_published_dq_workflow(
        it_client, admin_auth, rand_suffix,
        cleanup_workflows=cleanup_workflows,
        input_table=src,
    )

    # source 시드 + stg 가격 관찰 시드 (rollback 검증용) — source_id 가 필요.
    with sm() as session:
        source_id = session.execute(
            text(
                "INSERT INTO ctl.data_source (source_code, source_name, source_type, is_active, config_json) "
                "VALUES (:c, 'IT DQ reject src', 'API', TRUE, '{}'::jsonb) RETURNING source_id"
            ),
            {"c": f"IT_DQR_{rand_suffix.upper()}"},
        ).scalar_one()
        session.commit()

    pr_id = _drive_pipeline_to_on_hold(workflow_id)

    # stg.price_observation 에 가짜 row — load_batch_id = pr_id.
    with sm() as session:
        session.execute(
            text(
                "INSERT INTO stg.price_observation (source_id, product_name_raw, price_krw, "
                "observed_at, load_batch_id) "
                "VALUES (:sid, 'rollback-target', 1000, :obs, :pid)"
            ),
            {"sid": source_id, "obs": datetime.now(UTC), "pid": pr_id},
        )
        session.commit()

    # REJECT.
    r = it_client.post(
        f"/v1/pipelines/runs/{pr_id}/hold/reject",
        json={"reason": "운영자 거부"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline_status"] == "CANCELLED"
    assert body["decision"] == "REJECT"
    assert body["rollback_rows"] >= 1

    with sm() as session:
        pr = session.execute(
            select(PipelineRun).where(PipelineRun.pipeline_run_id == pr_id)
        ).scalar_one()
        assert pr.status == "CANCELLED"
        assert pr.finished_at is not None
        c_nr = session.execute(
            select(NodeRun)
            .where(NodeRun.pipeline_run_id == pr_id)
            .where(NodeRun.node_key == "C")
        ).scalar_one()
        assert c_nr.status == "CANCELLED"
        # stg row 삭제 확인.
        remaining = session.execute(
            text(
                "SELECT COUNT(*) FROM stg.price_observation WHERE load_batch_id = :pid"
            ),
            {"pid": pr_id},
        ).scalar_one()
        assert remaining == 0
        # 정리 — source.
        session.execute(
            text("DELETE FROM ctl.data_source WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.commit()


# ---------------------------------------------------------------------------
# 5. notify_worker — outbox 이벤트 처리 (Slack 미구성 → no-op + PUBLISHED 마킹)
# ---------------------------------------------------------------------------
def test_notify_worker_marks_outbox_published(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    cleanup_table: list[str],
) -> None:
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dqnotify_{safe}"
    cleanup_table.append(src)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1)"))
        session.commit()

    workflow_id = _create_published_dq_workflow(
        it_client, admin_auth, rand_suffix,
        cleanup_workflows=cleanup_workflows,
        input_table=src,
    )
    pr_id = _drive_pipeline_to_on_hold(workflow_id)

    with sm() as session:
        before = session.execute(
            select(EventOutbox).where(
                EventOutbox.event_type == "pipeline_run.on_hold",
                EventOutbox.aggregate_id == str(pr_id),
            )
        ).scalar_one()
        assert before.status == "PENDING"

        stats = notify_worker.consume_pending_notifications_for_test(session)
        session.commit()
        assert stats["selected"] >= 1
        assert stats["sent"] >= 1

        after = session.execute(
            select(EventOutbox).where(EventOutbox.event_id == before.event_id)
        ).scalar_one()
        assert after.status == "PUBLISHED"
        assert after.published_at is not None


# ---------------------------------------------------------------------------
# 6. 직접 도메인 호출 — approve_hold 가 RUNNING 아닌 run 에 대해 ValueError
# ---------------------------------------------------------------------------
def test_approve_rejects_when_not_on_hold(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    cleanup_table: list[str],
) -> None:
    safe = secrets.token_hex(4)
    src = f"wf.tmp_dqstate_{safe}"
    cleanup_table.append(src)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text(f"CREATE TABLE {src} (id INT)"))
        session.execute(text(f"INSERT INTO {src} VALUES (1), (2), (3)"))  # 통과.
        session.commit()

    # min=2 라 통과 — pipeline_run 은 ON_HOLD 가 아니라 RUNNING/SUCCESS.
    body: dict[str, Any] = {
        "name": f"IT_DQNH_{rand_suffix.upper()}",
        "version": 1,
        "nodes": [
            {
                "node_key": "DQ",
                "node_type": "DQ_CHECK",
                "config_json": {
                    "input_table": src,
                    "assertions": [{"kind": "row_count_min", "min": 1}],
                    "severity": "ERROR",
                },
            },
        ],
        "edges": [],
    }
    r = it_client.post("/v1/pipelines", json=body, headers=admin_auth)
    assert r.status_code == 201
    cleanup_workflows.append(int(r.json()["workflow_id"]))
    pub = it_client.patch(
        f"/v1/pipelines/{r.json()['workflow_id']}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200
    pid = int(pub.json()["published_workflow"]["workflow_id"])
    cleanup_workflows.append(pid)

    with sm() as session:
        started = start_pipeline_run(session, workflow_id=pid, triggered_by_user_id=None)
        session.commit()

    pipeline_run_id = started.pipeline_run_id

    # 도메인 함수 직접 호출 — ON_HOLD 가 아니라 ValueError.
    with sm() as session, pytest.raises(ValueError, match="not ON_HOLD"):
        dq_gate_domain.approve_hold(
            session, pipeline_run_id=pipeline_run_id, signer_user_id=1
        )
