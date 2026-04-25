"""dead-letters API 통합 테스트.

DeadLetter 시드 → list filter / replay (실제 actor 등록된 케이스) / 권한 차단.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.run import DeadLetter


@pytest.fixture(scope="module", autouse=True)
def _force_stub_broker() -> Iterator[None]:
    """Replay 가 실 Redis 브로커에 enqueue 시도하지 않도록 StubBroker 강제."""
    prev = os.environ.get("APP_DRAMATIQ_STUB")
    os.environ["APP_DRAMATIQ_STUB"] = "1"
    yield
    if prev is None:
        os.environ.pop("APP_DRAMATIQ_STUB", None)
    else:
        os.environ["APP_DRAMATIQ_STUB"] = prev


@pytest.fixture
def cleanup_dl() -> Iterator[list[int]]:
    ids: list[int] = []
    yield ids
    if not ids:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(DeadLetter).where(DeadLetter.dl_id.in_(ids)))
        session.commit()
    dispose_sync_engine()


def _seed_dl(*, origin: str, replayed: bool = False) -> int:
    sm = get_sync_sessionmaker()
    with sm() as session:
        row = DeadLetter(
            origin=origin,
            payload_json={"args": [], "kwargs": {}, "message_id": "test-msg"},
            error_message="boom",
            stack_trace="Traceback...",
        )
        session.add(row)
        session.commit()
        if replayed:
            from datetime import UTC, datetime

            row.replayed_at = datetime.now(UTC)
            row.replayed_by = 1
            session.commit()
        return row.dl_id


def test_list_filters_only_unreplayed_by_default(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_dl: list[int],
) -> None:
    a = _seed_dl(origin="actor_a")
    b = _seed_dl(origin="actor_a", replayed=True)
    cleanup_dl.extend([a, b])

    r = it_client.get(
        "/v1/dead-letters",
        params={"origin": "actor_a", "limit": 100},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    ids = [item["dl_id"] for item in r.json()]
    assert a in ids
    assert b not in ids


def test_list_includes_replayed_when_requested(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_dl: list[int],
) -> None:
    a = _seed_dl(origin="actor_a", replayed=True)
    cleanup_dl.append(a)

    r = it_client.get(
        "/v1/dead-letters",
        params={"origin": "actor_a", "replayed": "true", "limit": 100},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    ids = [item["dl_id"] for item in r.json()]
    assert a in ids


def test_replay_marks_row_and_enqueues_message(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_dl: list[int],
) -> None:
    """등록된 actor (`publish_outbox_batch`) 로 시드 → replay 시 실제 send_with_options 호출."""
    dl_id = _seed_dl(origin="publish_outbox_batch")
    cleanup_dl.append(dl_id)

    r = it_client.post(f"/v1/dead-letters/{dl_id}/replay", headers=admin_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dl_id"] == dl_id
    assert body["origin"] == "publish_outbox_batch"
    assert body["enqueued_message_id"]
    assert body["replayed_at"]

    # 마킹 확인.
    r2 = it_client.get(
        "/v1/dead-letters",
        params={"origin": "publish_outbox_batch", "replayed": "true"},
        headers=admin_auth,
    )
    ids = [item["dl_id"] for item in r2.json()]
    assert dl_id in ids


def test_replay_unknown_actor_returns_4xx(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_dl: list[int],
) -> None:
    dl_id = _seed_dl(origin="actor_does_not_exist")
    cleanup_dl.append(dl_id)

    r = it_client.post(f"/v1/dead-letters/{dl_id}/replay", headers=admin_auth)
    assert r.status_code in (400, 422), r.text


def test_replay_already_replayed_returns_4xx(
    it_client: TestClient,
    admin_auth: dict[str, str],
    cleanup_dl: list[int],
) -> None:
    dl_id = _seed_dl(origin="publish_outbox_batch", replayed=True)
    cleanup_dl.append(dl_id)

    r = it_client.post(f"/v1/dead-letters/{dl_id}/replay", headers=admin_auth)
    assert r.status_code in (400, 422), r.text


def test_viewer_cannot_access_dead_letters(
    it_client: TestClient,
    viewer_auth: dict[str, str],
    cleanup_dl: list[int],
) -> None:
    dl_id = _seed_dl(origin="actor_a")
    cleanup_dl.append(dl_id)

    r = it_client.get("/v1/dead-letters", headers=viewer_auth)
    assert r.status_code == 403, r.text
