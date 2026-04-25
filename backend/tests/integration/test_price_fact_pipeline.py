"""price_fact 도메인 통합 테스트 — confidence 게이트 4분기 + product_master idempotency.

stg.price_observation 시드 → propagate_price_fact → mart.{retailer,seller,product}
upsert + price_fact INSERT (또는 보류) + crowd_task placeholder + outbox(price_fact.ready).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.price_fact import propagate_price_fact
from app.models.mart import (
    PriceFact,
    ProductMaster,
    RetailerMaster,
    SellerMaster,
    StandardCode,
)
from app.models.run import CrowdTask, EventOutbox
from app.models.stg import PriceObservation


# ---------------------------------------------------------------------------
# Fixtures — 정리 일괄
# ---------------------------------------------------------------------------
@pytest.fixture
def cleanup_price_fact() -> Iterator[dict[str, list[object]]]:
    """삽입 항목 한 번에 정리. 외래키 순서: price_fact → obs → product_master →
    seller_master → retailer_master → standard_code.
    """
    holder: dict[str, list[object]] = {
        "raw_object_id": [],  # cleanup price_fact / obs / outbox / crowd_task
        "retailer_id": [],
        "std_code": [],
    }
    yield holder
    if not (holder["raw_object_id"] or holder["retailer_id"] or holder["std_code"]):
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for raw_id in holder["raw_object_id"]:
            assert isinstance(raw_id, int)
            session.execute(delete(EventOutbox).where(EventOutbox.aggregate_id.like(f"{raw_id}:%")))
            session.execute(
                delete(EventOutbox).where(EventOutbox.event_type == "crowd.task.created")
            )
            session.execute(delete(CrowdTask).where(CrowdTask.raw_object_id == raw_id))
            session.execute(delete(PriceFact).where(PriceFact.raw_object_id == raw_id))
            session.execute(
                delete(PriceObservation).where(PriceObservation.raw_object_id == raw_id)
            )
        # product_master 는 std_code 참조 → std_code 정리 전에 먼저.
        for code in holder["std_code"]:
            assert isinstance(code, str)
            session.execute(delete(ProductMaster).where(ProductMaster.std_code == code))
        for rid in holder["retailer_id"]:
            assert isinstance(rid, int)
            session.execute(delete(SellerMaster).where(SellerMaster.retailer_id == rid))
            session.execute(delete(RetailerMaster).where(RetailerMaster.retailer_id == rid))
        for code in holder["std_code"]:
            assert isinstance(code, str)
            session.execute(delete(StandardCode).where(StandardCode.std_code == code))
        session.commit()
    dispose_sync_engine()


def _seed_source_id(session: object) -> int:
    src = session.execute(  # type: ignore[attr-defined]
        text("SELECT source_id FROM ctl.data_source ORDER BY source_id LIMIT 1")
    ).scalar_one_or_none()
    if src is None:
        pytest.skip("no ctl.data_source row — run prior IT tests / seed first")
    return int(src)


def _seed_std_code(session: object, *, holder: dict[str, list[object]]) -> str:
    code = f"IT-PF-{secrets.token_hex(4).upper()}"
    holder["std_code"].append(code)
    session.add(  # type: ignore[attr-defined]
        StandardCode(
            std_code=code,
            category_lv1="과일",
            item_name_ko=f"테스트품목-{code[-4:]}",
            aliases=[],
            is_active=True,
        )
    )
    session.commit()  # type: ignore[attr-defined]
    return code


def _seed_observation(
    session: object,
    *,
    source_id: int,
    raw_object_id: int,
    std_code: str | None,
    std_confidence: Decimal | None,
    obs_id_seed: int,
) -> PriceObservation:
    obs = PriceObservation(
        source_id=source_id,
        raw_object_id=raw_object_id,
        raw_partition=date(2026, 4, 25),
        retailer_code=f"IT-RTL-{obs_id_seed}",
        seller_name=f"IT 판매자 {obs_id_seed}",
        product_name_raw=f"테스트 상품 {obs_id_seed}",
        std_code=std_code,
        std_confidence=std_confidence,
        sale_unit="ea",
        price_krw=Decimal("12345.67"),
        currency="KRW",
        observed_at=datetime.now(UTC),
        standardized_at=datetime.now(UTC) if std_code else None,
    )
    session.add(obs)  # type: ignore[attr-defined]
    session.commit()  # type: ignore[attr-defined]
    return obs


# ---------------------------------------------------------------------------
# 1. ≥ 95 단순 INSERT + product_master/seller/retailer upsert idempotent
# ---------------------------------------------------------------------------
def test_high_confidence_inserts_price_fact_and_upserts_master(
    cleanup_price_fact: dict[str, list[object]],
) -> None:
    sm = get_sync_sessionmaker()
    raw_id = 9_900_001
    cleanup_price_fact["raw_object_id"].append(raw_id)
    pdate = date(2026, 4, 25)

    with sm() as session:
        src_id = _seed_source_id(session)
        std_code = _seed_std_code(session, holder=cleanup_price_fact)
        # 같은 (retailer_code, seller_name, std_code) 로 2건 시드 — upsert idempotent 검증.
        _seed_observation(
            session,
            source_id=src_id,
            raw_object_id=raw_id,
            std_code=std_code,
            std_confidence=Decimal("98.50"),
            obs_id_seed=1,
        )
        _seed_observation(
            session,
            source_id=src_id,
            raw_object_id=raw_id,
            std_code=std_code,
            std_confidence=Decimal("99.00"),
            obs_id_seed=1,  # 같은 retailer/seller 로 충돌
        )

    with sm() as session:
        outcome = propagate_price_fact(
            session,
            raw_object_id=raw_id,
            partition_date=pdate,
            sample_rate=0.0,  # sampling 끔 — 95+ 라 어차피 무관.
        )
        session.commit()

    assert outcome.inserted_count == 2
    assert outcome.sampled_count == 0
    assert outcome.held_count == 0
    assert outcome.skipped_count == 0

    with sm() as session:
        # product_master / retailer_master / seller_master 각 1행만.
        prods = (
            session.execute(
                select(ProductMaster).where(
                    ProductMaster.std_code.in_(
                        [s for s in cleanup_price_fact["std_code"] if isinstance(s, str)]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(prods) == 1

        rtl = session.execute(
            select(RetailerMaster).where(RetailerMaster.retailer_code == "IT-RTL-1")
        ).scalar_one()
        cleanup_price_fact["retailer_id"].append(rtl.retailer_id)

        sellers = (
            session.execute(select(SellerMaster).where(SellerMaster.retailer_id == rtl.retailer_id))
            .scalars()
            .all()
        )
        assert len(sellers) == 1

        facts = (
            session.execute(select(PriceFact).where(PriceFact.raw_object_id == raw_id))
            .scalars()
            .all()
        )
        assert len(facts) == 2
        assert all(f.product_id == prods[0].product_id for f in facts)

        # outbox: price_fact.ready 1건. crowd_task 0건 → outbox 도 0.
        events = (
            session.execute(
                select(EventOutbox).where(
                    EventOutbox.aggregate_id == f"{raw_id}:{pdate.isoformat()}"
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "price_fact.ready"
        assert events[0].payload_json["inserted_count"] == 2


# ---------------------------------------------------------------------------
# 2. 80 ~ 95 — INSERT + sample_rate=1.0 강제 sampling 시 모두 sample crowd_task
# ---------------------------------------------------------------------------
def test_mid_confidence_with_full_sampling_creates_sample_crowd_tasks(
    cleanup_price_fact: dict[str, list[object]],
) -> None:
    sm = get_sync_sessionmaker()
    raw_id = 9_900_002
    cleanup_price_fact["raw_object_id"].append(raw_id)
    pdate = date(2026, 4, 25)

    with sm() as session:
        src_id = _seed_source_id(session)
        std_code = _seed_std_code(session, holder=cleanup_price_fact)
        _seed_observation(
            session,
            source_id=src_id,
            raw_object_id=raw_id,
            std_code=std_code,
            std_confidence=Decimal("85.00"),
            obs_id_seed=2,
        )

    with sm() as session:
        outcome = propagate_price_fact(
            session,
            raw_object_id=raw_id,
            partition_date=pdate,
            sample_rate=1.0,  # 100% sampling
        )
        session.commit()

    assert outcome.inserted_count == 1
    assert outcome.sampled_count == 1
    assert outcome.held_count == 0

    with sm() as session:
        crowds = (
            session.execute(
                select(CrowdTask)
                .where(CrowdTask.raw_object_id == raw_id)
                .where(CrowdTask.reason == "price_fact_sample_review")
            )
            .scalars()
            .all()
        )
        assert len(crowds) == 1

        events = (
            session.execute(
                select(EventOutbox).where(EventOutbox.event_type == "crowd.task.created")
            )
            .scalars()
            .all()
        )
        assert any(e.payload_json.get("reason") == "price_fact_sample_review" for e in events)

        rtl = session.execute(
            select(RetailerMaster).where(RetailerMaster.retailer_code == "IT-RTL-2")
        ).scalar_one_or_none()
        if rtl is not None:
            cleanup_price_fact["retailer_id"].append(rtl.retailer_id)


# ---------------------------------------------------------------------------
# 3. < 80 — held: price_fact 미적재 + crowd_task("price_fact_low_confidence")
# ---------------------------------------------------------------------------
def test_low_confidence_holds_and_creates_crowd_task(
    cleanup_price_fact: dict[str, list[object]],
) -> None:
    sm = get_sync_sessionmaker()
    raw_id = 9_900_003
    cleanup_price_fact["raw_object_id"].append(raw_id)
    pdate = date(2026, 4, 25)

    with sm() as session:
        src_id = _seed_source_id(session)
        std_code = _seed_std_code(session, holder=cleanup_price_fact)
        _seed_observation(
            session,
            source_id=src_id,
            raw_object_id=raw_id,
            std_code=std_code,
            std_confidence=Decimal("70.00"),
            obs_id_seed=3,
        )

    with sm() as session:
        outcome = propagate_price_fact(
            session,
            raw_object_id=raw_id,
            partition_date=pdate,
        )
        session.commit()

    assert outcome.inserted_count == 0
    assert outcome.held_count == 1
    assert outcome.sampled_count == 0

    with sm() as session:
        facts = (
            session.execute(select(PriceFact).where(PriceFact.raw_object_id == raw_id))
            .scalars()
            .all()
        )
        assert facts == []

        crowds = (
            session.execute(
                select(CrowdTask)
                .where(CrowdTask.raw_object_id == raw_id)
                .where(CrowdTask.reason == "price_fact_low_confidence")
            )
            .scalars()
            .all()
        )
        assert len(crowds) == 1
        assert crowds[0].status == "PENDING"


# ---------------------------------------------------------------------------
# 4. std_code = NULL — 즉시 skipped (이미 transform 단계에서 crowd_task 발급됨)
# ---------------------------------------------------------------------------
def test_null_std_code_is_skipped(
    cleanup_price_fact: dict[str, list[object]],
) -> None:
    sm = get_sync_sessionmaker()
    raw_id = 9_900_004
    cleanup_price_fact["raw_object_id"].append(raw_id)
    pdate = date(2026, 4, 25)

    with sm() as session:
        src_id = _seed_source_id(session)
        _seed_observation(
            session,
            source_id=src_id,
            raw_object_id=raw_id,
            std_code=None,
            std_confidence=None,
            obs_id_seed=4,
        )

    with sm() as session:
        outcome = propagate_price_fact(
            session,
            raw_object_id=raw_id,
            partition_date=pdate,
        )
        session.commit()

    assert outcome.skipped_count == 1
    assert outcome.inserted_count == 0
    assert outcome.held_count == 0

    with sm() as session:
        crowds = (
            session.execute(
                select(CrowdTask)
                .where(CrowdTask.raw_object_id == raw_id)
                .where(CrowdTask.reason.startswith("price_fact"))
            )
            .scalars()
            .all()
        )
        assert crowds == []  # transform 이 발급할 std_low_confidence 와 무관.

        events = (
            session.execute(
                select(EventOutbox).where(
                    EventOutbox.aggregate_id == f"{raw_id}:{pdate.isoformat()}"
                )
            )
            .scalars()
            .all()
        )
        # price_fact.ready 만 발행 (skipped_count=1).
        assert len(events) == 1
        assert events[0].event_type == "price_fact.ready"
        assert events[0].payload_json["skipped_count"] == 1
