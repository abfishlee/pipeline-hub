"""Pipeline 스케줄 / Backfill / 재실행 / runs 검색 통합 테스트 (Phase 3.2.7).

실 PG 의존. cron 표현식 검증, 날짜 범위 backfill, 새 run 트리거, status/기간 필터.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.config import Settings
from app.core.errors import ValidationError
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain import pipeline_schedule as schedule_domain
from app.models.run import NodeRun, PipelineRun
from app.models.wf import (
    EdgeDefinition,
    NodeDefinition,
    PipelineRelease,
    WorkflowDefinition,
)


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@pytest.fixture
def cleanup_schedule_workflows(integration_settings: Settings) -> Iterator[list[str]]:
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
    """DRAFT 생성 후 PUBLISH — (draft_id, published_id) 반환."""
    r = it_client.post(
        "/v1/pipelines",
        json={
            "name": name,
            "version": 1,
            "nodes": [
                {"node_key": "A", "node_type": "NOOP"},
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
# 스케줄 메타
# ---------------------------------------------------------------------------
def test_schedule_set_and_validate(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_SCH_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    # 정상 cron
    r = it_client.patch(
        f"/v1/pipelines/{pub_id}/schedule",
        json={"cron": "0 5 * * *", "enabled": True},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schedule_cron"] == "0 5 * * *"
    assert body["schedule_enabled"] is True

    # 잘못된 cron — 422
    bad = it_client.patch(
        f"/v1/pipelines/{pub_id}/schedule",
        json={"cron": "not a cron", "enabled": True},
        headers=admin_auth,
    )
    assert bad.status_code == 422, bad.text

    # cron=null → enabled 자동 false
    cleared = it_client.patch(
        f"/v1/pipelines/{pub_id}/schedule",
        json={"cron": None, "enabled": True},
        headers=admin_auth,
    )
    assert cleared.status_code == 200
    assert cleared.json()["schedule_cron"] is None
    assert cleared.json()["schedule_enabled"] is False


def test_validate_cron_unit() -> None:
    """도메인 단위 — 5필드/유효 필드 정책 직접 검증."""
    assert schedule_domain.validate_cron("0 5 * * *") == "0 5 * * *"
    with pytest.raises(ValidationError):
        schedule_domain.validate_cron("0 5 * *")  # 4 fields
    with pytest.raises(ValidationError):
        schedule_domain.validate_cron("99 5 * * *")  # invalid minute


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
def test_backfill_creates_one_run_per_day(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_BF_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    start = date(2026, 4, 1)
    end = date(2026, 4, 3)
    r = it_client.post(
        f"/v1/pipelines/{pub_id}/backfill",
        json={"start_date": start.isoformat(), "end_date": end.isoformat()},
        headers=admin_auth,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert len(body["pipeline_run_ids"]) == 3
    assert body["run_dates"] == [
        "2026-04-01",
        "2026-04-02",
        "2026-04-03",
    ]

    # 두 번째 호출 — 같은 ID 멱등 반환
    r2 = it_client.post(
        f"/v1/pipelines/{pub_id}/backfill",
        json={"start_date": start.isoformat(), "end_date": end.isoformat()},
        headers=admin_auth,
    )
    assert r2.status_code == 202
    assert r2.json()["pipeline_run_ids"] == body["pipeline_run_ids"]


def test_backfill_rejects_start_after_end(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_BF_BAD_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    r = it_client.post(
        f"/v1/pipelines/{pub_id}/backfill",
        json={"start_date": "2026-04-10", "end_date": "2026-04-05"},
        headers=admin_auth,
    )
    assert r.status_code == 422


def test_backfill_draft_workflow_rejected(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    """DRAFT 워크플로 backfill → 409 (PUBLISHED 만 허용)."""
    name = f"IT_BF_DRAFT_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    r = it_client.post(
        "/v1/pipelines",
        json={
            "name": name,
            "version": 1,
            "nodes": [{"node_key": "A", "node_type": "NOOP"}],
            "edges": [],
        },
        headers=admin_auth,
    )
    draft_id = int(r.json()["workflow_id"])
    bf = it_client.post(
        f"/v1/pipelines/{draft_id}/backfill",
        json={"start_date": "2026-04-01", "end_date": "2026-04-01"},
        headers=admin_auth,
    )
    assert bf.status_code == 409


# ---------------------------------------------------------------------------
# Runs 검색
# ---------------------------------------------------------------------------
def test_search_runs_filters(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_RS_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    # backfill 로 5일치 생성
    bf = it_client.post(
        f"/v1/pipelines/{pub_id}/backfill",
        json={"start_date": "2026-03-15", "end_date": "2026-03-19"},
        headers=admin_auth,
    )
    assert bf.status_code == 202
    expected_ids = set(bf.json()["pipeline_run_ids"])

    # workflow_id 필터
    r1 = it_client.get(
        "/v1/pipelines/runs",
        params={"workflow_id": pub_id, "limit": 50},
        headers=admin_auth,
    )
    assert r1.status_code == 200
    got_ids = {row["pipeline_run_id"] for row in r1.json()}
    assert expected_ids.issubset(got_ids)

    # status 필터 — backfill 은 PENDING.
    r2 = it_client.get(
        "/v1/pipelines/runs",
        params={"workflow_id": pub_id, "status": "PENDING"},
        headers=admin_auth,
    )
    assert r2.status_code == 200
    assert all(row["status"] == "PENDING" for row in r2.json())

    # 기간 필터 — 03-16 ~ 03-18 (3일)
    r3 = it_client.get(
        "/v1/pipelines/runs",
        params={
            "workflow_id": pub_id,
            "from": "2026-03-16",
            "to": "2026-03-18",
        },
        headers=admin_auth,
    )
    assert r3.status_code == 200
    dates = {row["run_date"] for row in r3.json()}
    assert dates == {"2026-03-16", "2026-03-17", "2026-03-18"}


# ---------------------------------------------------------------------------
# 재실행 — 전체/특정 노드부터
# ---------------------------------------------------------------------------
def test_restart_full_run_creates_new_run_with_entry_ready(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_RST_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    run = it_client.post(f"/v1/pipelines/{pub_id}/runs", headers=admin_auth)
    assert run.status_code == 202, run.text
    original_run_id = int(run.json()["pipeline_run_id"])

    rs = it_client.post(
        f"/v1/pipelines/runs/{original_run_id}/restart",
        json={"from_node_key": None},
        headers=admin_auth,
    )
    assert rs.status_code == 202, rs.text
    body = rs.json()
    assert body["new_pipeline_run_id"] != original_run_id
    assert body["seeded_success_node_keys"] == []
    assert len(body["ready_node_run_ids"]) >= 1  # entry node 가 READY

    # node_run 상세 확인 — entry 'A' 만 READY, B/C 는 PENDING
    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = list(
            session.execute(
                text(
                    "SELECT node_key, status FROM run.node_run "
                    "WHERE pipeline_run_id = :pr ORDER BY node_key"
                ),
                {"pr": body["new_pipeline_run_id"]},
            )
        )
    statuses = {r.node_key: r.status for r in rows}
    assert statuses["A"] == "READY"
    assert statuses["B"] == "PENDING"
    assert statuses["C"] == "PENDING"


def test_restart_from_specific_node_seeds_ancestors_success(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_RST_NODE_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)

    run = it_client.post(f"/v1/pipelines/{pub_id}/runs", headers=admin_auth)
    original_run_id = int(run.json()["pipeline_run_id"])

    rs = it_client.post(
        f"/v1/pipelines/runs/{original_run_id}/restart",
        json={"from_node_key": "B"},
        headers=admin_auth,
    )
    assert rs.status_code == 202, rs.text
    body = rs.json()
    # B 의 ancestor 는 A — A 가 SUCCESS 시드, B 는 READY, C 는 PENDING
    assert body["seeded_success_node_keys"] == ["A"]

    sm = get_sync_sessionmaker()
    with sm() as session:
        rows = list(
            session.execute(
                text(
                    "SELECT node_key, status FROM run.node_run "
                    "WHERE pipeline_run_id = :pr ORDER BY node_key"
                ),
                {"pr": body["new_pipeline_run_id"]},
            )
        )
    statuses = {r.node_key: r.status for r in rows}
    assert statuses["A"] == "SUCCESS"
    assert statuses["B"] == "READY"
    assert statuses["C"] == "PENDING"


def test_restart_unknown_node_key_rejected(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_schedule_workflows: list[str],
) -> None:
    name = f"IT_RST_BAD_{rand_suffix.upper()}"
    cleanup_schedule_workflows.append(name)
    _, pub_id = _create_published(it_client, admin_auth, name)
    run = it_client.post(f"/v1/pipelines/{pub_id}/runs", headers=admin_auth)
    rid = int(run.json()["pipeline_run_id"])

    rs = it_client.post(
        f"/v1/pipelines/runs/{rid}/restart",
        json={"from_node_key": "NONEXISTENT"},
        headers=admin_auth,
    )
    assert rs.status_code == 422
