"""Health endpoint smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_structure(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["env"] == "local"
    assert "version" in body
    assert body["checks"]["app"] == "ok"
    assert body["checks"]["db"] == "ok"


def test_readyz_returns_503_when_db_down(client_db_down: TestClient) -> None:
    """DB ping 실패 시 503 + checks.db=fail. healthz 는 영향 없음."""
    r = client_db_down.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unready"
    assert body["checks"]["db"] == "fail"
    assert body["checks"]["app"] == "ok"


def test_healthz_unaffected_by_db_state(client_db_down: TestClient) -> None:
    """DB 다운이어도 healthz 는 200 (liveness 는 외부 의존성과 분리)."""
    r = client_db_down.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_request_id_is_generated_when_missing(client: TestClient) -> None:
    r = client.get("/healthz")
    assert "x-request-id" in {k.lower() for k in r.headers}
    # uuid4 hex = 32자
    assert len(r.headers["x-request-id"]) == 32


def test_request_id_is_propagated_when_provided(client: TestClient) -> None:
    incoming = "test-corr-id-12345"
    r = client.get("/healthz", headers={"X-Request-ID": incoming})
    assert r.headers["x-request-id"] == incoming


def test_root_returns_meta(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "datapipeline-backend"
    assert "version" in body
