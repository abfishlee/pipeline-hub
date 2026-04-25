"""Pipeline release / diff 통합 테스트 (Phase 3.2.6).

PUBLISHED 전환 → 새 워크플로 row + version_no auto-inc + wf.pipeline_release 적재 +
diff 응답. 같은 name 두 번째 publish 시 version_no=3.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.wf import (
    EdgeDefinition,
    NodeDefinition,
    PipelineRelease,
    WorkflowDefinition,
)


@pytest.fixture
def cleanup_release_workflows() -> Iterator[list[str]]:
    """workflow name 단위로 정리 (PUBLISHED rows 가 여러 개 생성되므로 ID 추적이 부담)."""
    names: list[str] = []
    yield names
    if not names:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        # release / nodes / edges / workflow 순서 — wf.pipeline_release 가 released_workflow_id
        # ondelete CASCADE 라 workflow 삭제로 자동 정리되지만 source_workflow_id 도 풀어줘야
        # 한다 (SET NULL).
        wf_ids = list(
            session.execute(
                text("SELECT workflow_id FROM wf.workflow_definition WHERE name = ANY(:names)"),
                {"names": names},
            ).scalars()
        )
        if wf_ids:
            session.execute(
                text(
                    "DELETE FROM run.node_run WHERE node_definition_id IN ("
                    " SELECT node_id FROM wf.node_definition WHERE workflow_id = ANY(:ids))"
                ),
                {"ids": wf_ids},
            )
            session.execute(
                text("DELETE FROM run.pipeline_run WHERE workflow_id = ANY(:ids)"),
                {"ids": wf_ids},
            )
            session.execute(
                delete(PipelineRelease).where(PipelineRelease.released_workflow_id.in_(wf_ids))
            )
            session.execute(delete(EdgeDefinition).where(EdgeDefinition.workflow_id.in_(wf_ids)))
            session.execute(delete(NodeDefinition).where(NodeDefinition.workflow_id.in_(wf_ids)))
            session.execute(
                delete(WorkflowDefinition).where(WorkflowDefinition.workflow_id.in_(wf_ids))
            )
            session.commit()
    dispose_sync_engine()


def _create_workflow(it_client: TestClient, admin_auth: dict[str, str], name: str) -> int:
    r = it_client.post(
        "/v1/pipelines",
        json={
            "name": name,
            "version": 1,
            "nodes": [
                {"node_key": "A", "node_type": "NOOP", "position_x": 0, "position_y": 0},
                {"node_key": "B", "node_type": "NOOP", "position_x": 100, "position_y": 0},
            ],
            "edges": [{"from_node_key": "A", "to_node_key": "B"}],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["workflow_id"])


def test_publish_creates_new_workflow_with_incremented_version(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_release_workflows: list[str],
) -> None:
    name = f"IT_REL_{rand_suffix.upper()}"
    cleanup_release_workflows.append(name)
    draft_id = _create_workflow(it_client, admin_auth, name)

    pub = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200, pub.text
    body = pub.json()
    # 원본 DRAFT 는 그대로
    assert body["workflow"]["status"] == "DRAFT"
    assert body["workflow"]["workflow_id"] == draft_id
    # 새 PUBLISHED 워크플로
    pub_wf = body["published_workflow"]
    assert pub_wf["status"] == "PUBLISHED"
    assert pub_wf["version"] == 2
    assert pub_wf["workflow_id"] != draft_id
    # release row
    rel = body["release"]
    assert rel is not None
    assert rel["workflow_name"] == name
    assert rel["version_no"] == 2
    assert rel["source_workflow_id"] == draft_id
    assert rel["released_workflow_id"] == pub_wf["workflow_id"]
    # 첫 publish 라 prev 가 없으므로 모든 노드가 added 로 잡힘.
    assert "A" in rel["change_summary"]["added"]
    assert "B" in rel["change_summary"]["added"]


def test_second_publish_increments_version_and_diffs_against_prev(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_release_workflows: list[str],
) -> None:
    name = f"IT_REL2_{rand_suffix.upper()}"
    cleanup_release_workflows.append(name)
    draft_id = _create_workflow(it_client, admin_auth, name)

    # 1st publish (v2)
    r1 = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert r1.status_code == 200
    pub1 = r1.json()["published_workflow"]
    assert pub1["version"] == 2

    # DRAFT 를 변경 — B 의 config 변경 + C 추가 + 엣지 B->C 추가.
    patch = it_client.patch(
        f"/v1/pipelines/{draft_id}",
        json={
            "nodes": [
                {"node_key": "A", "node_type": "NOOP"},
                {
                    "node_key": "B",
                    "node_type": "NOOP",
                    "config_json": {"note": "changed"},
                },
                {"node_key": "C", "node_type": "NOOP"},
            ],
            "edges": [
                {"from_node_key": "A", "to_node_key": "B"},
                {"from_node_key": "B", "to_node_key": "C"},
            ],
        },
        headers=admin_auth,
    )
    assert patch.status_code == 200, patch.text

    # 2nd publish (v3) — diff 가 의미 있게 잡혀야 함.
    r2 = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    pub2 = body2["published_workflow"]
    assert pub2["version"] == 3
    assert pub2["workflow_id"] != pub1["workflow_id"]
    summary = body2["release"]["change_summary"]
    assert "C" in summary["added"]
    assert "B" in summary["changed"]
    assert "A->B" in summary["edges_added"] or "A->B" not in summary["edges_removed"]
    assert "B->C" in summary["edges_added"]


def test_publish_empty_workflow_rejected(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_release_workflows: list[str],
) -> None:
    """노드 0개 워크플로 publish → ConflictError 409."""
    name = f"IT_REL_EMPTY_{rand_suffix.upper()}"
    cleanup_release_workflows.append(name)
    # 노드 1개로 일단 생성(=API min 요구 충족) 후 PATCH 로 비움.
    r = it_client.post(
        "/v1/pipelines",
        json={
            "name": name,
            "nodes": [{"node_key": "A", "node_type": "NOOP"}],
            "edges": [],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201
    draft_id = int(r.json()["workflow_id"])

    # 노드를 모두 제거.
    p = it_client.patch(
        f"/v1/pipelines/{draft_id}",
        json={"nodes": [], "edges": []},
        headers=admin_auth,
    )
    assert p.status_code == 200

    pub = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 409, pub.text


def test_diff_endpoint_against_published(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_release_workflows: list[str],
) -> None:
    name = f"IT_DIFF_{rand_suffix.upper()}"
    cleanup_release_workflows.append(name)
    draft_id = _create_workflow(it_client, admin_auth, name)

    pub = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200
    pub_id = int(pub.json()["published_workflow"]["workflow_id"])

    # DRAFT 변경: 노드 C 추가 + 엣지 추가, A 의 config 변경.
    patch = it_client.patch(
        f"/v1/pipelines/{draft_id}",
        json={
            "nodes": [
                {"node_key": "A", "node_type": "NOOP", "config_json": {"x": 1}},
                {"node_key": "B", "node_type": "NOOP"},
                {"node_key": "C", "node_type": "NOOP"},
            ],
            "edges": [
                {"from_node_key": "A", "to_node_key": "B"},
                {"from_node_key": "B", "to_node_key": "C"},
            ],
        },
        headers=admin_auth,
    )
    assert patch.status_code == 200

    diff = it_client.get(
        f"/v1/pipelines/{draft_id}/diff",
        params={"against": pub_id},
        headers=admin_auth,
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["before_workflow_id"] == pub_id
    assert body["after_workflow_id"] == draft_id
    added_keys = [n["node_key"] for n in body["nodes_added"]]
    changed_keys = [n["node_key"] for n in body["nodes_changed"]]
    assert "C" in added_keys
    assert "A" in changed_keys
    edges_added = [(e["from_node_key"], e["to_node_key"]) for e in body["edges_added"]]
    assert ("B", "C") in edges_added


def test_releases_listing_filtered_by_name(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_release_workflows: list[str],
) -> None:
    name = f"IT_LIST_{rand_suffix.upper()}"
    cleanup_release_workflows.append(name)
    draft_id = _create_workflow(it_client, admin_auth, name)
    it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )

    rows = it_client.get(
        "/v1/pipelines/releases",
        params={"name": name},
        headers=admin_auth,
    )
    assert rows.status_code == 200
    body = rows.json()
    assert len(body) == 1
    assert body[0]["workflow_name"] == name
    assert body[0]["version_no"] == 2

    # 상세 — snapshot 동봉
    rel_id = int(body[0]["release_id"])
    detail = it_client.get(f"/v1/pipelines/releases/{rel_id}", headers=admin_auth)
    assert detail.status_code == 200
    d = detail.json()
    assert len(d["nodes_snapshot"]) == 2
    assert len(d["edges_snapshot"]) == 1
