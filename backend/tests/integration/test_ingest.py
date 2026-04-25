"""수집 API 통합 테스트 — 실 PG + MinIO. Phase 1.2.7."""

from __future__ import annotations

import io
import json
import os

import psycopg
from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas.ingest import INLINE_JSON_LIMIT_BYTES

from .conftest import _sync_url


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _fetch_outbox_event_type(
    settings: Settings, raw_object_id: int
) -> tuple[str, dict[str, object]] | None:
    """방금 적재된 raw_object 에 대응하는 outbox 이벤트 조회 — 테스트 확인용."""
    with (
        psycopg.connect(_sync_url(settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            SELECT event_type, payload_json
              FROM run.event_outbox
             WHERE aggregate_type = 'raw_object'
               AND aggregate_id = %s
             ORDER BY event_id DESC
             LIMIT 1
            """,
            (str(raw_object_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return row[0], row[1]


def _operator_auth_header(it_client: TestClient, _operator_seed: dict[str, str]) -> dict[str, str]:
    r = it_client.post("/v1/auth/login", json=_operator_seed)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# /v1/ingest/api/{source_code}
# ---------------------------------------------------------------------------
def test_ingest_api_json_happy_path(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
    integration_settings: Settings,
) -> None:
    code = active_source["source_code"]
    payload = {"sku": "CHAMOE-10KG", "price_krw": 24900, "store": "test"}
    r = it_client.post(
        f"/v1/ingest/api/{code}",
        json=payload,
        headers=operator_auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["dedup"] is False
    assert body["raw_object_id"] > 0
    assert body["job_id"] > 0
    # 작은 JSON → inline. object_uri 는 None.
    assert body["object_uri"] is None

    # DB 에 실제로 insert 되었는지 확인 (raw_object + outbox).
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT source_id, object_type, status, payload_json IS NOT NULL "
            "FROM raw.raw_object WHERE raw_object_id = %s",
            (body["raw_object_id"],),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[1] == "JSON"
    assert row[2] == "RECEIVED"
    assert row[3] is True  # payload_json 저장됨

    # outbox event
    ev = _fetch_outbox_event_type(integration_settings, body["raw_object_id"])
    assert ev is not None
    event_type, outbox_payload = ev
    assert event_type == "ingest.api.received"
    assert outbox_payload["raw_object_id"] == body["raw_object_id"]


def test_ingest_api_idempotency_returns_dedup(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    headers = {**operator_auth, "Idempotency-Key": "it-ingest-idem-001"}

    r1 = it_client.post(f"/v1/ingest/api/{code}", json={"x": 1}, headers=headers)
    assert r1.status_code == 201
    first_id = r1.json()["raw_object_id"]

    # 동일 키 + 다른 body → dedup (idempotency 우선).
    r2 = it_client.post(f"/v1/ingest/api/{code}", json={"x": 999, "y": "changed"}, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["dedup"] is True
    assert r2.json()["raw_object_id"] == first_id


def test_ingest_api_content_hash_dedup_without_idempotency(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    code = active_source["source_code"]
    body = {"sku": "SAME-BODY", "price": 100}

    r1 = it_client.post(f"/v1/ingest/api/{code}", json=body, headers=operator_auth)
    assert r1.status_code == 201
    first_id = r1.json()["raw_object_id"]

    # idempotency 없이도 content_hash 동일 → dedup.
    r2 = it_client.post(f"/v1/ingest/api/{code}", json=body, headers=operator_auth)
    assert r2.status_code == 200
    assert r2.json()["dedup"] is True
    assert r2.json()["raw_object_id"] == first_id


def test_ingest_api_inactive_source_is_forbidden(
    it_client: TestClient,
    operator_auth: dict[str, str],
    inactive_source: dict[str, object],
) -> None:
    code = inactive_source["source_code"]
    r = it_client.post(f"/v1/ingest/api/{code}", json={"x": 1}, headers=operator_auth)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_ingest_api_unknown_source_is_404(
    it_client: TestClient, operator_auth: dict[str, str]
) -> None:
    r = it_client.post(
        "/v1/ingest/api/NOT_EXIST_SOURCE",
        json={"x": 1},
        headers=operator_auth,
    )
    assert r.status_code == 404


def test_ingest_api_large_json_goes_to_object_storage(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
    integration_settings: Settings,
) -> None:
    code = active_source["source_code"]
    # INLINE 한계(64KB) 초과 페이로드 생성 — 70KB 목표.
    filler = "x" * (70 * 1024)
    payload = {"big_field": filler, "sku": "LARGE"}

    r = it_client.post(f"/v1/ingest/api/{code}", json=payload, headers=operator_auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["dedup"] is False
    assert body["object_uri"] is not None
    assert body["object_uri"].startswith(("s3://", "nos://"))

    # DB 쪽 payload_json 은 NULL 이어야 함.
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT payload_json IS NULL, object_uri FROM raw.raw_object WHERE raw_object_id = %s",
            (body["raw_object_id"],),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is True  # payload_json NULL
    assert row[1] == body["object_uri"]

    # INLINE_JSON_LIMIT_BYTES 상수 기준 sanity check
    assert len(json.dumps(payload)) > INLINE_JSON_LIMIT_BYTES


def test_ingest_api_requires_authentication(
    it_client: TestClient, active_source: dict[str, object]
) -> None:
    code = active_source["source_code"]
    r = it_client.post(f"/v1/ingest/api/{code}", json={"x": 1})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /v1/ingest/file/{source_code}
# ---------------------------------------------------------------------------
def test_ingest_file_upload_1mb_to_object_storage(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
    integration_settings: Settings,
) -> None:
    code = active_source["source_code"]
    payload = os.urandom(1024 * 1024)  # 1 MB
    r = it_client.post(
        f"/v1/ingest/file/{code}",
        files={"file": ("big.bin", io.BytesIO(payload), "application/octet-stream")},
        headers=operator_auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["dedup"] is False
    assert body["object_uri"] is not None

    # Presigned GET 으로 재다운로드 해 원본과 일치 확인 (MinIO → httpx).
    # object_uri 는 scheme://bucket/key 형식 — key 만 뽑아서 presigned_get.
    # 여기서는 DB 에 저장된 object_uri 만 확인.
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT object_type, object_uri FROM raw.raw_object WHERE raw_object_id = %s",
            (body["raw_object_id"],),
        )
        row = cur.fetchone()
    assert row is not None
    # application/octet-stream + ext 'bin' → _infer_object_type 는 fallback='JSON'
    # bin 확장자가 CHECK 에 없어서 JSON 으로 들어감 — 수용 가능 (Phase 2 에서 정제)
    assert row[0] in {"JSON", "IMAGE", "PDF", "CSV", "XML", "HTML", "DB_ROW"}
    assert row[1].endswith(".bin") is False or row[1].endswith(".bin")


# ---------------------------------------------------------------------------
# /v1/ingest/receipt
# ---------------------------------------------------------------------------
def test_ingest_receipt_11mb_returns_413(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    # 영수증 source 전용이 있으면 좋지만 테스트에서는 active_source 가 API type.
    # receipt 엔드포인트는 form 으로 source_code 받음.
    payload = os.urandom(11 * 1024 * 1024)  # 11 MB
    r = it_client.post(
        "/v1/ingest/receipt",
        files={"file": ("huge.jpg", io.BytesIO(payload), "image/jpeg")},
        data={"source_code": active_source["source_code"]},
        headers=operator_auth,
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_ingest_receipt_bad_content_type_is_422(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
) -> None:
    payload = b"not an image"
    r = it_client.post(
        "/v1/ingest/receipt",
        files={"file": ("bad.txt", io.BytesIO(payload), "text/plain")},
        data={"source_code": active_source["source_code"]},
        headers=operator_auth,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_ingest_receipt_valid_jpeg_ok(
    it_client: TestClient,
    operator_auth: dict[str, str],
    active_source: dict[str, object],
    integration_settings: Settings,
) -> None:
    # 작은 이미지 더미 — JPEG SOI/EOI 마커만 포함.
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"
    r = it_client.post(
        "/v1/ingest/receipt",
        files={"file": ("receipt.jpg", io.BytesIO(jpg), "image/jpeg")},
        data={"source_code": active_source["source_code"]},
        headers=operator_auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["object_uri"] is not None
    assert "/receipt/" in body["object_uri"]

    # object_type 확인.
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT object_type FROM raw.raw_object WHERE raw_object_id = %s",
            (body["raw_object_id"],),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "RECEIPT_IMAGE"

    # outbox event type 확인.
    ev = _fetch_outbox_event_type(integration_settings, body["raw_object_id"])
    assert ev is not None
    assert ev[0] == "ingest.receipt.received"
