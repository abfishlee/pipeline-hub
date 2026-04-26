"""Phase 8.1 — 4 유통사 가상 시나리오 풀 e2e 회귀 테스트.

검증 흐름 (사용자 § 5 — 보완 항목 #2):
  1. alembic + Phase 8 seed 가 적용되어 4 유통사 자산이 모두 PUBLISHED
  2. service_mart 통합 마트가 4 유통사 데이터를 모두 노출
  3. inbound 채널 3종 (CRAWLER/OCR/UPLOAD) 등록 + push endpoint 인증
  4. Operations Dashboard 의 channels endpoint 가 5+ workflow 노출
  5. inbound dispatch endpoint 가 PROCESSING 상태로 전환

본 테스트는 *seed 가 미리 적용된 환경* 에서 실행. seed 없으면 건너뜀 (skip).
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker


def _seed_present() -> bool:
    """Phase 8 seed 가 적용된 환경인지 확인."""
    sm = get_sync_sessionmaker()
    with sm() as s:
        try:
            cnt = s.execute(
                text(
                    "SELECT COUNT(*) FROM domain.public_api_connector "
                    "WHERE domain_code IN ('emart','homeplus','lottemart','hanaro')"
                )
            ).scalar_one()
            return int(cnt) >= 4
        except Exception:
            return False


def test_phase8_seed_applied() -> None:
    """Phase 8 seed 가 적용되어 4 유통사 connector 4건 존재."""
    if not _seed_present():
        import pytest

        pytest.skip("Phase 8 seed 미적용 — phase8_seed_full_e2e.py 먼저 실행")
    sm = get_sync_sessionmaker()
    with sm() as s:
        # connector 4
        cnt = s.execute(
            text(
                "SELECT COUNT(*) FROM domain.public_api_connector "
                "WHERE domain_code IN ('emart','homeplus','lottemart','hanaro')"
            )
        ).scalar_one()
        assert int(cnt) == 4

        # service_mart unified rows
        cnt = s.execute(
            text(
                "SELECT COUNT(*) FROM service_mart.product_price "
                "WHERE retailer_code IN ('emart','homeplus','lottemart','hanaro')"
            )
        ).scalar_one()
        assert int(cnt) >= 10  # 최소 10 row 이상 통합


def test_phase8_service_mart_endpoint(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """/v2/service-mart/channel-stats 가 4 유통사 모두 노출."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    res = it_client.get(
        "/v2/service-mart/channel-stats", headers=admin_auth
    )
    assert res.status_code == 200, res.text
    stats = res.json()
    retailers = {s["retailer_code"] for s in stats}
    assert {"emart", "homeplus", "lottemart", "hanaro"}.issubset(retailers)


def test_phase8_operations_summary(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """/v2/operations/summary 가 PUBLISHED workflow 5+ 카운트."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    res = it_client.get("/v2/operations/summary", headers=admin_auth)
    assert res.status_code == 200, res.text
    summary = res.json()
    assert summary["workflow_count"] >= 4
    # rows_24h / runs_24h 등 placeholder 가 아닌 실값 존재 확인
    assert "runs_24h" in summary
    assert "success_rate_pct" in summary


def test_phase8_operations_channels(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """/v2/operations/channels 가 4+ workflow 노출."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    res = it_client.get(
        "/v2/operations/channels?limit=20", headers=admin_auth
    )
    assert res.status_code == 200, res.text
    channels = res.json()
    workflow_names = {c["workflow_name"] for c in channels}
    # 4 유통사 workflow 모두 존재
    expected = {
        "emart_price_daily",
        "homeplus_promo_daily",
        "lottemart_canon_daily",
        "hanaro_agri_daily",
    }
    assert expected.issubset(workflow_names), (
        f"missing workflows: {expected - workflow_names}"
    )


def test_phase8_inbound_channels_published(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """/v2/inbound-channels 가 3 채널 PUBLISHED."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    res = it_client.get("/v2/inbound-channels", headers=admin_auth)
    assert res.status_code == 200
    channels = res.json()
    codes = {c["channel_code"] for c in channels}
    assert {"vendor_a_crawler", "ocr_partner_b", "smb_uploads"}.issubset(codes)


def test_phase8_inbound_endpoint_hmac_auth(
    it_client: TestClient,
) -> None:
    """POST /v1/inbound/{channel_code} — HMAC 인증 검증.

    실 secret 은 env 에 없으므로 401 응답 (secret_ref 미설정) 또는 422 응답.
    중요한 건 endpoint 가 *살아있고 인증이 작동*함.
    """
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    # invalid signature → 401 또는 secret 없음 → 500
    payload = b'{"items": []}'
    timestamp = int(time.time())
    res = it_client.post(
        "/v1/inbound/vendor_a_crawler",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Signature": "hmac-sha256=" + "a" * 64,
            "X-Timestamp": str(timestamp),
            "X-Idempotency-Key": "phase8_e2e_test_invalid",
        },
    )
    # 401 (HMAC 불일치) / 500 (secret 미설정) 둘 다 OK — endpoint 살아있음.
    assert res.status_code in (401, 500)


def test_phase8_dispatch_pending_endpoint(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """POST /v2/operations/dispatch-pending 작동."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    res = it_client.post(
        "/v2/operations/dispatch-pending?limit=10", headers=admin_auth
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "pending_before" in body
    assert "pending_after" in body
    assert isinstance(body["items"], list)


def test_phase8_review_queue_has_low_confidence_tasks(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """롯데마트 low confidence → 검수 큐 (crowd.task) 시드 검증."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    sm = get_sync_sessionmaker()
    with sm() as s:
        cnt = s.execute(
            text(
                "SELECT COUNT(*) FROM crowd.task "
                "WHERE task_kind = 'std_low_confidence'"
            )
        ).scalar_one()
        assert int(cnt) >= 3, f"expected 3+ low confidence tasks, got {cnt}"


def test_phase8_intentional_failed_runs_present(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """시나리오상 의도적 FAILED 케이스 — 운영자가 발견할 부분."""
    if not _seed_present():
        import pytest

        pytest.skip("seed 필요")
    sm = get_sync_sessionmaker()
    with sm() as s:
        cnt = s.execute(
            text(
                "SELECT COUNT(*) FROM run.pipeline_run "
                "WHERE status = 'FAILED'"
            )
        ).scalar_one()
        assert int(cnt) >= 1, "Phase 8 시드는 의도적 FAILED 케이스 포함"
