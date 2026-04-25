"""crowd-tasks API 통합 테스트.

CrowdTask 시드 → list filter / detail 컨텍스트 / 상태 전이 / 권한 차단.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.run import CrowdTask


@pytest.fixture
def cleanup_crowd_tasks() -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(CrowdTask).where(CrowdTask.crowd_task_id.in_(ids)))
        session.commit()
    dispose_sync_engine()


def _seed_task(*, reason: str, status: str = "PENDING") -> int:
    sm = get_sync_sessionmaker()
    with sm() as session:
        task = CrowdTask(
            raw_object_id=900_000 + secrets.randbelow(99_999),
            partition_date=date(2026, 4, 25),
            ocr_result_id=None,
            reason=reason,
            status=status,
            payload_json={"test": "it"},
        )
        session.add(task)
        session.commit()
        return task.crowd_task_id


def test_list_filters_by_status_and_reason(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    a = _seed_task(reason="ocr_low_confidence", status="PENDING")
    b = _seed_task(reason="std_low_confidence", status="PENDING")
    c = _seed_task(reason="ocr_low_confidence", status="APPROVED")
    cleanup_crowd_tasks.extend([a, b, c])

    r = it_client.get(
        "/v1/crowd-tasks",
        params={"status": "PENDING", "reason": "ocr_low_confidence", "limit": 100},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    ids = [item["crowd_task_id"] for item in r.json()]
    assert a in ids
    assert b not in ids  # 다른 reason
    assert c not in ids  # 다른 status


def test_get_detail_returns_payload_and_ocr_results(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    task_id = _seed_task(reason="ocr_low_confidence")
    cleanup_crowd_tasks.append(task_id)

    r = it_client.get(f"/v1/crowd-tasks/{task_id}", headers=admin_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["crowd_task_id"] == task_id
    assert body["reason"] == "ocr_low_confidence"
    # raw_object 미시드라 None 이 정상.
    assert body["raw_object_payload"] is None
    assert body["ocr_results"] == []


def test_status_transition_pending_to_approved(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    task_id = _seed_task(reason="std_low_confidence")
    cleanup_crowd_tasks.append(task_id)

    # PENDING → REVIEWING
    r1 = it_client.patch(
        f"/v1/crowd-tasks/{task_id}/status",
        json={"status": "REVIEWING"},
        headers=admin_auth,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "REVIEWING"
    assert r1.json()["reviewed_at"] is not None

    # REVIEWING → APPROVED
    r2 = it_client.patch(
        f"/v1/crowd-tasks/{task_id}/status",
        json={"status": "APPROVED"},
        headers=admin_auth,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "APPROVED"


def test_invalid_transition_returns_4xx(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    task_id = _seed_task(reason="ocr_low_confidence", status="APPROVED")
    cleanup_crowd_tasks.append(task_id)

    r = it_client.patch(
        f"/v1/crowd-tasks/{task_id}/status",
        json={"status": "REJECTED"},
        headers=admin_auth,
    )
    assert r.status_code in (400, 422), r.text


def test_viewer_cannot_access_crowd_tasks(
    it_client: TestClient,
    viewer_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    task_id = _seed_task(reason="ocr_low_confidence")
    cleanup_crowd_tasks.append(task_id)

    r = it_client.get("/v1/crowd-tasks", headers=viewer_auth)
    assert r.status_code == 403, r.text
