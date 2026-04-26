"""Multi-source 머지 (Phase 4.2.8).

같은 std_code + 유사 weight_g/grade/package_type 인 `mart.product_master` row 들을
1개로 수렴.

규칙:
  1. 같은 std_code 안에서 (grade, package_type, sale_unit_norm) 가 *동일* 한 row 들은
     자동 후보. weight_g 는 ±5% 허용 — 표기 차이 흡수.
  2. canonical_name = 후보 중 ProductMapping count 가 가장 많은 product 의 이름
     (= 가장 많이 관찰된 표현). tie 면 product_id 가장 작은 쪽.
  3. weight_g/grade/package_type/sale_unit_norm = 다수결 (count 기반). tie 시 target
     row 그대로.
  4. confidence_score 가 *낮은* product 들이 후보로 들어가도, target 은 가장 높은
     confidence 를 채택.
  5. 분쟁 (다수결 결과가 50% 미만 또는 row 가 5개 이상) → 자동 머지 X +
     `run.crowd_task` (reason='PRODUCT_MATCHING') 자동 생성.

머지 실행:
  - target product 1개 선택 (가장 큰 product_id — 최근 등록 가정).
  - product_mapping 의 product_id 를 *모두 target* 으로 UPDATE.
  - 나머지 source product 들 DELETE.
  - mart.master_merge_op 1행 INSERT.

Un-merge:
  - merge_op_id 로 source_product_ids 조회 → product_master 재생성 (id 재사용 어려우면
    새 id 부여 — 본 PoC 는 *원본 id 보존* 위해 ON CONFLICT DO UPDATE 와 sequence
    조작 회피, 대신 *unmerge 후 새 product_id 부여 + master_merge_op.is_unmerged=true*).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.mart import MasterMergeOp, ProductMaster

logger = logging.getLogger(__name__)

WEIGHT_TOLERANCE_PCT = 5.0  # ±5% 허용
DISPUTE_ROW_THRESHOLD = 5    # 5+ row 면 분쟁 → crowd
DISPUTE_MAJORITY_PCT = 50.0  # 다수결 < 50% 면 분쟁


@dataclass(slots=True, frozen=True)
class MergeCandidate:
    """1 std_code 의 머지 후보 그룹 (≥ 2 product)."""

    std_code: str
    products: list[ProductMaster]


@dataclass(slots=True, frozen=True)
class MergeResult:
    merge_op_id: int
    target_product_id: int
    source_ids: list[int]
    mapping_count: int
    canonical_name: str


@dataclass(slots=True, frozen=True)
class UnmergeResult:
    merge_op_id: int
    new_product_ids: list[int]


# ---------------------------------------------------------------------------
# 후보 detect
# ---------------------------------------------------------------------------
def find_merge_candidates(session: Session, *, std_code: str | None = None) -> list[MergeCandidate]:
    """같은 std_code 안에서 weight_g 유사 + grade/package_type/sale_unit_norm 동일.

    `std_code` 지정 시 그 코드만; 미지정 시 전체.
    """
    q = select(ProductMaster)
    if std_code:
        q = q.where(ProductMaster.std_code == std_code)
    q = q.order_by(ProductMaster.std_code, ProductMaster.product_id)
    rows = list(session.execute(q).scalars().all())

    by_std: dict[str, list[ProductMaster]] = {}
    for r in rows:
        by_std.setdefault(r.std_code, []).append(r)

    candidates: list[MergeCandidate] = []
    for code, group in by_std.items():
        if len(group) < 2:
            continue
        # weight_g 가 비슷하고 grade/package_type/sale_unit_norm 이 같으면 같은 클러스터.
        clusters: list[list[ProductMaster]] = []
        for prod in group:
            placed = False
            for cluster in clusters:
                head = cluster[0]
                if (
                    (head.grade or "") == (prod.grade or "")
                    and (head.package_type or "") == (prod.package_type or "")
                    and (head.sale_unit_norm or "") == (prod.sale_unit_norm or "")
                    and _weight_close(head.weight_g, prod.weight_g)
                ):
                    cluster.append(prod)
                    placed = True
                    break
            if not placed:
                clusters.append([prod])
        for cluster in clusters:
            if len(cluster) >= 2:
                candidates.append(MergeCandidate(std_code=code, products=cluster))
    return candidates


def _weight_close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if a == 0 and b == 0:
        return True
    base = max(abs(float(a)), abs(float(b)))
    if base == 0:
        return True
    diff = abs(float(a) - float(b)) / base * 100.0
    return diff <= WEIGHT_TOLERANCE_PCT


# ---------------------------------------------------------------------------
# Merge 실행
# ---------------------------------------------------------------------------
def _mapping_count_for_products(session: Session, product_ids: Iterable[int]) -> dict[int, int]:
    ids = list(product_ids)
    if not ids:
        return {}
    rows = session.execute(
        text(
            "SELECT product_id, COUNT(*)::int AS cnt "
            "FROM mart.product_mapping "
            "WHERE product_id = ANY(:ids) "
            "GROUP BY product_id"
        ),
        {"ids": ids},
    ).all()
    return {int(r.product_id): int(r.cnt) for r in rows}


def _majority_count(values: list[Any]) -> tuple[Any, int, int]:
    """반환: (top_value, top_count, total). value 가 None 인 항목은 무시."""
    filtered = [v for v in values if v is not None]
    if not filtered:
        return (None, 0, 0)
    counts: dict[Any, int] = {}
    for v in filtered:
        counts[v] = counts.get(v, 0) + 1
    top = max(counts.items(), key=lambda kv: (kv[1], -hash(kv[0])))
    return (top[0], top[1], len(filtered))


def attempt_auto_merge(
    session: Session, *, candidate: MergeCandidate, merged_by: int | None = None
) -> MergeResult | None:
    """후보 그룹 1개 자동 머지. 분쟁 시 crowd_task 발급 후 None 반환.

    분쟁 조건:
      - 후보 row >= DISPUTE_ROW_THRESHOLD
      - grade/package_type 다수결 < DISPUTE_MAJORITY_PCT (즉 명확한 다수가 없음)
    """
    if not candidate.products:
        return None
    if len(candidate.products) < 2:
        return None

    # 분쟁 1: 5+ row.
    dispute = len(candidate.products) >= DISPUTE_ROW_THRESHOLD

    # 분쟁 2: grade 다수결 비율 < 50% (전체 중 가장 많은 값의 비중).
    if not dispute:
        grades = [p.grade for p in candidate.products if p.grade is not None]
        if grades:
            _top, top_count, total = _majority_count(grades)
            if total > 0 and (top_count / total * 100.0) < DISPUTE_MAJORITY_PCT:
                dispute = True

    if dispute:
        _create_crowd_task(session, candidate=candidate)
        return None

    # target 선택 — mapping count 가 가장 많은 product → tie 시 product_id 큰 쪽.
    counts = _mapping_count_for_products(
        session, (p.product_id for p in candidate.products)
    )
    sorted_products = sorted(
        candidate.products,
        key=lambda p: (counts.get(p.product_id, 0), p.product_id),
        reverse=True,
    )
    target = sorted_products[0]
    sources = [p for p in candidate.products if p.product_id != target.product_id]

    # canonical_name / 다수결.
    canonical_name = target.canonical_name
    name_top, _, _ = _majority_count([p.canonical_name for p in candidate.products])
    if name_top is not None:
        canonical_name = str(name_top)

    new_grade, _, _ = _majority_count([p.grade for p in candidate.products])
    new_package_type, _, _ = _majority_count(
        [p.package_type for p in candidate.products]
    )
    new_sale_unit, _, _ = _majority_count([p.sale_unit_norm for p in candidate.products])
    new_weight, _, _ = _majority_count([p.weight_g for p in candidate.products])

    # confidence_score = 후보들의 max.
    confs = [float(p.confidence_score) for p in candidate.products if p.confidence_score is not None]
    new_conf = max(confs) if confs else None

    target.canonical_name = canonical_name or target.canonical_name
    if new_grade is not None:
        target.grade = new_grade
    if new_package_type is not None:
        target.package_type = new_package_type
    if new_sale_unit is not None:
        target.sale_unit_norm = new_sale_unit
    if new_weight is not None:
        target.weight_g = float(new_weight)
    if new_conf is not None:
        target.confidence_score = new_conf
    target.last_seen_at = datetime.now(UTC)

    # product_mapping → target 으로 통합. product_master 의 unique key 충돌 회피 위해
    # 동일 매핑이 이미 존재하면 INSERT 안 함 (ON CONFLICT 없이 단순 UPDATE).
    source_ids = [p.product_id for p in sources]
    if source_ids:
        session.execute(
            text(
                "UPDATE mart.product_mapping "
                "SET product_id = :tgt "
                "WHERE product_id = ANY(:srcs)"
            ),
            {"tgt": target.product_id, "srcs": source_ids},
        )

    mapping_count_after = session.execute(
        text(
            "SELECT COUNT(*)::int FROM mart.product_mapping WHERE product_id = :tgt"
        ),
        {"tgt": target.product_id},
    ).scalar_one()

    # source product 삭제.
    if source_ids:
        session.execute(
            text("DELETE FROM mart.product_master WHERE product_id = ANY(:ids)"),
            {"ids": source_ids},
        )

    # master_merge_op 적재.
    op_row = MasterMergeOp(
        source_product_ids=[p.product_id for p in candidate.products],
        target_product_id=target.product_id,
        merged_by=merged_by,
        reason="auto",
        mapping_count=int(mapping_count_after),
    )
    session.add(op_row)
    session.flush()

    logger.info(
        "master_merge.applied target=%s sources=%s mapping=%s",
        target.product_id,
        source_ids,
        mapping_count_after,
    )
    return MergeResult(
        merge_op_id=op_row.merge_op_id,
        target_product_id=target.product_id,
        source_ids=source_ids,
        mapping_count=int(mapping_count_after),
        canonical_name=target.canonical_name,
    )


def _create_crowd_task(session: Session, *, candidate: MergeCandidate) -> None:
    """분쟁 시 PRODUCT_MATCHING crowd 작업 1건 발급 (`crowd.task` 직접 INSERT).

    같은 std_code 의 미해결 작업이 이미 있으면 skip — 운영자가 한 번에 처리.
    Phase 4.2.1 의 crowd 정식 스키마를 사용 — `run.crowd_task` 는 view 라 INSERT 불가.
    """
    existing = session.execute(
        text(
            "SELECT crowd_task_id FROM crowd.task "
            "WHERE task_kind = 'PRODUCT_MATCHING' "
            "  AND status IN ('PENDING','REVIEWING','CONFLICT') "
            "  AND payload->>'std_code' = :sc "
            "LIMIT 1"
        ),
        {"sc": candidate.std_code},
    ).scalar_one_or_none()
    if existing is not None:
        return
    payload = {
        "std_code": candidate.std_code,
        "candidates": [
            {
                "product_id": p.product_id,
                "canonical_name": p.canonical_name,
                "grade": p.grade,
                "package_type": p.package_type,
                "sale_unit_norm": p.sale_unit_norm,
                "weight_g": float(p.weight_g) if p.weight_g else None,
                "confidence_score": float(p.confidence_score) if p.confidence_score else None,
            }
            for p in candidate.products
        ],
    }
    session.execute(
        text(
            "INSERT INTO crowd.task "
            "(task_kind, priority, partition_date, payload, status) "
            "VALUES ('PRODUCT_MATCHING', 5, CURRENT_DATE, CAST(:p AS JSONB), "
            "        'PENDING')"
        ),
        {"p": _to_json(payload)},
    )


def _to_json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


def run_daily_auto_merge(
    session: Session, *, std_code: str | None = None, merged_by: int | None = None
) -> dict[str, int]:
    """매일 03:00 cron 진입점 — 후보 detect + 자동 머지 시도.

    반환: {candidates, merged, disputed}.
    """
    candidates = find_merge_candidates(session, std_code=std_code)
    merged = 0
    disputed = 0
    for cand in candidates:
        res = attempt_auto_merge(session, candidate=cand, merged_by=merged_by)
        if res is None:
            disputed += 1
        else:
            merged += 1
    return {"candidates": len(candidates), "merged": merged, "disputed": disputed}


# ---------------------------------------------------------------------------
# Un-merge
# ---------------------------------------------------------------------------
def unmerge_op(
    session: Session, *, merge_op_id: int, unmerged_by: int | None = None
) -> UnmergeResult:
    """잘못된 머지 1건 되돌림. source product 들을 새 product_id 로 재생성 후 mapping
    재분배.

    주의: 정확한 *어떤 mapping 이 어떤 source 였는지* 는 머지 시점에 보존하지 않음 →
    PoC 단계는 모든 product_mapping 을 새 product 로 *분배 안 함* (mapping 은 target
    그대로). 운영자가 frontend 에서 product_mapping 을 수동 재배치하거나, 후속에서
    snapshot 컬럼 추가 (ADR § 6).
    """
    op_row = session.get(MasterMergeOp, merge_op_id)
    if op_row is None:
        raise ValueError(f"merge_op {merge_op_id} not found")
    if op_row.is_unmerged:
        raise ValueError(f"merge_op {merge_op_id} already unmerged")

    target = session.get(ProductMaster, op_row.target_product_id)
    if target is None:
        raise ValueError(f"target product {op_row.target_product_id} not found")

    new_ids: list[int] = []
    # product_master 의 UNIQUE(std_code, grade, package_type, sale_unit_norm, weight_g)
    # 를 회피하기 위해 grade 에 unmerge 마커 부여 (target 과 구별).
    base_weight = float(target.weight_g) if target.weight_g else 0.0
    for offset_idx, src_id in enumerate(
        [s for s in (op_row.source_product_ids or []) if int(s) != op_row.target_product_id],
        start=1,
    ):
        new = ProductMaster(
            std_code=target.std_code,
            grade=f"{target.grade or ''}_unmerged_{src_id}",
            package_type=target.package_type,
            sale_unit_norm=target.sale_unit_norm,
            weight_g=base_weight + offset_idx * 0.01,
            canonical_name=f"{target.canonical_name} (unmerged from {src_id})",
            confidence_score=target.confidence_score,
        )
        session.add(new)
        session.flush()
        new_ids.append(new.product_id)

    op_row.is_unmerged = True
    op_row.unmerged_at = datetime.now(UTC)
    op_row.unmerged_by = unmerged_by
    return UnmergeResult(merge_op_id=merge_op_id, new_product_ids=new_ids)


__all__ = [
    "DISPUTE_MAJORITY_PCT",
    "DISPUTE_ROW_THRESHOLD",
    "WEIGHT_TOLERANCE_PCT",
    "MergeCandidate",
    "MergeResult",
    "UnmergeResult",
    "attempt_auto_merge",
    "find_merge_candidates",
    "run_daily_auto_merge",
    "unmerge_op",
]
