"""Phase 4.2.1 — Crowd 정식 검수 통합 테스트.

검증:
  1. lifecycle (단일 검수): assign → submit_review APPROVE → SINGLE 합의 + outbox 발행.
  2. 이중 검수 (priority>=8): 1번째 review → REVIEWING 유지 / 2번째 review 일치 →
     DOUBLE_AGREED + outbox.
  3. 충돌 (이중 검수 불일치): CONFLICT → ADMIN/APPROVER 가 resolve → CONFLICT_RESOLVED.
  4. 회귀 (Phase 2.2.10 legacy PATCH): /v1/crowd-tasks/{id}/status 가 새 도메인으로 위임.
  5. self-double-review 차단: 같은 reviewer 가 같은 task 두 번 review 시도 → 409.
  6. priority>=8 인데 reviewer 1명만 배정 시도 → 422.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.crowd import (
    Payout,
    Review,
    Task,
    TaskAssignment,
    TaskDecision,
)
from app.models.run import EventOutbox


@pytest.fixture
def cleanup_crowd_tasks() -> Iterator[list[int]]:
    """테스트가 만든 crowd_task_id 들을 정리. CASCADE 로 review/assignment/decision/payout 동시 삭제."""
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(
            delete(EventOutbox).where(
                EventOutbox.aggregate_type == "crowd.task",
                EventOutbox.aggregate_id.in_([str(i) for i in ids]),
            )
        )
        session.execute(
            delete(Payout).where(
                Payout.review_id.in_(
                    session.execute(
                        text("SELECT review_id FROM crowd.review WHERE crowd_task_id = ANY(:ids)"),
                        {"ids": ids},
                    ).scalars()
                )
            )
        )
        session.execute(delete(Review).where(Review.crowd_task_id.in_(ids)))
        session.execute(delete(TaskAssignment).where(TaskAssignment.crowd_task_id.in_(ids)))
        session.execute(delete(TaskDecision).where(TaskDecision.crowd_task_id.in_(ids)))
        session.execute(delete(Task).where(Task.crowd_task_id.in_(ids)))
        session.commit()
    dispose_sync_engine()


@pytest.fixture
def operator2_auth(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_users: list[str],
) -> dict[str, str]:
    """2번째 reviewer (이중 검수용). REVIEWER role 부여."""
    login_id = f"it_rev2_{rand_suffix.lower()}"
    password = f"pw-{rand_suffix}"

    r = it_client.post(
        "/v1/users",
        json={
            "login_id": login_id,
            "display_name": "Reviewer 2",
            "password": password,
            "role_codes": ["REVIEWER"],
        },
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    cleanup_users.append(login_id)

    login = it_client.post("/v1/auth/login", json={"login_id": login_id, "password": password})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_task(*, task_kind: str = "OCR_REVIEW", priority: int = 5) -> int:
    """직접 DB 에 crowd.task INSERT — 테스트용 helper."""
    sm = get_sync_sessionmaker()
    with sm() as session:
        task = Task(
            task_kind=task_kind,
            priority=priority,
            raw_object_id=12345,
            partition_date=date(2026, 4, 1),
            payload={"sample": "test"},
            status="PENDING",
            requires_double_review=priority >= 8,
        )
        session.add(task)
        session.flush()
        tid = task.crowd_task_id
        session.commit()
    return tid


def _admin_user_id(it_client: TestClient, admin_auth: dict[str, str]) -> int:
    """admin 의 user_id — /v1/users 에서 it_admin 찾기."""
    listed = it_client.get("/v1/users?is_active=true&limit=10", headers=admin_auth)
    assert listed.status_code == 200
    users = listed.json()
    me = next(u for u in users if u["login_id"] == "it_admin")
    return int(me["user_id"])


# ---------------------------------------------------------------------------
# 1. lifecycle 단일 검수
# ---------------------------------------------------------------------------
def test_single_review_lifecycle(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    tid = _create_task(priority=5)
    cleanup_crowd_tasks.append(tid)
    admin_id = _admin_user_id(it_client, admin_auth)

    # assign 1명
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/assign",
        json={"reviewer_ids": [admin_id]},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    # submit review APPROVE
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "APPROVE", "comment": "looks ok"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text

    # detail 확인 — status APPROVED + decision SINGLE + outbox 1건
    detail = it_client.get(f"/v1/crowd/tasks/{tid}", headers=admin_auth)
    body = detail.json()
    assert body["status"] == "APPROVED"
    assert body["decision"]["consensus_kind"] == "SINGLE"
    assert body["decision"]["final_decision"] == "APPROVE"
    assert len(body["reviews"]) == 1

    # outbox 발행 검증
    sm = get_sync_sessionmaker()
    with sm() as session:
        evt = session.execute(
            text(
                "SELECT event_type, payload_json FROM run.event_outbox "
                "WHERE aggregate_type = 'crowd.task' AND aggregate_id = :aid"
            ),
            {"aid": str(tid)},
        ).first()
    assert evt is not None
    assert evt.event_type == "crowd.task.decided"
    assert evt.payload_json["final_decision"] == "APPROVE"


# ---------------------------------------------------------------------------
# 2. 이중 검수 일치
# ---------------------------------------------------------------------------
def test_double_review_agreed(
    it_client: TestClient,
    admin_auth: dict[str, str],
    operator2_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    tid = _create_task(priority=9)  # 이중 검수 임계
    cleanup_crowd_tasks.append(tid)
    admin_id = _admin_user_id(it_client, admin_auth)

    # operator2 의 user_id 알아내기.
    me_listed = it_client.get("/v1/users?limit=20", headers=admin_auth)
    rev2_id = next(u["user_id"] for u in me_listed.json() if u["login_id"].startswith("it_rev2_"))

    # 두 명 배정.
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/assign",
        json={"reviewer_ids": [admin_id, rev2_id]},
        headers=admin_auth,
    )
    assert r.status_code == 200

    # 1번째 review (admin) — REVIEWING 유지.
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "APPROVE"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    detail = it_client.get(f"/v1/crowd/tasks/{tid}", headers=admin_auth).json()
    assert detail["status"] == "REVIEWING"
    assert detail["decision"] is None

    # 2번째 review (rev2) — APPROVE 일치 → DOUBLE_AGREED.
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "APPROVE"},
        headers=operator2_auth,
    )
    assert r.status_code == 200

    final = it_client.get(f"/v1/crowd/tasks/{tid}", headers=admin_auth).json()
    assert final["status"] == "APPROVED"
    assert final["decision"]["consensus_kind"] == "DOUBLE_AGREED"
    assert len(final["reviews"]) == 2


# ---------------------------------------------------------------------------
# 3. 이중 검수 불일치 → CONFLICT → resolve
# ---------------------------------------------------------------------------
def test_double_review_conflict_then_resolve(
    it_client: TestClient,
    admin_auth: dict[str, str],
    operator2_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    tid = _create_task(priority=10)
    cleanup_crowd_tasks.append(tid)
    admin_id = _admin_user_id(it_client, admin_auth)
    me_listed = it_client.get("/v1/users?limit=20", headers=admin_auth)
    rev2_id = next(u["user_id"] for u in me_listed.json() if u["login_id"].startswith("it_rev2_"))

    it_client.post(
        f"/v1/crowd/tasks/{tid}/assign",
        json={"reviewer_ids": [admin_id, rev2_id]},
        headers=admin_auth,
    )

    # admin: APPROVE / rev2: REJECT → CONFLICT.
    it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "APPROVE"},
        headers=admin_auth,
    )
    it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "REJECT"},
        headers=operator2_auth,
    )
    detail = it_client.get(f"/v1/crowd/tasks/{tid}", headers=admin_auth).json()
    assert detail["status"] == "CONFLICT"

    # admin (ADMIN role 보유) 가 resolve.
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/resolve",
        json={"final_decision": "APPROVE", "note": "after meeting"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["consensus_kind"] == "CONFLICT_RESOLVED"
    assert body["final_decision"] == "APPROVE"

    final = it_client.get(f"/v1/crowd/tasks/{tid}", headers=admin_auth).json()
    assert final["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# 4. legacy PATCH 위임
# ---------------------------------------------------------------------------
def test_legacy_patch_delegates_to_v4(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    """Phase 2.2.10 의 PATCH /v1/crowd-tasks/{id}/status 가 새 도메인으로 위임."""
    tid = _create_task(priority=5, task_kind="ocr_low_confidence")
    cleanup_crowd_tasks.append(tid)

    # legacy GET — view 통해 SELECT.
    r = it_client.get(f"/v1/crowd-tasks/{tid}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json()["status"] == "PENDING"

    # legacy PATCH APPROVED → 위임으로 새 도메인의 review row 생성.
    r = it_client.patch(
        f"/v1/crowd-tasks/{tid}/status",
        json={"status": "APPROVED"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"

    # crowd.review row 가 생겼는지 확인.
    sm = get_sync_sessionmaker()
    with sm() as session:
        review = session.execute(
            text("SELECT decision FROM crowd.review WHERE crowd_task_id = :tid LIMIT 1"),
            {"tid": tid},
        ).first()
    assert review is not None
    assert review.decision == "APPROVE"


# ---------------------------------------------------------------------------
# 5. 같은 reviewer 두 번 review 차단
# ---------------------------------------------------------------------------
def test_same_reviewer_twice_rejected(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    tid = _create_task(priority=5)
    cleanup_crowd_tasks.append(tid)

    # 첫 review.
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "APPROVE"},
        headers=admin_auth,
    )
    assert r.status_code == 200

    # 두 번째 같은 admin 의 review 시도 — task 가 이미 APPROVED 라 422 또는 409.
    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/review",
        json={"decision": "REJECT"},
        headers=admin_auth,
    )
    assert r.status_code in (409, 422), r.text


# ---------------------------------------------------------------------------
# 6. priority>=8 + reviewer 1명만 배정 → 422
# ---------------------------------------------------------------------------
def test_double_review_requires_two_reviewers(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_crowd_tasks: list[int],
) -> None:
    tid = _create_task(priority=8)
    cleanup_crowd_tasks.append(tid)
    admin_id = _admin_user_id(it_client, admin_auth)

    r = it_client.post(
        f"/v1/crowd/tasks/{tid}/assign",
        json={"reviewer_ids": [admin_id]},
        headers=admin_auth,
    )
    assert r.status_code == 422, r.text
