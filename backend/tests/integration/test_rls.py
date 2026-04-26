"""Phase 4.2.4 — RLS + 컬럼 마스킹 통합 테스트.

검증 시나리오:
  1. app_rw / connection user → mart.retailer_master_view 의 business_no 평문.
  2. app_public → business_no 마스킹 (`***-**-****`), head_office_addr NULL.
  3. mart.seller_master RLS — allowlist 비어 있으면 0 row.
  4. allowlist 부분 매칭 — 해당 retailer 의 row 만 보임.
  5. RESET ROLE → connection user 로 복귀 + 모든 row 다시 보임.

실 PG 의존. 미가동 시 skip.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import hash_password
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker


@pytest.fixture
def cleanup_mart() -> Iterator[dict[str, list[int]]]:
    """테스트 종료 시 생성한 mart row 제거."""
    state: dict[str, list[int]] = {
        "retailers": [],
        "sellers": [],
        "api_keys": [],
    }
    yield state
    sm = get_sync_sessionmaker()
    with sm() as session:
        if state["sellers"]:
            session.execute(
                text("DELETE FROM mart.seller_master WHERE seller_id = ANY(:ids)"),
                {"ids": state["sellers"]},
            )
        if state["retailers"]:
            session.execute(
                text("DELETE FROM mart.retailer_master WHERE retailer_id = ANY(:ids)"),
                {"ids": state["retailers"]},
            )
        if state["api_keys"]:
            # Phase 4.2.5 — public_api_usage / public_api_usage_daily 의 FK 정리.
            session.execute(
                text(
                    "DELETE FROM audit.public_api_usage "
                    " WHERE api_key_id = ANY(:ids)"
                ),
                {"ids": state["api_keys"]},
            )
            session.execute(
                text("DELETE FROM ctl.api_key WHERE api_key_id = ANY(:ids)"),
                {"ids": state["api_keys"]},
            )
        session.commit()
    dispose_sync_engine()


def _seed_two_retailers(state: dict[str, list[int]]) -> tuple[int, int, int, int]:
    """retailer 2개 + 각 retailer 의 seller 1개 시드. (r1, r2, s1, s2) 반환."""
    sm = get_sync_sessionmaker()
    suffix = secrets.token_hex(4).upper()
    with sm() as session:
        r1_code = f"IT_RLS_R1_{suffix}"
        r2_code = f"IT_RLS_R2_{suffix}"
        r1 = session.execute(
            text(
                "INSERT INTO mart.retailer_master "
                "(retailer_code, retailer_name, retailer_type, business_no, head_office_addr) "
                "VALUES (:c, '검증 retailer 1', 'MART', '123-45-67890', '서울 강남구') "
                "RETURNING retailer_id"
            ),
            {"c": r1_code},
        ).scalar_one()
        r2 = session.execute(
            text(
                "INSERT INTO mart.retailer_master "
                "(retailer_code, retailer_name, retailer_type, business_no, head_office_addr) "
                "VALUES (:c, '검증 retailer 2', 'MART', '987-65-43210', '부산 해운대구') "
                "RETURNING retailer_id"
            ),
            {"c": r2_code},
        ).scalar_one()
        s1 = session.execute(
            text(
                "INSERT INTO mart.seller_master "
                "(retailer_id, seller_code, seller_name, channel, region_sido, region_sigungu, "
                " address) "
                "VALUES (:r, :c, 's1', 'OFFLINE', '서울', '강남구', '서울 강남구 테헤란로 1') "
                "RETURNING seller_id"
            ),
            {"r": r1, "c": f"S1_{suffix}"},
        ).scalar_one()
        s2 = session.execute(
            text(
                "INSERT INTO mart.seller_master "
                "(retailer_id, seller_code, seller_name, channel, region_sido, region_sigungu, "
                " address) "
                "VALUES (:r, :c, 's2', 'OFFLINE', '부산', '해운대구', '부산 해운대구 우동 1') "
                "RETURNING seller_id"
            ),
            {"r": r2, "c": f"S2_{suffix}"},
        ).scalar_one()
        session.commit()
    state["retailers"].extend([r1, r2])
    state["sellers"].extend([s1, s2])
    return int(r1), int(r2), int(s1), int(s2)


# ---------------------------------------------------------------------------
# 1. app_rw — 평문 노출
# ---------------------------------------------------------------------------
def test_admin_role_sees_plaintext_business_no(
    cleanup_mart: dict[str, list[int]],
) -> None:
    r1, _r2, _s1, _s2 = _seed_two_retailers(cleanup_mart)
    sm = get_sync_sessionmaker()
    with sm() as session:
        # connection user (= app) 는 SET ROLE 안 해도 평문이 보여야 함.
        row = session.execute(
            text(
                "SELECT business_no, head_office_addr "
                "FROM mart.retailer_master_view WHERE retailer_id = :rid"
            ),
            {"rid": r1},
        ).one()
        assert row.business_no == "123-45-67890"
        assert row.head_office_addr == "서울 강남구"


# ---------------------------------------------------------------------------
# 2. app_public — 마스킹
# ---------------------------------------------------------------------------
def test_public_role_sees_masked_business_no(
    cleanup_mart: dict[str, list[int]],
) -> None:
    r1, _r2, _s1, _s2 = _seed_two_retailers(cleanup_mart)
    sm = get_sync_sessionmaker()
    with sm() as session:
        # 트랜잭션 안에서 SET LOCAL ROLE — commit 시 자동 해제.
        session.execute(text("SET LOCAL ROLE app_public"))
        row = session.execute(
            text(
                "SELECT business_no, head_office_addr "
                "FROM mart.retailer_master_view WHERE retailer_id = :rid"
            ),
            {"rid": r1},
        ).one()
        # 숫자가 모두 '*' 로 마스킹.
        assert row.business_no == "***-**-*****"
        assert row.head_office_addr is None
        session.rollback()


# ---------------------------------------------------------------------------
# 3. RLS — allowlist 비어 있으면 seller 0 row
# ---------------------------------------------------------------------------
def test_public_with_empty_allowlist_sees_no_sellers(
    cleanup_mart: dict[str, list[int]],
) -> None:
    _r1, _r2, _s1, _s2 = _seed_two_retailers(cleanup_mart)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text("SET LOCAL ROLE app_public"))
        # allowlist 비움.
        session.execute(text("SELECT set_config('app.retailer_allowlist', '', true)"))
        rows = session.execute(
            text("SELECT seller_id FROM mart.seller_master")
        ).all()
        assert rows == []
        session.rollback()


# ---------------------------------------------------------------------------
# 4. RLS — allowlist 부분 매칭
# ---------------------------------------------------------------------------
def test_public_with_partial_allowlist_sees_only_matching(
    cleanup_mart: dict[str, list[int]],
) -> None:
    r1, r2, s1, s2 = _seed_two_retailers(cleanup_mart)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text("SET LOCAL ROLE app_public"))
        session.execute(
            text("SELECT set_config('app.retailer_allowlist', :v, true)"),
            {"v": "{" + str(r1) + "}"},
        )
        rows = session.execute(
            text("SELECT seller_id, retailer_id, address FROM mart.seller_master_view")
        ).all()
        seller_ids = {r.seller_id for r in rows}
        assert s1 in seller_ids
        assert s2 not in seller_ids
        # address 컬럼은 마스킹.
        assert all(r.address is None for r in rows)
        session.rollback()
        del r2  # used only for clarity in assertion above.


# ---------------------------------------------------------------------------
# 5. RESET ROLE → app 으로 복귀
# ---------------------------------------------------------------------------
def test_reset_role_restores_full_visibility(
    cleanup_mart: dict[str, list[int]],
) -> None:
    _r1, _r2, _s1, _s2 = _seed_two_retailers(cleanup_mart)
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(text("SET LOCAL ROLE app_public"))
        session.execute(text("SELECT set_config('app.retailer_allowlist', '', true)"))
        empty = session.execute(text("SELECT COUNT(*) FROM mart.seller_master")).scalar_one()
        assert empty == 0
        session.execute(text("RESET ROLE"))
        all_rows = session.execute(text("SELECT COUNT(*) FROM mart.seller_master")).scalar_one()
        assert all_rows >= 2
        session.rollback()


# ---------------------------------------------------------------------------
# 6. /public/v1 endpoints — api_key 인증 + 마스킹 + RLS 통합
# ---------------------------------------------------------------------------
def test_public_endpoint_masks_and_filters_by_allowlist(
    it_client: TestClient,
    cleanup_mart: dict[str, list[int]],
) -> None:
    r1, _r2, s1, s2 = _seed_two_retailers(cleanup_mart)

    # api_key 시드 — retailer_allowlist = [r1].
    sm = get_sync_sessionmaker()
    suffix = secrets.token_hex(4).lower()
    prefix = f"itrls{suffix}"
    secret = secrets.token_urlsafe(24)
    with sm() as session:
        api_key_id = session.execute(
            text(
                "INSERT INTO ctl.api_key "
                "(key_prefix, key_hash, client_name, scope, retailer_allowlist) "
                "VALUES (:p, :h, 'IT RLS client', "
                "        '{products.read,prices.read}', :al) "
                "RETURNING api_key_id"
            ),
            {
                "p": prefix,
                "h": hash_password(secret),
                "al": "{" + str(r1) + "}",
            },
        ).scalar_one()
        session.commit()
    cleanup_mart["api_keys"].append(int(api_key_id))

    # GET /public/v1/sellers — RLS 로 r1 의 seller 만 노출 + address 마스킹.
    r = it_client.get(
        "/public/v1/sellers",
        headers={"X-API-Key": f"{prefix}.{secret}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    seller_ids = {b["seller_id"] for b in body}
    assert s1 in seller_ids
    assert s2 not in seller_ids
    assert all(b["address"] is None for b in body)

    # GET /public/v1/retailers — 모든 retailer 보임 + business_no 마스킹.
    r = it_client.get(
        "/public/v1/retailers",
        headers={"X-API-Key": f"{prefix}.{secret}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    target = next((b for b in body if b["retailer_id"] == r1), None)
    assert target is not None
    assert "*" in target["business_no"]
    assert target["head_office_addr"] is None

    # 잘못된 API key → 401.
    bad = it_client.get(
        "/public/v1/retailers",
        headers={"X-API-Key": f"{prefix}.wrong-secret"},
    )
    assert bad.status_code == 401

    # X-API-Key 누락 → 401.
    missing = it_client.get("/public/v1/retailers")
    assert missing.status_code == 401
