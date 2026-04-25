"""Phase 4.0.4 — Airflow internal trigger endpoint 통합 테스트.

POST /v1/pipelines/internal/runs:
  - X-Internal-Token 누락/오답 → 401
  - backend 에 token 미설정 → 503
  - PUBLISHED 만 통과, DRAFT/ARCHIVED → 422
  - 같은 (workflow_id, today) 가 RUNNING 이면 기존 ID 반환 (created=False)
  - 신규 트리거 → created=True
  - schedule_enabled=FALSE 라도 internal endpoint 자체는 거름 ✗ (cron polling 단계가 거름)

실 PG + 실 Redis 의존. monkey-patch 로 settings.airflow_internal_token 주입.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.config import get_settings
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.run import NodeRun, PipelineRun
from app.models.wf import (
    EdgeDefinition,
    NodeDefinition,
    PipelineRelease,
    WorkflowDefinition,
)

VALID_TOKEN = "it-airflow-token-supersecret"


@pytest.fixture(autouse=True)
def _set_internal_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Settings.airflow_internal_token 을 테스트 동안 강제 주입."""
    settings = get_settings()
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "airflow_internal_token", SecretStr(VALID_TOKEN))
    yield


@pytest.fixture
def cleanup_workflows() -> Iterator[list[str]]:
    """workflow name 단위로 release / runs / nodes / workflow 정리."""
    names: list[str] = []
    yield names
    if not names:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        wf_ids = list(
            session.execute(
                text("SELECT workflow_id FROM wf.workflow_definition WHERE name = ANY(:names)"),
                {"names": names},
            ).scalars()
        )
        if wf_ids:
            session.execute(
                delete(NodeRun).where(
                    NodeRun.node_definition_id.in_(
                        session.execute(
                            text(
                                "SELECT node_id FROM wf.node_definition WHERE workflow_id = ANY(:ids)"
                            ),
                            {"ids": wf_ids},
                        ).scalars()
                    )
                )
            )
            session.execute(delete(PipelineRun).where(PipelineRun.workflow_id.in_(wf_ids)))
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


def _create_published(
    it_client: TestClient, admin_auth: dict[str, str], name: str
) -> tuple[int, int]:
    """DRAFT 생성 + PUBLISH — (draft_id, published_id) 반환."""
    r = it_client.post(
        "/v1/pipelines",
        json={
            "name": name,
            "version": 1,
            "nodes": [{"node_key": "A", "node_type": "NOOP", "position_x": 0, "position_y": 0}],
            "edges": [],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    draft_id = int(r.json()["workflow_id"])
    pub = it_client.patch(
        f"/v1/pipelines/{draft_id}/status",
        json={"status": "PUBLISHED"},
        headers=admin_auth,
    )
    assert pub.status_code == 200, pub.text
    return draft_id, int(pub.json()["published_workflow"]["workflow_id"])


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------
def test_missing_token_401(it_client: TestClient) -> None:
    r = it_client.post("/v1/pipelines/internal/runs", json={"workflow_id": 1})
    assert r.status_code == 401, r.text


def test_wrong_token_401(it_client: TestClient) -> None:
    r = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": 1},
        headers={"X-Internal-Token": "wrong"},
    )
    assert r.status_code == 401


def test_backend_unconfigured_503(it_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings.airflow_internal_token 비어 있으면 503."""
    settings = get_settings()
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "airflow_internal_token", SecretStr(""))
    r = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": 1},
        headers={"X-Internal-Token": "anything"},
    )
    assert r.status_code == 503, r.text


# ---------------------------------------------------------------------------
# workflow status
# ---------------------------------------------------------------------------
def test_draft_workflow_rejected_422(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[str],
) -> None:
    """DRAFT 워크플로 trigger → 422."""
    name = f"IT_AIRFLOW_DRAFT_{rand_suffix.upper()}"
    cleanup_workflows.append(name)
    r = it_client.post(
        "/v1/pipelines",
        json={
            "name": name,
            "nodes": [{"node_key": "A", "node_type": "NOOP"}],
            "edges": [],
        },
        headers=admin_auth,
    )
    draft_id = int(r.json()["workflow_id"])

    trig = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": draft_id},
        headers={"X-Internal-Token": VALID_TOKEN},
    )
    assert trig.status_code == 422


def test_unknown_workflow_404(it_client: TestClient) -> None:
    r = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": 999_999_999},
        headers={"X-Internal-Token": VALID_TOKEN},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 멱등성 + 신규
# ---------------------------------------------------------------------------
def test_published_creates_new_run(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[str],
) -> None:
    name = f"IT_AIRFLOW_PUB_{rand_suffix.upper()}"
    cleanup_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    r = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": pub_id},
        headers={"X-Internal-Token": VALID_TOKEN},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["pipeline_run_id"] > 0
    assert body["status"] == "RUNNING"


def test_idempotent_same_day(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_workflows: list[str],
) -> None:
    """같은 (workflow_id, today) 에 두 번째 호출 → 같은 ID 반환 + created=False."""
    name = f"IT_AIRFLOW_IDEMP_{rand_suffix.upper()}"
    cleanup_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    first = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": pub_id},
        headers={"X-Internal-Token": VALID_TOKEN},
    )
    assert first.status_code == 200
    first_id = first.json()["pipeline_run_id"]
    assert first.json()["created"] is True

    second = it_client.post(
        "/v1/pipelines/internal/runs",
        json={"workflow_id": pub_id},
        headers={"X-Internal-Token": VALID_TOKEN},
    )
    assert second.status_code == 200
    assert second.json()["pipeline_run_id"] == first_id
    assert second.json()["created"] is False
