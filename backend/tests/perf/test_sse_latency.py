"""Pipeline SSE publish→수신 latency 측정 (Phase 3 비기능).

목표 (3.4): publish 시각 → SSE event 수신 시각 ≤ 500ms.

방법:
  1. 임시 PUBLISHED 워크플로 + pipeline_run 생성.
  2. SSE GET `/v1/pipelines/runs/{run_id}/stream` 을 별도 thread 로 구독.
  3. 메인 thread 에서 `RedisPubSub.publish(...)` — 같은 시점에 monotonic 기록.
  4. SSE 라인이 도착한 시점도 monotonic 기록 → 차이 = 종단 latency.
  5. 10회 반복 → avg / p95 / max.

제약: TestClient 의 SSE 는 bytes-stream 이라 실시간 측정이 까다롭다. 대신 raw HTTP +
threading 으로 구현. 인프라(실 PG + 실 Redis + 별도 백엔드) 가 떠 있어야 함.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import redis as redis_lib
from sqlalchemy import delete

from app.config import get_settings
from app.core.events import RedisPubSub
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.run import NodeRun, PipelineRun
from app.models.wf import (
    EdgeDefinition,
    NodeDefinition,
    PipelineRelease,
    WorkflowDefinition,
)

REPS = 10
TARGET_MS = 500


pytestmark = pytest.mark.skipif(
    os.environ.get("PERF") != "1",
    reason="PERF=1 환경변수가 없으면 비기능 테스트는 skip.",
)


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
def _backend_base_url() -> str:
    """`PERF_BACKEND_URL` env 가 없으면 http://localhost:8000."""
    return os.environ.get("PERF_BACKEND_URL", "http://localhost:8000")


@pytest.fixture
def _seed_pipeline_run() -> Iterator[tuple[int, str]]:
    """임시 PUBLISHED 워크플로 + RUNNING pipeline_run 1개 시드. (run_id, jwt) 반환."""
    sm = get_sync_sessionmaker()
    suffix = os.urandom(4).hex()
    name = f"PERF_SSE_{suffix}"
    with sm() as session:
        wf = WorkflowDefinition(
            name=name,
            version=1,
            status="PUBLISHED",
            description="perf SSE",
        )
        session.add(wf)
        session.flush()
        node = NodeDefinition(
            workflow_id=wf.workflow_id,
            node_key="A",
            node_type="NOOP",
            config_json={},
        )
        session.add(node)
        session.flush()
        pr = PipelineRun(
            workflow_id=wf.workflow_id,
            status="RUNNING",
            triggered_by=None,
        )
        session.add(pr)
        session.flush()
        nr = NodeRun(
            pipeline_run_id=pr.pipeline_run_id,
            run_date=pr.run_date,
            node_definition_id=node.node_id,
            node_key="A",
            node_type="NOOP",
            status="READY",
        )
        session.add(nr)
        session.commit()
        run_id = pr.pipeline_run_id
        wf_id = wf.workflow_id

    # admin token 발급.
    base = os.environ.get("PERF_BACKEND_URL", "http://localhost:8000")
    r = httpx.post(
        f"{base}/v1/auth/login",
        json={"login_id": "it_admin", "password": "it-admin-pw-0425"},
        timeout=5,
    )
    r.raise_for_status()
    jwt: str = r.json()["access_token"]

    yield run_id, jwt

    with sm() as session:
        session.execute(delete(NodeRun).where(NodeRun.pipeline_run_id == run_id))
        session.execute(delete(PipelineRun).where(PipelineRun.pipeline_run_id == run_id))
        session.execute(
            delete(PipelineRelease).where(PipelineRelease.released_workflow_id == wf_id)
        )
        session.execute(delete(EdgeDefinition).where(EdgeDefinition.workflow_id == wf_id))
        session.execute(delete(NodeDefinition).where(NodeDefinition.workflow_id == wf_id))
        session.execute(delete(WorkflowDefinition).where(WorkflowDefinition.workflow_id == wf_id))
        session.commit()
    dispose_sync_engine()


def test_sse_latency_publish_to_receive(
    _seed_pipeline_run: tuple[int, str],
    _backend_base_url: str,
    _redis_or_skip: redis_lib.Redis,
) -> None:
    run_id, jwt = _seed_pipeline_run
    received_at: list[float] = []
    publish_at: list[float] = []
    stop_evt = threading.Event()

    def reader() -> None:
        url = f"{_backend_base_url}/v1/pipelines/runs/{run_id}/stream"
        with (
            httpx.Client(timeout=None) as client,
            client.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {jwt}", "Accept": "text/event-stream"},
            ) as resp,
        ):
            assert resp.status_code == 200, resp.text
            for line in resp.iter_lines():
                if stop_evt.is_set():
                    return
                if not line or not line.startswith("data: "):
                    continue
                try:
                    payload = json.loads(line[len("data: ") :])
                except json.JSONDecodeError:
                    continue
                if payload.get("perf_marker"):
                    received_at.append(time.monotonic())
                    if len(received_at) >= REPS:
                        return

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(0.5)  # subscriber registration grace.

    pubsub = RedisPubSub.from_settings()
    try:
        for i in range(REPS):
            publish_at.append(time.monotonic())
            pubsub.publish(
                f"pipeline:{run_id}",
                {"perf_marker": True, "i": i, "published_at": time.monotonic()},
            )
            time.sleep(0.1)
    finally:
        pubsub.close()

    t.join(timeout=5)
    stop_evt.set()
    assert (
        len(received_at) >= REPS - 1
    ), f"only received {len(received_at)} of {REPS} markers — SSE may be disconnected"

    deltas_ms = [(r - p) * 1000 for p, r in zip(publish_at, received_at, strict=False)]
    avg_ms = statistics.mean(deltas_ms)
    p95_ms = sorted(deltas_ms)[int(len(deltas_ms) * 0.95)]
    max_ms = max(deltas_ms)

    print(
        "\n[PERF sse] "
        f"reps={len(deltas_ms)} avg={avg_ms:.1f}ms p95={p95_ms:.1f}ms max={max_ms:.1f}ms"
    )
    assert max_ms <= TARGET_MS * 2, f"max latency {max_ms:.1f}ms breaches 2x target"
    assert avg_ms <= TARGET_MS, f"avg latency {avg_ms:.1f}ms breaches target {TARGET_MS}ms"
