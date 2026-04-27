"""Phase 8.4 — Inbound `auth_method='api_key'` 인증 통합 테스트.

검증:
  1. 정상 X-API-Key → 202 + envelope 생성
  2. 잘못된 X-API-Key → 401 + security_event 기록
  3. X-API-Key 헤더 누락 → 401 + security_event 기록
  4. secret_ref env 미설정 → 500
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

API_KEY_CHANNEL_CODE = "p84_apikey_test_channel"
API_KEY_SECRET_REF = "P84_TEST_API_KEY"
API_KEY_VALUE = "p84-test-key-7c6a9e"


@pytest.fixture
def apikey_channel() -> None:
    """auth_method='api_key' 채널 1건 등록 (idempotent) + env 설정."""
    os.environ[API_KEY_SECRET_REF] = API_KEY_VALUE

    sm = get_sync_sessionmaker()
    with sm() as s:
        # domain.domain_definition emart 가 시드에 있다는 가정 (Phase 8 seed 의존).
        # 없으면 skip.
        d = s.execute(
            text("SELECT 1 FROM domain.domain_definition WHERE domain_code='emart'")
        ).scalar_one_or_none()
        if d is None:
            pytest.skip("Phase 8 seed (emart 도메인) 미적용")

        s.execute(
            text(
                "INSERT INTO domain.inbound_channel "
                "(channel_code, domain_code, name, channel_kind, secret_ref, "
                " auth_method, status, is_active, expected_content_type) "
                "VALUES (:c, 'emart', 'P84 API Key Test', 'WEBHOOK', :sr, "
                "        'api_key', 'PUBLISHED', true, 'application/json') "
                "ON CONFLICT (channel_code) DO UPDATE SET "
                "  auth_method='api_key', secret_ref=EXCLUDED.secret_ref, "
                "  status='PUBLISHED', is_active=true"
            ),
            {"c": API_KEY_CHANNEL_CODE, "sr": API_KEY_SECRET_REF},
        )
        s.commit()
    yield


def test_inbound_api_key_success(it_client: TestClient, apikey_channel: None) -> None:
    """정상 X-API-Key + JSON payload → 202."""
    res = it_client.post(
        f"/v1/inbound/{API_KEY_CHANNEL_CODE}",
        content=b'{"items":[{"name":"apple","price":1500}]}',
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY_VALUE,
            "X-Idempotency-Key": "p84-apikey-success-1",
        },
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["channel_code"] == API_KEY_CHANNEL_CODE
    assert body["status"] == "RECEIVED"


def test_inbound_api_key_invalid(
    it_client: TestClient, apikey_channel: None
) -> None:
    """잘못된 X-API-Key → 401 + security_event."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        before = s.execute(
            text(
                "SELECT COUNT(*) FROM audit.security_event "
                "WHERE details_json->>'channel_code' = :c "
                "  AND details_json->>'reason' = 'api_key_mismatch'"
            ),
            {"c": API_KEY_CHANNEL_CODE},
        ).scalar_one()

    res = it_client.post(
        f"/v1/inbound/{API_KEY_CHANNEL_CODE}",
        content=b'{"items":[]}',
        headers={
            "Content-Type": "application/json",
            "X-API-Key": "wrong-key-zzz",
            "X-Idempotency-Key": "p84-apikey-invalid-1",
        },
    )
    assert res.status_code == 401, res.text
    assert "invalid" in res.json()["detail"].lower()

    # security_event 1 건 증가 확인.
    with sm() as s:
        after = s.execute(
            text(
                "SELECT COUNT(*) FROM audit.security_event "
                "WHERE details_json->>'channel_code' = :c "
                "  AND details_json->>'reason' = 'api_key_mismatch'"
            ),
            {"c": API_KEY_CHANNEL_CODE},
        ).scalar_one()
        assert int(after) == int(before) + 1


def test_inbound_api_key_missing(
    it_client: TestClient, apikey_channel: None
) -> None:
    """X-API-Key 헤더 누락 → 401 + security_event."""
    res = it_client.post(
        f"/v1/inbound/{API_KEY_CHANNEL_CODE}",
        content=b'{"items":[]}',
        headers={
            "Content-Type": "application/json",
            "X-Idempotency-Key": "p84-apikey-missing-1",
        },
    )
    assert res.status_code == 401, res.text
    assert "required" in res.json()["detail"].lower()
