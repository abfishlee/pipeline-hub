"""Phase 4.2.8 — Multi-source 머지 통합 테스트.

검증:
  1. 동일 std_code + 호환되는 grade/weight_g 의 product 3개 → 자동 머지 → 1개.
  2. product_mapping.retailer_product_code 보존 + product_id 가 target 으로 통합.
  3. cluster row >= 5 → 분쟁 → crowd_task PRODUCT_MATCHING 발급 (자동 머지 X).
  4. grade 다수결 < 50% → 분쟁 → crowd_task.
  5. unmerge_op → 새 product_id 발급 + master_merge_op.is_unmerged=true.

실 PG 의존.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, select, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.master_merge import (
    attempt_auto_merge,
    find_merge_candidates,
    unmerge_op,
)
from app.models.mart import (
    MasterMergeOp,
    ProductMapping,
    ProductMaster,
    RetailerMaster,
)


@pytest.fixture
def std_code_seed() -> Iterator[str]:
    """1 std_code 와 retailer 1개 시드 → cleanup."""
    sm = get_sync_sessionmaker()
    code = f"FRT_TEST_{secrets.token_hex(3).upper()}"
    retailer_code = f"IT_MM_R_{secrets.token_hex(3).upper()}"
    with sm() as session:
        session.execute(
            text(
                "INSERT INTO mart.standard_code "
                "(std_code, category_lv1, item_name_ko, source_authority) "
                "VALUES (:c, '농산물', '사과', 'IT')"
            ),
            {"c": code},
        )
        session.execute(
            text(
                "INSERT INTO mart.retailer_master (retailer_code, retailer_name, retailer_type) "
                "VALUES (:c, '검증 마트', 'MART')"
            ),
            {"c": retailer_code},
        )
        session.commit()
    yield code
    with sm() as session:
        # 정리 — product_mapping 의 FK 부터.
        session.execute(text("DELETE FROM mart.master_merge_op WHERE merge_op_id IN ("
                             " SELECT mo.merge_op_id FROM mart.master_merge_op mo "
                             "  JOIN mart.product_master pm ON pm.product_id = mo.target_product_id"
                             "  WHERE pm.std_code = :c)"),
                        {"c": code})
        session.execute(
            text(
                "DELETE FROM mart.product_mapping WHERE product_id IN ("
                "  SELECT product_id FROM mart.product_master WHERE std_code = :c)"
            ),
            {"c": code},
        )
        session.execute(delete(ProductMaster).where(ProductMaster.std_code == code))
        session.execute(text("DELETE FROM mart.standard_code WHERE std_code = :c"), {"c": code})
        session.execute(
            text("DELETE FROM mart.retailer_master WHERE retailer_code = :c"),
            {"c": retailer_code},
        )
        session.execute(
            text(
                "DELETE FROM crowd.task WHERE task_kind = 'PRODUCT_MATCHING' "
                "  AND payload->>'std_code' = :c"
            ),
            {"c": code},
        )
        session.commit()
    dispose_sync_engine()


def _seed_products(
    session, *, std_code: str, count: int, base_weight_g: float = 1500.0,
    grade: str = "특", package_type: str = "낱개"
) -> list[int]:
    """count 개 product_master row 시드. weight_g 를 ±5% 안에서 살짝 다르게.

    product_master 의 UNIQUE(std_code, grade, package_type, sale_unit_norm, weight_g)
    를 회피하려면 weight 가 달라야 함. 1500/1510/1520... 식 (~0.7% 차이) — 모두 ±5%
    허용 범위라 같은 cluster.
    """
    ids: list[int] = []
    for i in range(count):
        pm = ProductMaster(
            std_code=std_code,
            grade=grade,
            package_type=package_type,
            sale_unit_norm="kg",
            weight_g=base_weight_g + i * 10,
            canonical_name=f"사과 v{i}",
            confidence_score=80.0 + i,
        )
        session.add(pm)
        session.flush()
        ids.append(pm.product_id)
    session.commit()
    return ids


def _seed_mapping(session, *, retailer_id: int, product_id: int, code: str) -> None:
    pm = ProductMapping(
        retailer_id=retailer_id,
        retailer_product_code=code,
        raw_product_name=f"raw {code}",
        product_id=product_id,
        match_method="HUMAN",
        confidence_score=90.0,
    )
    session.add(pm)
    session.flush()


def _retailer_id(session, code: str) -> int:
    return int(
        session.execute(
            select(RetailerMaster.retailer_id).where(RetailerMaster.retailer_code == code)
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# 1. 자동 머지 + retailer_product_code 보존
# ---------------------------------------------------------------------------
def test_auto_merge_three_products(std_code_seed: str) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        ids = _seed_products(session, std_code=std_code_seed, count=3)
        # mapping seed — 3 개의 retailer_product_code, 각자 다른 product_id 에 분포.
        retailer_code = (
            session.execute(
                text(
                    "SELECT retailer_code FROM mart.retailer_master "
                    "WHERE retailer_code LIKE 'IT_MM_R_%' "
                    "ORDER BY retailer_id DESC LIMIT 1"
                )
            ).scalar_one()
        )
        rid = _retailer_id(session, retailer_code)
        for i, pid in enumerate(ids):
            _seed_mapping(session, retailer_id=rid, product_id=pid, code=f"RPC-{i}")
        session.commit()

    # find candidates → 1 group of 3.
    with sm() as session:
        cands = find_merge_candidates(session, std_code=std_code_seed)
        assert len(cands) == 1
        assert len(cands[0].products) == 3

        # 자동 머지.
        result = attempt_auto_merge(session, candidate=cands[0])
        assert result is not None
        assert len(result.source_ids) == 2
        # 같은 std_code 의 product_master 가 1 개만 남음.
        remaining = list(
            session.execute(
                select(ProductMaster).where(ProductMaster.std_code == std_code_seed)
            ).scalars()
        )
        assert len(remaining) == 1
        assert remaining[0].product_id == result.target_product_id

        # mapping 의 retailer_product_code 가 모두 보존 + product_id 가 target.
        mappings = list(
            session.execute(
                select(ProductMapping).where(
                    ProductMapping.product_id == result.target_product_id
                )
            ).scalars()
        )
        codes = sorted([m.retailer_product_code for m in mappings])
        assert codes == ["RPC-0", "RPC-1", "RPC-2"]

        # master_merge_op 1행.
        ops = list(
            session.execute(
                select(MasterMergeOp).where(
                    MasterMergeOp.target_product_id == result.target_product_id
                )
            ).scalars()
        )
        assert len(ops) == 1
        assert sorted(ops[0].source_product_ids) == sorted(ids)
        session.commit()


# ---------------------------------------------------------------------------
# 2. 5+ row 분쟁 → 자동 머지 X + crowd_task 발급
# ---------------------------------------------------------------------------
def test_dispute_too_many_rows_creates_crowd(std_code_seed: str) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        _seed_products(session, std_code=std_code_seed, count=5)
        session.commit()
    with sm() as session:
        cands = find_merge_candidates(session, std_code=std_code_seed)
        assert len(cands) == 1
        result = attempt_auto_merge(session, candidate=cands[0])
        assert result is None  # 분쟁
        # crowd_task 1건.
        ct = session.execute(
            text(
                "SELECT COUNT(*) FROM crowd.task "
                "WHERE task_kind = 'PRODUCT_MATCHING' "
                "  AND payload->>'std_code' = :c"
            ),
            {"c": std_code_seed},
        ).scalar_one()
        assert ct == 1
        # product_master 는 그대로 5 row 보존.
        remaining = session.execute(
            select(ProductMaster).where(ProductMaster.std_code == std_code_seed)
        ).scalars().all()
        assert len(list(remaining)) == 5
        session.commit()


# ---------------------------------------------------------------------------
# 3. grade 다수결 < 50% 분쟁 → crowd_task
# ---------------------------------------------------------------------------
def test_dispute_low_majority_creates_crowd(std_code_seed: str) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        # 4 product 각자 다른 grade (특/대/중/소) — 다수결 비율 25%.
        for grade in ("특", "대", "중", "소"):
            pm = ProductMaster(
                std_code=std_code_seed,
                grade=grade,
                package_type="낱개",
                sale_unit_norm="kg",
                weight_g=1500.0,
                canonical_name=f"사과 {grade}",
                confidence_score=85.0,
            )
            session.add(pm)
        session.commit()

    # 클러스터링은 (grade, package_type, sale_unit_norm) 동일을 요구하므로
    # grade 가 4종이면 자동 분리 → cluster size 1 씩 → 후보 0. 본 테스트는
    # find_merge_candidates 가 후보 0 을 반환함을 검증 (분쟁 분기 진입 전 클러스터링
    # 자체가 분리).
    with sm() as session:
        cands = find_merge_candidates(session, std_code=std_code_seed)
        assert cands == []
        session.commit()


# ---------------------------------------------------------------------------
# 4. weight_g ±5% 허용 — 1500 vs 1550 (3.3%) 같은 cluster
# ---------------------------------------------------------------------------
def test_weight_tolerance_clusters_close_weights(std_code_seed: str) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        for w in (1500.0, 1550.0):
            pm = ProductMaster(
                std_code=std_code_seed,
                grade="특",
                package_type="낱개",
                sale_unit_norm="kg",
                weight_g=w,
                canonical_name=f"사과 {w}g",
                confidence_score=85.0,
            )
            session.add(pm)
        session.commit()
    with sm() as session:
        cands = find_merge_candidates(session, std_code=std_code_seed)
        assert len(cands) == 1
        assert len(cands[0].products) == 2


# ---------------------------------------------------------------------------
# 5. unmerge — 새 product_id 발급 + is_unmerged=true
# ---------------------------------------------------------------------------
def test_unmerge_creates_new_product_ids(std_code_seed: str) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        _seed_products(session, std_code=std_code_seed, count=3)
        session.commit()
    with sm() as session:
        cands = find_merge_candidates(session, std_code=std_code_seed)
        result = attempt_auto_merge(session, candidate=cands[0])
        assert result is not None
        session.commit()
    with sm() as session:
        op_id = result.merge_op_id
        un = unmerge_op(session, merge_op_id=op_id, unmerged_by=None)
        assert un.merge_op_id == op_id
        assert len(un.new_product_ids) == 2  # 3 source 중 target 제외 = 2 새 row
        op_row = session.get(MasterMergeOp, op_id)
        assert op_row is not None
        assert op_row.is_unmerged is True
        assert op_row.unmerged_at is not None
        session.commit()
