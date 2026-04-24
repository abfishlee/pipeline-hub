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
