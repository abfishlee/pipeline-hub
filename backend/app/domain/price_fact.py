"""가격 팩트 자동 반영 도메인 (Phase 2.2.6).

흐름:
  1. `staging.ready` 이벤트가 도착하면 같은 raw_object_id 의 `stg.price_observation`
     모든 row 를 읽는다.
  2. row 별 `std_confidence` 게이트:
     - ≥ 95 → mart 적재(insert)
     - 80 ~ 95 → mart 적재 + 5% 결정적 샘플링 → `crowd_task("price_fact_sample_review")` (sampled)
     - < 80 → 미적재 + `crowd_task("price_fact_low_confidence")` (held)
     - std_code NULL → skip (이미 표준화 단계에서 crowd_task 발급됨)
  3. mart 적재는 `retailer_master` → `seller_master` → `product_master` → `price_fact`
     순서로 manual upsert (NULLS DISTINCT 회피 위해 `_get_or_create_*` 헬퍼 사용).
  4. 마지막에 outbox(`price_fact.ready`) 발행 — 다운스트림 `price_daily_agg` Airflow
     DAG (Phase 2.2.3 후속) 가 사용.

호출자가 commit 책임 (`consume_idempotent` 가 트랜잭션 닫음).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as DateType
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import metrics
from app.models.mart import (
    PriceFact,
    ProductMaster,
    RetailerMaster,
    SellerMaster,
)
from app.models.run import CrowdTask, EventOutbox
from app.models.stg import PriceObservation

# 게이트 임계값 — std_confidence 는 0~100 스케일 (transform 도메인 / 0007 컬럼 정의 기준).
HIGH_CONFIDENCE = Decimal("95")
MID_CONFIDENCE = Decimal("80")
DEFAULT_SAMPLE_RATE = 0.05


@dataclass(slots=True, frozen=True)
class PriceFactOutcome:
    raw_object_id: int
    partition_date: DateType
    inserted_count: int
    sampled_count: int
    held_count: int
    skipped_count: int
    price_fact_ids: tuple[int, ...]


# ---------------------------------------------------------------------------
# upsert helpers — manual SELECT-then-INSERT (NULLS DISTINCT 회피).
# ---------------------------------------------------------------------------
def _get_or_create_retailer(session: Session, *, code: str | None) -> RetailerMaster:
    """retailer_code 로 조회. 없으면 INSERT (retailer_type 기본 'ONLINE')."""
    norm = (code or "UNKNOWN").strip() or "UNKNOWN"
    existing = session.execute(
        select(RetailerMaster).where(RetailerMaster.retailer_code == norm)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = RetailerMaster(
        retailer_code=norm,
        retailer_name=norm,
        retailer_type="ONLINE",  # 보수적 기본값. 운영자가 후속 보정.
    )
    session.add(row)
    session.flush()
    return row


def _seller_code_from(name: str | None) -> str:
    """seller_name → 결정적 seller_code (영문/숫자/`-` 만 64자, 부족하면 hash)."""
    base = (name or "unknown").strip() or "unknown"
    safe = "".join(c if c.isalnum() else "-" for c in base.lower())[:48]
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}" if safe != "-" else f"unknown-{digest}"


def _get_or_create_seller(session: Session, *, retailer_id: int, name: str | None) -> SellerMaster:
    code = _seller_code_from(name)
    existing = session.execute(
        select(SellerMaster).where(
            (SellerMaster.retailer_id == retailer_id) & (SellerMaster.seller_code == code)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = SellerMaster(
        retailer_id=retailer_id,
        seller_code=code,
        seller_name=name or "unknown",
        channel="ONLINE",
    )
    session.add(row)
    session.flush()
    return row


def _get_or_create_product(
    session: Session,
    *,
    std_code: str,
    grade: str | None,
    package_type: str | None,
    sale_unit_norm: str | None,
    weight_g: Decimal | None,
    canonical_name: str,
) -> ProductMaster:
    stmt = select(ProductMaster).where(ProductMaster.std_code == std_code)
    # NULLS DISTINCT 한계 회피 — IS NOT DISTINCT FROM 으로 NULL 도 동일 비교.
    if grade is None:
        stmt = stmt.where(ProductMaster.grade.is_(None))
    else:
        stmt = stmt.where(ProductMaster.grade == grade)
    if package_type is None:
        stmt = stmt.where(ProductMaster.package_type.is_(None))
    else:
        stmt = stmt.where(ProductMaster.package_type == package_type)
    if sale_unit_norm is None:
        stmt = stmt.where(ProductMaster.sale_unit_norm.is_(None))
    else:
        stmt = stmt.where(ProductMaster.sale_unit_norm == sale_unit_norm)
    if weight_g is None:
        stmt = stmt.where(ProductMaster.weight_g.is_(None))
    else:
        stmt = stmt.where(ProductMaster.weight_g == weight_g)

    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        return existing
    row = ProductMaster(
        std_code=std_code,
        grade=grade,
        package_type=package_type,
        sale_unit_norm=sale_unit_norm,
        weight_g=weight_g,
        canonical_name=canonical_name,
    )
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# sampling
# ---------------------------------------------------------------------------
def _is_sampled(obs_id: int, sample_rate: float) -> bool:
    """결정적 샘플링 — 같은 obs_id 는 항상 같은 결정. (테스트 재현성).

    obs_id sha256 첫 4 byte 를 0~1 로 정규화 후 sample_rate 비교.
    """
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    digest = hashlib.sha256(str(obs_id).encode("ascii")).digest()
    n = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return n < sample_rate


# ---------------------------------------------------------------------------
# 메인 함수
# ---------------------------------------------------------------------------
def propagate_price_fact(
    session: Session,
    *,
    raw_object_id: int,
    partition_date: DateType,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> PriceFactOutcome:
    obs_rows: Sequence[PriceObservation] = (
        session.execute(
            select(PriceObservation).where(PriceObservation.raw_object_id == raw_object_id)
        )
        .scalars()
        .all()
    )

    inserted_ids: list[int] = []
    sampled = 0
    held = 0
    skipped = 0
    now = datetime.now(UTC)

    for obs in obs_rows:
        if obs.std_code is None:
            skipped += 1
            metrics.price_fact_inserts_total.labels(outcome="skipped").inc()
            continue

        # std_confidence 는 NUMERIC(5,2). None 이면 0 으로 취급 → held.
        conf = Decimal(obs.std_confidence) if obs.std_confidence is not None else Decimal(0)

        if conf < MID_CONFIDENCE:
            held += 1
            metrics.price_fact_inserts_total.labels(outcome="held").inc()
            session.add(
                CrowdTask(
                    raw_object_id=raw_object_id,
                    partition_date=partition_date,
                    ocr_result_id=None,
                    reason="price_fact_low_confidence",
                    status="PENDING",
                    payload_json={
                        "obs_id": obs.obs_id,
                        "std_code": obs.std_code,
                        "std_confidence": str(conf),
                        "product_name_raw": obs.product_name_raw,
                    },
                )
            )
            metrics.crowd_task_created_total.labels(reason="price_fact_low_confidence").inc()
            continue

        # ≥ 80 — 적재.
        retailer = _get_or_create_retailer(session, code=obs.retailer_code)
        seller = _get_or_create_seller(
            session, retailer_id=retailer.retailer_id, name=obs.seller_name
        )
        product = _get_or_create_product(
            session,
            std_code=obs.std_code,
            grade=obs.grade,
            package_type=obs.package_type,
            sale_unit_norm=obs.sale_unit,
            weight_g=Decimal(obs.weight_g) if obs.weight_g is not None else None,
            canonical_name=obs.product_name_raw,
        )

        fact = PriceFact(
            product_id=product.product_id,
            seller_id=seller.seller_id,
            observed_at=obs.observed_at,
            price_krw=Decimal(obs.price_krw),
            discount_price_krw=(
                Decimal(obs.discount_price_krw) if obs.discount_price_krw is not None else None
            ),
            source_id=obs.source_id,
            raw_object_id=raw_object_id,
            partition_date=partition_date,
        )
        session.add(fact)
        session.flush()  # price_id 채움.
        inserted_ids.append(fact.price_id)

        latency = max(0.0, (now - obs.observed_at).total_seconds())
        metrics.price_fact_observed_to_inserted_seconds.observe(latency)

        # 80~95 게이트 → 5% sampling 검수.
        if conf < HIGH_CONFIDENCE and _is_sampled(obs.obs_id, sample_rate):
            sampled += 1
            metrics.price_fact_inserts_total.labels(outcome="sampled").inc()
            session.add(
                CrowdTask(
                    raw_object_id=raw_object_id,
                    partition_date=partition_date,
                    ocr_result_id=None,
                    reason="price_fact_sample_review",
                    status="PENDING",
                    payload_json={
                        "obs_id": obs.obs_id,
                        "price_id": fact.price_id,
                        "std_confidence": str(conf),
                    },
                )
            )
            metrics.crowd_task_created_total.labels(reason="price_fact_sample_review").inc()
        else:
            metrics.price_fact_inserts_total.labels(outcome="insert").inc()

    # crowd_task 들 → outbox (held + sampled). 별도 SELECT 로 본 함수에서 적재한 것만.
    new_crowd: Sequence[CrowdTask] = [
        obj
        for obj in session.new
        if isinstance(obj, CrowdTask)
        and obj.reason in ("price_fact_low_confidence", "price_fact_sample_review")
    ]
    session.flush()
    for ct in new_crowd:
        session.add(
            EventOutbox(
                aggregate_type="crowd_task",
                aggregate_id=str(ct.crowd_task_id),
                event_type="crowd.task.created",
                payload_json={
                    "crowd_task_id": ct.crowd_task_id,
                    "raw_object_id": raw_object_id,
                    "partition_date": partition_date.isoformat(),
                    "ocr_result_id": None,
                    "reason": ct.reason,
                    "status": "PENDING",
                },
            )
        )

    # price_fact.ready outbox — 다운스트림 daily_agg DAG 트리거.
    session.add(
        EventOutbox(
            aggregate_type="price_fact",
            aggregate_id=f"{raw_object_id}:{partition_date.isoformat()}",
            event_type="price_fact.ready",
            payload_json={
                "raw_object_id": raw_object_id,
                "partition_date": partition_date.isoformat(),
                "inserted_count": len(inserted_ids),
                "sampled_count": sampled,
                "held_count": held,
                "skipped_count": skipped,
                "price_fact_ids": list(inserted_ids),
            },
        )
    )

    return PriceFactOutcome(
        raw_object_id=raw_object_id,
        partition_date=partition_date,
        inserted_count=len(inserted_ids),
        sampled_count=sampled,
        held_count=held,
        skipped_count=skipped,
        price_fact_ids=tuple(inserted_ids),
    )


__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "HIGH_CONFIDENCE",
    "MID_CONFIDENCE",
    "PriceFactOutcome",
    "propagate_price_fact",
]
