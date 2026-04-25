"""Transform 도메인 통합 테스트 — raw_object → standard_record + price_observation
+ outbox(staging.ready). 실 PG, mock embedding client.

trigram_hit / crowd 분기 각각 1건씩 (embedding_hit 는 standardization 테스트가 커버).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import delete, select, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.transform import process_record
from app.models.mart import StandardCode
from app.models.raw import RawObject
from app.models.run import CrowdTask, EventOutbox
from app.models.stg import PriceObservation, StandardRecord


@pytest.fixture
def cleanup_transform() -> Iterator[dict[str, list[object]]]:
    """삽입 항목들 정리. raw_object_id, std_code 추적."""
    holder: dict[str, list[object]] = {"raw": [], "std_code": []}
    yield holder
    if not (holder["raw"] or holder["std_code"]):
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for raw_id in holder["raw"]:
            assert isinstance(raw_id, int)
            # outbox: aggregate_id 가 `<raw_id>:<date>` 또는 crowd_task_id (정확히 매칭 어려움)
            session.execute(delete(EventOutbox).where(EventOutbox.aggregate_id.like(f"{raw_id}:%")))
            # crowd_task → outbox cascade 안 됨 — std_low_confidence 제거
            session.execute(
                delete(EventOutbox).where(EventOutbox.event_type == "crowd.task.created")
            )
            session.execute(delete(CrowdTask).where(CrowdTask.raw_object_id == raw_id))
            session.execute(
                delete(PriceObservation).where(PriceObservation.raw_object_id == raw_id)
            )
            session.execute(delete(StandardRecord).where(StandardRecord.raw_object_id == raw_id))
            session.execute(delete(RawObject).where(RawObject.raw_object_id == raw_id))
        for code in holder["std_code"]:
            assert isinstance(code, str)
            session.execute(delete(StandardCode).where(StandardCode.std_code == code))
        session.commit()
    dispose_sync_engine()


def _seed_source(session: object) -> int:
    src = session.execute(  # type: ignore[attr-defined]
        text("SELECT source_id FROM ctl.data_source ORDER BY source_id LIMIT 1")
    ).scalar_one_or_none()
    if src is None:
        pytest.skip("no ctl.data_source row — run prior IT tests / seed first")
    return int(src)


def _seed_raw_object(
    session: object,
    *,
    source_id: int,
    items: list[dict[str, object]],
) -> tuple[int, date]:
    pdate = date(2026, 4, 25)
    row = RawObject(
        source_id=source_id,
        object_type="JSON",
        object_uri=None,
        payload_json={"items": items},
        content_hash="tx-it-" + secrets.token_hex(8),
        status="RECEIVED",
        partition_date=pdate,
    )
    session.add(row)  # type: ignore[attr-defined]
    session.commit()  # type: ignore[attr-defined]
    return row.raw_object_id, pdate


# ---------------------------------------------------------------------------
# 1. trigram_hit 경로 — std_code 매핑 + price_observation.std_code 채워짐
# ---------------------------------------------------------------------------
def test_transform_creates_standard_record_with_trigram_match(
    cleanup_transform: dict[str, list[object]],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"IT-TX-{secrets.token_hex(4).upper()}"
    cleanup_transform["std_code"].append(code)

    with sm() as session:
        session.add(
            StandardCode(
                std_code=code,
                category_lv1="과일",
                item_name_ko="후지사과",
                aliases=["사과"],
                is_active=True,
            )
        )
        session.commit()

        src_id = _seed_source(session)
        raw_id, pdate = _seed_raw_object(
            session,
            source_id=src_id,
            items=[
                {"name": "후지 사과 5kg", "price": 24900, "unit": "box"},
                {"name": "후지 사과 3kg", "price": 14900, "unit": "box"},
            ],
        )
        cleanup_transform["raw"].append(raw_id)

    with sm() as session:
        outcome = process_record(
            session,
            raw_object_id=raw_id,
            partition_date=pdate,
            embedding_client=None,
            trigram_threshold=0.5,
            embedding_threshold=0.85,
        )
        session.commit()

    assert outcome.record_count == 2
    assert outcome.matched_count == 2
    assert outcome.crowd_task_count == 0

    with sm() as session:
        obs_rows = (
            session.execute(
                select(PriceObservation).where(PriceObservation.raw_object_id == raw_id)
            )
            .scalars()
            .all()
        )
        assert len(obs_rows) == 2
        assert all(r.std_code == code for r in obs_rows)
        assert all(r.std_confidence is not None for r in obs_rows)

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
        assert events[0].event_type == "staging.ready"
        payload = events[0].payload_json
        assert payload["matched_count"] == 2
        assert payload["crowd_task_count"] == 0
        assert payload["record_count"] == 2

        raw = session.execute(
            select(RawObject).where(RawObject.raw_object_id == raw_id)
        ).scalar_one()
        assert raw.status == "PROCESSED"


# ---------------------------------------------------------------------------
# 2. crowd 경로 — std_code 매핑 실패 → crowd_task 적재 + outbox 2건
# ---------------------------------------------------------------------------
def test_transform_creates_crowd_task_when_no_match(
    cleanup_transform: dict[str, list[object]],
) -> None:
    sm = get_sync_sessionmaker()

    with sm() as session:
        src_id = _seed_source(session)
        raw_id, pdate = _seed_raw_object(
            session,
            source_id=src_id,
            items=[{"name": "asdfqwerzxcv-no-match-it", "price": 1000}],
        )
        cleanup_transform["raw"].append(raw_id)

    with sm() as session:
        outcome = process_record(
            session,
            raw_object_id=raw_id,
            partition_date=pdate,
            embedding_client=None,  # 임베딩 비활성 → 즉시 crowd
            trigram_threshold=0.7,
            embedding_threshold=0.85,
        )
        session.commit()

    assert outcome.record_count == 1
    assert outcome.matched_count == 0
    assert outcome.crowd_task_count == 1

    with sm() as session:
        crowd = (
            session.execute(
                select(CrowdTask)
                .where(CrowdTask.raw_object_id == raw_id)
                .where(CrowdTask.reason == "std_low_confidence")
            )
            .scalars()
            .all()
        )
        assert len(crowd) == 1
        assert crowd[0].status == "PENDING"

        # outbox: staging.ready (1) + crowd.task.created (1)
        events = (
            session.execute(
                select(EventOutbox)
                .where(
                    (EventOutbox.aggregate_id == f"{raw_id}:{pdate.isoformat()}")
                    | (EventOutbox.aggregate_id == str(crowd[0].crowd_task_id))
                )
                .order_by(EventOutbox.event_id)
            )
            .scalars()
            .all()
        )
        types = sorted(e.event_type for e in events)
        assert types == ["crowd.task.created", "staging.ready"]
