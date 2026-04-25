"""SSE 라우터 통합 테스트 (Phase 3.2.3).

실 PG + 실 Redis 의존. 미가동 시 skip.

검증:
  - pipeline_run 시드 → GET 401 / 403 / 404 / 200 분기
  - GET 200 시 `data: {...}` 라인 1건 이상 수신 후 close
  - 권한 없는 사용자 (VIEWER) 403
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.config import get_settings
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.run import NodeRun, PipelineRun
from app.models.wf import WorkflowDefinition


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
def seeded_pipeline_run() -> Iterator[tuple[int, int]]:
    """workflow + pipeline_run 1건 시드. (workflow_id, pipeline_run_id) 반환."""
    sm = get_sync_sessionmaker()
    name = f"IT_SSE_{secrets.token_hex(4).upper()}"
    today = date.today()
    workflow_id: int
    pipeline_run_id: int

    with sm() as session:
        wf = WorkflowDefinition(
            name=name,
            version=1,
            status="PUBLISHED",
            published_at=datetime.now(UTC),
        )
        session.add(wf)
        session.commit()
        workflow_id = wf.workflow_id

        pr = PipelineRun(
            workflow_id=workflow_id,
            run_date=today,
            status="RUNNING",
            started_at=datetime.now(UTC),
        )
        session.add(pr)
        session.commit()
        pipeline_run_id = pr.pipeline_run_id

    yield workflow_id, pipeline_run_id

    with sm() as session:
        session.execute(
            text("DELETE FROM run.node_run WHERE pipeline_run_id = :pr"),
            {"pr": pipeline_run_id},
        )
        session.execute(
            text("DELETE FROM run.pipeline_run WHERE pipeline_run_id = :pr AND run_date = :d"),
            {"pr": pipeline_run_id, "d": today},
        )
        session.execute(
            delete(WorkflowDefinition).where(WorkflowDefinition.workflow_id == workflow_id)
        )
        session.commit()
    dispose_sync_engine()


def test_sse_endpoint_unauthenticated_returns_401(
    it_client: TestClient,
    seeded_pipeline_run: tuple[int, int],
) -> None:
    _, pipeline_run_id = seeded_pipeline_run
    r = it_client.get(f"/v1/pipelines/runs/{pipeline_run_id}/events")
    assert r.status_code in (401, 403)


def test_sse_endpoint_viewer_forbidden(
    it_client: TestClient,
    viewer_auth: dict[str, str],
    seeded_pipeline_run: tuple[int, int],
) -> None:
    _, pipeline_run_id = seeded_pipeline_run
    r = it_client.get(f"/v1/pipelines/runs/{pipeline_run_id}/events", headers=viewer_auth)
    assert r.status_code == 403


def test_sse_endpoint_unknown_run_returns_404(
    it_client: TestClient,
    admin_auth: dict[str, str],
) -> None:
    r = it_client.get("/v1/pipelines/runs/999999999/events", headers=admin_auth)
    assert r.status_code == 404


def test_sse_endpoint_streams_open_event_then_published_message(
    it_client: TestClient,
    admin_auth: dict[str, str],
    seeded_pipeline_run: tuple[int, int],
    _redis_or_skip: redis_lib.Redis,
) -> None:
    workflow_id, pipeline_run_id = seeded_pipeline_run
    channel = f"pipeline:{pipeline_run_id}"

    # 별도 스레드에서 0.5s 후 publish — TestClient stream 이 메시지를 흘러야 함.
    def _publish_after_delay() -> None:
        time.sleep(0.5)
        _redis_or_skip.publish(
            channel,
            json.dumps(
                {
                    "pipeline_run_id": pipeline_run_id,
                    "run_date": date.today().isoformat(),
                    "workflow_id": workflow_id,
                    "node_run_id": 1,
                    "node_key": "A",
                    "node_type": "NOOP",
                    "status": "SUCCESS",
                    "attempt_no": 1,
                    "error_message": None,
                }
            ),
        )

    t = threading.Thread(target=_publish_after_delay, daemon=True)
    t.start()

    received_lines: list[str] = []
    deadline = time.time() + 5.0
    with it_client.stream(
        "GET", f"/v1/pipelines/runs/{pipeline_run_id}/events", headers=admin_auth
    ) as r:
        assert r.status_code == 200
        # iter_lines 는 \n 단위. SSE 의 빈 줄(message 종결) 도 yield.
        for line in r.iter_lines():
            received_lines.append(line)
            saw_event = any("node.state.changed" in s for s in received_lines)
            saw_data = any(s.startswith("data: ") and len(s) > 6 for s in received_lines)
            if saw_event and saw_data:
                break
            if time.time() >= deadline:
                break

    t.join(timeout=1.0)

    # opening event 부터 도착했어야 함.
    assert any(line == "event: open" for line in received_lines)
    # node.state.changed 이벤트 도달.
    assert any(line == "event: node.state.changed" for line in received_lines)
    # data 라인 1건 이상.
    data_lines = [line for line in received_lines if line.startswith("data: ")]
    assert len(data_lines) >= 1


def test_sse_format_includes_sse_headers(
    it_client: TestClient,
    admin_auth: dict[str, str],
    seeded_pipeline_run: tuple[int, int],
) -> None:
    _, pipeline_run_id = seeded_pipeline_run
    with it_client.stream(
        "GET", f"/v1/pipelines/runs/{pipeline_run_id}/events", headers=admin_auth
    ) as r:
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert ctype.startswith("text/event-stream")
        assert r.headers.get("cache-control", "").startswith("no-cache")
        assert r.headers.get("x-accel-buffering") == "no"
        # 한 줄만 읽고 즉시 close.
        for _ in r.iter_lines():
            break

    # NodeRun 미사용 — 모델 임포트 회귀만.
    _ = NodeRun
