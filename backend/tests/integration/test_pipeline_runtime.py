"""Pipeline Runtime 통합 테스트 (Phase 3.2.1).

NOOP 3-노드 DAG 를 만들고 실행 — pipeline_run + node_run 적재 + 토폴로지 정렬 +
Pub/Sub 이벤트 발행 + cycle 거부 + DRAFT 상태 강제.

실 PG + 실 Redis 의존. 미가동 시 skip.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.config import get_settings
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.pipeline_runtime import (
    complete_node,
    start_pipeline_run,
)
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition


@pytest.fixture(scope="module")
def _redis_or_skip() -> Iterator[redis_lib.Redis]:
    settings = get_settings()
    client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:
        pytest.skip(f"redis unreachable: {exc}")
    yield client
    client.close()


@pytest.fixture
def cleanup_workflows() -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for wid in ids:
            session.execute(
                text(
                    "DELETE FROM run.node_run WHERE node_definition_id IN (SELECT node_id FROM wf.node_definition WHERE workflow_id = :wid)"
                ),
                {"wid": wid},
            )
            session.execute(
                text("DELETE FROM run.pipeline_run WHERE workflow_id = :wid"), {"wid": wid}
            )
        session.execute(delete(EdgeDefinition).where(EdgeDefinition.workflow_id.in_(ids)))
        session.execute(delete(NodeDefinition).where(NodeDefinition.workflow_id.in_(ids)))
        session.execute(delete(WorkflowDefinition).where(WorkflowDefinition.workflow_id.in_(ids)))
        session.commit()
    dispose_sync_engine()


def _create_three_noop_workflow(
    it_client: TestClient, admin_auth: dict[str, str], rand_suffix: str
) -> int:
    """A → B → C 직선 NOOP 워크플로 생성. workflow_id 반환."""
    name = f"IT_PR_{rand_suffix.upper()}"
    body = {
        "name": name,
        "version": 1,
        "description": "phase 3 IT — 3 NOOP nodes",
        "nodes": [
            {"node_key": "A", "node_type": "NOOP", "position_x": 0, "position_y": 0},
            {"node_key": "B", "node_type": "NOOP", "position_x": 100, "position_y": 0},
            {"node_key": "C", "node_type": "NOOP", "position_x": 200, "position_y": 0},
        ],
        "edges": [
            {"from_node_key": "A", "to_node_key": "B"},
            {"from_node_key": "B", "to_node_key": "C"},
        ],
    }
    r = it_client.post("/v1/pipelines", json=body, headers=admin_auth)
    assert r.status_code == 201, r.text
    return int(r.json()["workflow_id"])


# ---------------------------------------------------------------------------
# 1. CRUD 흐름 — DRAFT 생성 / PATCH / PUBLISH 전이
# ---------------------------------------------------------------------------
def test_create_workflow_in_draft_then_publish(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
) -> None:
    workflow_id = _create_three_noop_workflow(it_client, admin_auth, rand_suffix)
    cleanup_workflows.append(workflow_id)

    detail = it_client.get(f"/v1/pipelines/{workflow_id}", headers=admin_auth)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "DRAFT"
    assert len(body["nodes"]) == 3
    assert len(body["edges"]) == 2

    # PATCH — 노드 추가 가능 (DRAFT)
    patch = it_client.patch(
        f"/v1/pipelines/{workflow_id}",
        json={
            "nodes": body["nodes"]  # 그대로 유지하면서 description 만 바꿔도 OK 지만
            # nodes 가 None 이 아닌 케이스 검증.
            and [{"node_key": n["node_key"], "node_type": n["node_type"]} for n in body["nodes"]],
            "edges": [
                {"from_node_key": "A", "to_node_key": "B"},
                {"from_node_key": "B", "to_node_key": "C"},
            ],
            "description": "patched",
        },
        headers=admin_auth,
    )
    assert patch.status_code == 200, patch.text

    # PUBLISH 전이 — Phase 3.2.6: 새 PUBLISHED 워크플로 row 생성됨.
    pub = it_client.patch(
        f"/v1/pipelines/{workflow_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["workflow"]["status"] == "DRAFT"  # 원본은 DRAFT 유지
    assert body["published_workflow"]["status"] == "PUBLISHED"
    assert body["published_workflow"]["version"] >= 2  # version_no 증가
    assert body["release"] is not None
    cleanup_workflows.append(int(body["published_workflow"]["workflow_id"]))

    # PUBLISHED 워크플로 PATCH 시도 → 4xx
    published_id = int(body["published_workflow"]["workflow_id"])
    bad = it_client.patch(
        f"/v1/pipelines/{published_id}",
        json={"description": "should fail"},
        headers=admin_auth,
    )
    assert bad.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 2. cycle 워크플로 — start_pipeline_run 거부
# ---------------------------------------------------------------------------
def test_cycle_workflow_rejected_at_start(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
) -> None:
    name = f"IT_CYCLE_{rand_suffix.upper()}"
    body = {
        "name": name,
        "version": 1,
        "nodes": [
            {"node_key": "A", "node_type": "NOOP"},
            {"node_key": "B", "node_type": "NOOP"},
        ],
        "edges": [
            {"from_node_key": "A", "to_node_key": "B"},
            {"from_node_key": "B", "to_node_key": "A"},  # cycle
        ],
    }
    r = it_client.post("/v1/pipelines", json=body, headers=admin_auth)
    assert r.status_code == 201
    workflow_id = int(r.json()["workflow_id"])
    cleanup_workflows.append(workflow_id)

    # PUBLISH 까지는 통과 (메타 검증만 — cycle 검출은 실행 시점). Phase 3.2.6 부터
    # PUBLISH 는 새 워크플로 row 를 만들고, run 트리거는 그 새 ID 로 실행해야 함.
    pub = it_client.patch(
        f"/v1/pipelines/{workflow_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200
    published_id = int(pub.json()["published_workflow"]["workflow_id"])
    cleanup_workflows.append(published_id)

    # 실행 트리거 → cycle 검출 → 422
    run = it_client.post(f"/v1/pipelines/{published_id}/runs", headers=admin_auth)
    assert run.status_code in (400, 422), run.text


# ---------------------------------------------------------------------------
# 3. 3-NOOP DAG 토폴로지 진행 — sync 도메인 직접 호출 (worker stub)
# ---------------------------------------------------------------------------
def test_topology_progresses_when_nodes_succeed(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    _redis_or_skip: redis_lib.Redis,
) -> None:
    workflow_id = _create_three_noop_workflow(it_client, admin_auth, rand_suffix)
    cleanup_workflows.append(workflow_id)
    # PUBLISH — Phase 3.2.6: published_workflow 의 새 ID 로 후속 실행.
    pub = it_client.patch(
        f"/v1/pipelines/{workflow_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200
    published_id = int(pub.json()["published_workflow"]["workflow_id"])
    cleanup_workflows.append(published_id)

    # PUBSUB 구독 — 노드 상태 이벤트 수집.
    pubsub = _redis_or_skip.pubsub()

    # API 로 실행 트리거.
    run = it_client.post(f"/v1/pipelines/{published_id}/runs", headers=admin_auth)
    assert run.status_code == 202, run.text
    pipeline_run_id = int(run.json()["pipeline_run_id"])
    pubsub.subscribe(f"pipeline:{pipeline_run_id}")

    # node_run 3건 적재 확인 + entry 1건이 READY (worker 가 없으므로 그 상태 유지).
    sm = get_sync_sessionmaker()
    with sm() as session:
        node_runs = list(
            session.execute(
                text(
                    "SELECT node_run_id, node_key, status FROM run.node_run "
                    "WHERE pipeline_run_id = :pr ORDER BY node_run_id"
                ),
                {"pr": pipeline_run_id},
            )
        )
        assert len(node_runs) == 3
        statuses = {r.node_key: r.status for r in node_runs}
        assert statuses["A"] == "READY"
        assert statuses["B"] == "PENDING"
        assert statuses["C"] == "PENDING"
        node_run_ids = {r.node_key: r.node_run_id for r in node_runs}

    # 도메인 직접 호출로 노드를 SUCCESS 마킹 — worker actor 의 효과를 시뮬.
    from app.core.events import RedisPubSub

    pub_sender = RedisPubSub(_redis_or_skip)
    with sm() as session:
        c = complete_node(
            session,
            node_run_id=node_run_ids["A"],
            status="SUCCESS",
            pubsub=pub_sender,
        )
        session.commit()
    assert c.pipeline_status == "RUNNING"
    assert len(c.next_ready_node_run_ids) == 1  # B 가 READY 됨

    with sm() as session:
        complete_node(
            session,
            node_run_id=node_run_ids["B"],
            status="SUCCESS",
            pubsub=pub_sender,
        )
        session.commit()

    with sm() as session:
        c3 = complete_node(
            session,
            node_run_id=node_run_ids["C"],
            status="SUCCESS",
            pubsub=pub_sender,
        )
        session.commit()
    assert c3.pipeline_status == "SUCCESS"

    # API 상세 — pipeline 상태 SUCCESS, 모든 node 가 SUCCESS.
    detail = it_client.get(f"/v1/pipelines/runs/{pipeline_run_id}", headers=admin_auth)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "SUCCESS"
    assert all(n["status"] == "SUCCESS" for n in body["node_runs"])

    # Pub/Sub 메시지 1개 이상 도착 (대기 100ms 안에).
    received: list[dict] = []
    deadline_loops = 20
    while deadline_loops > 0:
        msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if msg is None:
            deadline_loops -= 1
            continue
        if msg.get("type") == "message":
            received.append(json.loads(msg["data"]))
    pubsub.close()
    assert any(m.get("status") == "SUCCESS" for m in received)


# ---------------------------------------------------------------------------
# 4. cancel — RUNNING 파이프라인을 취소
# ---------------------------------------------------------------------------
def test_cancel_pipeline_run_marks_all_nonterminal_as_cancelled(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[int],
    _redis_or_skip: redis_lib.Redis,
) -> None:
    workflow_id = _create_three_noop_workflow(it_client, admin_auth, rand_suffix)
    cleanup_workflows.append(workflow_id)
    pub = it_client.patch(
        f"/v1/pipelines/{workflow_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    published_id = int(pub.json()["published_workflow"]["workflow_id"])
    cleanup_workflows.append(published_id)

    # 도메인 직접 — start 만 호출. PUBLISHED 워크플로 ID 로.
    sm = get_sync_sessionmaker()
    with sm() as session:
        started = start_pipeline_run(
            session,
            workflow_id=published_id,
            triggered_by_user_id=1,
        )
        session.commit()

    # 도메인 cancel.
    from app.domain.pipeline_runtime import cancel_pipeline_run

    with sm() as session:
        pr = cancel_pipeline_run(
            session,
            pipeline_run_id=started.pipeline_run_id,
            run_date=started.run_date,
            user_id=1,
        )
        session.commit()
    assert pr.status == "CANCELLED"

    with sm() as session:
        siblings = list(
            session.execute(
                text("SELECT status FROM run.node_run WHERE pipeline_run_id = :pr"),
                {"pr": started.pipeline_run_id},
            )
        )
    assert all(r.status in ("CANCELLED", "SUCCESS", "FAILED", "SKIPPED") for r in siblings)
    assert any(r.status == "CANCELLED" for r in siblings)


# ---------------------------------------------------------------------------
# 5. 권한 — VIEWER 는 GET 도 차단 (전체 라우터가 OPERATOR+)
# ---------------------------------------------------------------------------
def test_viewer_cannot_access_pipelines(
    it_client: TestClient,
    viewer_auth: dict[str, str],
) -> None:
    r = it_client.get("/v1/pipelines", headers=viewer_auth)
    assert r.status_code == 403
