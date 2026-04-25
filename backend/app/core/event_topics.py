"""도메인 이벤트 토픽 정의 + payload 모델 (Phase 2.2.2).

Redis Streams 의 stream key 와 message fields 를 타입 안전하게 다루기 위한
중간 계층. Outbox publisher 가 발행한 fields 와 1:1 정합.

Phase 2 시작은 `raw_object` 1개 토픽만 정의. ocr/standardization/transform/dq
등은 각 단계 추가 시 함께 정의 (`docs/02_ARCHITECTURE.md` 2.9 참조).
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventTopic(StrEnum):
    """Redis Streams stream key 의 aggregate_type 부분.

    실제 stream key = `<settings.redis_streams_prefix>:<topic>` (예: `dp:events:raw_object`).
    """

    RAW_OBJECT = "raw_object"
    OCR_RESULT = "ocr_result"
    CROWD_TASK = "crowd_task"
    PRICE_OBSERVATION = "price_observation"
    STAGING = "staging"
    PRICE_FACT = "price_fact"


class StreamEnvelope(BaseModel):
    """Outbox publisher 가 XADD 할 때 쓰는 공통 봉투.

    fields 는 Redis Streams 가 string-only flat dict 라 dict/list 값은 JSON 직렬화
    됨 (publisher 측). 여기서는 deserialize 후 pydantic 으로 검증.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    aggregate_type: str = Field(min_length=1)
    aggregate_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RawObjectCreatedPayload(BaseModel):
    """`raw_object.created` 이벤트의 payload 부분.

    Phase 1.2.7 에서 outbox 에 적재되는 JSON 과 1:1. 새 필드는 backwards-compatible
    하게 추가 — `model_config.extra = "ignore"` 로 unknown 키 허용.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    raw_object_id: int
    partition_date: str  # YYYY-MM-DD
    source_id: int
    content_hash: str  # hex-encoded SHA-256
    object_uri: str | None = None
    bytes_size: int = 0


class OcrCompletedPayload(BaseModel):
    """`ocr.completed` 이벤트의 payload — Phase 2.2.4 OCR 파이프라인 결과."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    raw_object_id: int
    partition_date: str
    ocr_result_ids: list[int]
    page_count: int
    avg_confidence: float
    provider: str  # 'clova' | 'upstage'
    engine_version: str | None = None
    duration_ms: int = 0
    crowd_task_id: int | None = None  # < 0.85 시 함께 발급된 placeholder.


class CrowdTaskCreatedPayload(BaseModel):
    """`crowd.task.created` 이벤트의 payload — Phase 2.2.4 검수 placeholder."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    crowd_task_id: int
    raw_object_id: int
    partition_date: str
    ocr_result_id: int | None = None
    reason: str
    status: str = "PENDING"


class StagingReadyPayload(BaseModel):
    """`staging.ready` 이벤트의 payload — Phase 2.2.5 표준화 후 다운스트림 준비 완료.

    `record_count` 는 standard_record / price_observation 적재 행수 (둘 다 같음).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    raw_object_id: int
    partition_date: str
    record_count: int
    price_observation_count: int
    standard_record_ids: list[int] = Field(default_factory=list)
    price_observation_ids: list[int] = Field(default_factory=list)
    matched_count: int = 0  # std_code 매핑된 record 수.
    crowd_task_count: int = 0  # 매핑 미달로 발급된 crowd_task 수.


class PriceFactReadyPayload(BaseModel):
    """`price_fact.ready` 이벤트 — Phase 2.2.6 가격 팩트 적재 결과.

    confidence 게이트 outcome 별 카운트. inserted+sampled+held+skipped == 처리 시도 row 수.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    raw_object_id: int
    partition_date: str
    inserted_count: int = 0  # std_confidence ≥ 95 또는 80~95 모두 INSERT.
    sampled_count: int = 0  # 80~95 + 5% 샘플링 → crowd_task("price_fact_sample_review").
    held_count: int = 0  # < 80 → INSERT 없이 crowd_task("price_fact_low_confidence").
    skipped_count: int = 0  # std_code NULL — 이미 표준화 단계에서 crowd_task 발급됨.
    price_fact_ids: list[int] = Field(default_factory=list)


def parse_message(fields: dict[str, str]) -> StreamEnvelope:
    """Stream message fields → 타입화 envelope.

    fields["payload"] 는 JSON string 이므로 dict 로 역직렬화. 다른 키도 동일.
    """
    raw_payload = fields.get("payload", "{}")
    try:
        payload_obj: Any = json.loads(raw_payload) if raw_payload else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid payload json: {exc}") from exc
    if not isinstance(payload_obj, dict):
        raise ValueError(f"payload must be json object, got {type(payload_obj).__name__}")

    occurred = fields.get("occurred_at") or None
    return StreamEnvelope(
        event_id=fields.get("event_id", ""),
        aggregate_type=fields.get("aggregate_type", ""),
        aggregate_id=fields.get("aggregate_id", ""),
        event_type=fields.get("event_type", ""),
        occurred_at=datetime.fromisoformat(occurred) if occurred else None,
        payload=payload_obj,
    )


__all__ = [
    "CrowdTaskCreatedPayload",
    "EventTopic",
    "OcrCompletedPayload",
    "PriceFactReadyPayload",
    "RawObjectCreatedPayload",
    "StagingReadyPayload",
    "StreamEnvelope",
    "parse_message",
]
