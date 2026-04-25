"""OCR 도메인 통합 테스트 — 실 PG, 모킹된 OCR provider + ObjectStorage.

CLOVA / Upstage 실 호출은 비싸고 외부 의존이라 stub. domain 자체의 분기 로직(threshold,
crowd_task placeholder, outbox 적재) 만 검증.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.core.events import RedisStreamPublisher
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.ocr import process_receipt
from app.integrations.ocr.types import OcrError, OcrPage, OcrResponse
from app.models.raw import OcrResult, RawObject
from app.models.run import CrowdTask, EventOutbox


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------
class _StubStorage:
    bucket = "stub-bucket"
    uri_scheme = "s3"

    def __init__(self, payload: bytes = b"\x89PNG-stub") -> None:
        self._payload = payload

    async def get_bytes(self, key: str) -> bytes:
        return self._payload

    def object_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    # 본 테스트는 read-only — 나머지 ObjectStorage 메서드는 호출되지 않음.
    async def put(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def put_stream(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def presigned_put(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def presigned_get(self, *_a: object, **_kw: object) -> str:  # pragma: no cover
        raise NotImplementedError

    async def exists(self, *_a: object, **_kw: object) -> bool:  # pragma: no cover
        return True

    async def delete(self, *_a: object, **_kw: object) -> bool:  # pragma: no cover
        return True

    async def ping(self, *_a: object, **_kw: object) -> bool:  # pragma: no cover
        return True


class _StubProvider:
    def __init__(self, *, name: str, confidence: float, fail: bool = False) -> None:
        self.name = name
        self._confidence = confidence
        self._fail = fail
        self.calls = 0

    async def recognize(self, **_kw: Any) -> OcrResponse:
        self.calls += 1
        if self._fail:
            raise OcrError(f"{self.name} stub failure")
        return OcrResponse(
            provider=self.name,
            engine_version="stub-v1",
            pages=(
                OcrPage(
                    page_no=1,
                    text="사과 5kg 24,900원",
                    confidence=self._confidence,
                    layout={"fields": []},
                ),
            ),
            duration_ms=120,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cleanup_raw() -> Iterator[list[tuple[int, date]]]:
    """삽입한 raw_object PK 와 그에 딸린 ocr_result/crowd_task/outbox 정리."""
    keys: list[tuple[int, date]] = []
    yield keys
    if not keys:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        for raw_id, pdate in keys:
            session.execute(
                delete(EventOutbox).where(
                    EventOutbox.aggregate_id.in_(
                        [
                            f"{raw_id}:{pdate.isoformat()}",
                            # crowd_task 발급 시 aggregate_id = crowd_task_id 였음 — pattern match 어려워
                            # 별도 정리.
                        ]
                    )
                )
            )
            session.execute(
                delete(EventOutbox).where(EventOutbox.event_type == "crowd.task.created")
            )
            session.execute(delete(CrowdTask).where(CrowdTask.raw_object_id == raw_id))
            session.execute(delete(OcrResult).where(OcrResult.raw_object_id == raw_id))
            session.execute(delete(RawObject).where(RawObject.raw_object_id == raw_id))
        session.commit()
    dispose_sync_engine()


def _seed_raw_object(session: object, *, source_id: int) -> tuple[int, date]:
    """raw_object 1건 (RECEIPT_IMAGE) 적재. source_id 는 ctl.data_source 의 실 PK."""
    import secrets

    pdate = date(2026, 4, 25)
    row = RawObject(
        source_id=source_id,
        object_type="RECEIPT_IMAGE",
        object_uri="s3://stub-bucket/receipts/test-key.jpg",
        content_hash="ocr-it-" + secrets.token_hex(8),
        status="RECEIVED",
        partition_date=pdate,
    )
    session.add(row)  # type: ignore[attr-defined]
    session.commit()  # type: ignore[attr-defined]
    return row.raw_object_id, pdate


# ---------------------------------------------------------------------------
# 1. confidence ≥ threshold 경로
# ---------------------------------------------------------------------------
def test_high_confidence_path_emits_ocr_completed_only(
    cleanup_raw: list[tuple[int, date]],
) -> None:
    sm = get_sync_sessionmaker()

    with sm() as session:
        # 1번 source 가 ctl.data_source 에 있어야 외래키 통과 — seed 없으면 스킵.
        from sqlalchemy import text

        ids = session.execute(
            text("SELECT source_id FROM ctl.data_source ORDER BY source_id LIMIT 1")
        ).scalar_one_or_none()
        if ids is None:
            pytest.skip("no ctl.data_source row — run prior IT tests / seed first")
        raw_id, pdate = _seed_raw_object(session, source_id=int(ids))
        cleanup_raw.append((raw_id, pdate))

    with sm() as session:
        publisher = RedisStreamPublisher.from_settings()
        try:
            outcome = process_receipt(
                session,
                publisher,
                _StubStorage(),  # type: ignore[arg-type]
                [_StubProvider(name="clova", confidence=0.95)],
                raw_object_id=raw_id,
                partition_date=pdate,
                confidence_threshold=0.85,
            )
            session.commit()
        finally:
            publisher.close()

    assert outcome.provider == "clova"
    assert outcome.page_count == 1
    assert outcome.crowd_task_id is None
    assert abs(outcome.avg_confidence - 0.95) < 1e-6

    with sm() as session:
        ocr_rows = (
            session.execute(select(OcrResult).where(OcrResult.raw_object_id == raw_id))
            .scalars()
            .all()
        )
        assert len(ocr_rows) == 1
        assert float(ocr_rows[0].confidence_score or 0) == pytest.approx(95.0)
        assert ocr_rows[0].engine_name == "clova"

        outbox_events = (
            session.execute(
                select(EventOutbox).where(
                    EventOutbox.aggregate_id == f"{raw_id}:{pdate.isoformat()}"
                )
            )
            .scalars()
            .all()
        )
        assert len(outbox_events) == 1
        assert outbox_events[0].event_type == "ocr.completed"

        crowd = (
            session.execute(select(CrowdTask).where(CrowdTask.raw_object_id == raw_id))
            .scalars()
            .all()
        )
        assert crowd == []

        raw = session.execute(
            select(RawObject).where(RawObject.raw_object_id == raw_id)
        ).scalar_one()
        assert raw.status == "PROCESSED"


# ---------------------------------------------------------------------------
# 2. confidence < threshold 경로 → crowd_task placeholder
# ---------------------------------------------------------------------------
def test_low_confidence_path_creates_crowd_task_and_two_outbox(
    cleanup_raw: list[tuple[int, date]],
) -> None:
    sm = get_sync_sessionmaker()
    from sqlalchemy import text

    with sm() as session:
        src_id = session.execute(
            text("SELECT source_id FROM ctl.data_source ORDER BY source_id LIMIT 1")
        ).scalar_one_or_none()
        if src_id is None:
            pytest.skip("no ctl.data_source row — run prior IT tests / seed first")
        raw_id, pdate = _seed_raw_object(session, source_id=int(src_id))
        cleanup_raw.append((raw_id, pdate))

    with sm() as session:
        publisher = RedisStreamPublisher.from_settings()
        try:
            outcome = process_receipt(
                session,
                publisher,
                _StubStorage(),  # type: ignore[arg-type]
                [_StubProvider(name="clova", confidence=0.50)],
                raw_object_id=raw_id,
                partition_date=pdate,
                confidence_threshold=0.85,
            )
            session.commit()
        finally:
            publisher.close()

    assert outcome.crowd_task_id is not None
    assert outcome.avg_confidence == pytest.approx(0.50)

    with sm() as session:
        crowd = session.execute(
            select(CrowdTask).where(CrowdTask.raw_object_id == raw_id)
        ).scalar_one()
        assert crowd.status == "PENDING"
        assert crowd.reason == "ocr_low_confidence"
        assert crowd.payload_json["provider"] == "clova"

        # outbox 2건: ocr.completed + crowd.task.created.
        events = (
            session.execute(
                select(EventOutbox)
                .where(
                    (EventOutbox.aggregate_id == f"{raw_id}:{pdate.isoformat()}")
                    | (EventOutbox.aggregate_id == str(outcome.crowd_task_id))
                )
                .order_by(EventOutbox.event_id)
            )
            .scalars()
            .all()
        )
        types = sorted(e.event_type for e in events)
        assert types == ["crowd.task.created", "ocr.completed"]


# ---------------------------------------------------------------------------
# 3. CLOVA 실패 → Upstage 폴백 성공
# ---------------------------------------------------------------------------
def test_provider_fallback_on_clova_failure(
    cleanup_raw: list[tuple[int, date]],
) -> None:
    sm = get_sync_sessionmaker()
    from sqlalchemy import text

    with sm() as session:
        src_id = session.execute(
            text("SELECT source_id FROM ctl.data_source ORDER BY source_id LIMIT 1")
        ).scalar_one_or_none()
        if src_id is None:
            pytest.skip("no ctl.data_source row — run prior IT tests / seed first")
        raw_id, pdate = _seed_raw_object(session, source_id=int(src_id))
        cleanup_raw.append((raw_id, pdate))

    clova = _StubProvider(name="clova", confidence=0.99, fail=True)
    upstage = _StubProvider(name="upstage", confidence=0.90)

    with sm() as session:
        publisher = RedisStreamPublisher.from_settings()
        try:
            outcome = process_receipt(
                session,
                publisher,
                _StubStorage(),  # type: ignore[arg-type]
                [clova, upstage],
                raw_object_id=raw_id,
                partition_date=pdate,
                confidence_threshold=0.85,
            )
            session.commit()
        finally:
            publisher.close()

    assert clova.calls == 1
    assert upstage.calls == 1
    assert outcome.provider == "upstage"
    assert outcome.crowd_task_id is None
