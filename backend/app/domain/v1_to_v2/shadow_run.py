"""Shadow Run dual-path 비교 (Q1, Q4 답변).

흐름:
  1. v1 endpoint 가 응답을 만들고, 이미 응답 직후 caller 가 본 모듈에 (request_kind,
     request_key, v1_payload, v2_payload) 전달.
  2. 본 모듈이 두 payload 의 *canonical hash* 비교 → 동일하면 'identical_skipped'
     (적재 X), 다르면 audit.shadow_diff 에 1행 INSERT.
  3. (Q4) 임계값 가드 — shadow_diff 의 *지난 1시간 mismatch ratio* 가 임계 초과 시
     application 이 alert + cutover_block.

본 모듈은 *비교 + 적재* 만 담당. alert 발송은 별도 worker.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


VALID_DIFF_KINDS: Final[tuple[str, ...]] = (
    "identical_skipped",
    "row_count_mismatch",
    "value_mismatch",
    "schema_mismatch",
    "v1_only",
    "v2_only",
    "exception",
    "other",
)


@dataclass(slots=True)
class ShadowDiffOutcome:
    diff_kind: str
    v1_hash: str | None
    v2_hash: str | None
    inserted: bool
    diff_id: int | None = None


def _canonical_hash(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value
    else:
        normalized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def diff_kind_for(
    v1_payload: Any,
    v2_payload: Any,
) -> str:
    """v1/v2 payload 만 보고 diff_kind 결정."""
    if v1_payload is None and v2_payload is None:
        return "identical_skipped"
    if v1_payload is None:
        return "v2_only"
    if v2_payload is None:
        return "v1_only"
    if _canonical_hash(v1_payload) == _canonical_hash(v2_payload):
        return "identical_skipped"
    # row count 비교 — list 형태 한정.
    if (
        isinstance(v1_payload, list)
        and isinstance(v2_payload, list)
        and len(v1_payload) != len(v2_payload)
    ):
        return "row_count_mismatch"
    # schema 비교 — dict key set.
    if (
        isinstance(v1_payload, dict)
        and isinstance(v2_payload, dict)
        and set(v1_payload.keys()) != set(v2_payload.keys())
    ):
        return "schema_mismatch"
    return "value_mismatch"


def record_shadow_diff(
    session: Session,
    *,
    domain_code: str,
    resource_code: str,
    request_kind: str,
    request_key: str | None,
    v1_payload: Any,
    v2_payload: Any,
    diff_kind: str | None = None,
    extra: Mapping[str, Any] | None = None,
    skip_identical: bool = True,
) -> ShadowDiffOutcome:
    """v1/v2 결과 비교 + audit.shadow_diff 적재.

    skip_identical=True 일 때 동일하면 *INSERT 안 함* (Q4 의 ratio 분모 안정성을 위해
    다른 row 만 누적). False 면 통계 산출 용도로 모두 적재.
    """
    final_kind = diff_kind or diff_kind_for(v1_payload, v2_payload)
    if final_kind not in VALID_DIFF_KINDS:
        final_kind = "other"

    v1_hash = _canonical_hash(v1_payload)
    v2_hash = _canonical_hash(v2_payload)

    if final_kind == "identical_skipped" and skip_identical:
        return ShadowDiffOutcome(
            diff_kind=final_kind, v1_hash=v1_hash, v2_hash=v2_hash, inserted=False
        )

    diff_id = session.execute(
        text(
            "INSERT INTO audit.shadow_diff "
            "(domain_code, resource_code, request_kind, request_key, "
            " v1_value_hash, v2_value_hash, diff_kind, "
            " v1_payload, v2_payload, extra, occurred_at) "
            "VALUES (:dom, :res, :rk, :rkk, :v1h, :v2h, :kind, "
            "        CAST(:v1p AS JSONB), CAST(:v2p AS JSONB), "
            "        CAST(:ext AS JSONB), :ts) "
            "RETURNING diff_id"
        ),
        {
            "dom": domain_code,
            "res": resource_code,
            "rk": request_kind,
            "rkk": request_key,
            "v1h": v1_hash,
            "v2h": v2_hash,
            "kind": final_kind,
            "v1p": json.dumps(v1_payload, ensure_ascii=False, default=str)
            if v1_payload is not None
            else None,
            "v2p": json.dumps(v2_payload, ensure_ascii=False, default=str)
            if v2_payload is not None
            else None,
            "ext": json.dumps(dict(extra or {}), ensure_ascii=False, default=str),
            "ts": datetime.now(UTC),
        },
    ).scalar_one()

    return ShadowDiffOutcome(
        diff_kind=final_kind,
        v1_hash=v1_hash,
        v2_hash=v2_hash,
        inserted=True,
        diff_id=int(diff_id),
    )


def run_shadow_compare(
    session: Session,
    *,
    domain_code: str,
    resource_code: str,
    request_kind: str,
    request_key: str | None,
    v1_callable: Any,  # () -> Any
    v2_callable: Any,  # () -> Any
    extra: Mapping[str, Any] | None = None,
) -> ShadowDiffOutcome:
    """v1/v2 callable 을 실행하고 결과를 비교.

    v1 결과는 *반드시 사용자 응답으로 반환되도록 caller 가 별도 처리* — 본 함수는
    오직 *비교 + 적재*. 예외 시 'exception' diff_kind.
    """
    v1_payload: Any = None
    v2_payload: Any = None
    exc_extra: dict[str, Any] = {}

    try:
        v1_payload = v1_callable()
    except Exception as exc:
        exc_extra["v1_error"] = f"{type(exc).__name__}: {exc}"[:500]
        v1_payload = None
    try:
        v2_payload = v2_callable()
    except Exception as exc:
        exc_extra["v2_error"] = f"{type(exc).__name__}: {exc}"[:500]
        v2_payload = None

    diff_kind = "exception" if exc_extra else None
    merged_extra = {**dict(extra or {}), **exc_extra}
    return record_shadow_diff(
        session,
        domain_code=domain_code,
        resource_code=resource_code,
        request_kind=request_kind,
        request_key=request_key,
        v1_payload=v1_payload,
        v2_payload=v2_payload,
        diff_kind=diff_kind,
        extra=merged_extra,
    )


__all__ = [
    "VALID_DIFF_KINDS",
    "ShadowDiffOutcome",
    "diff_kind_for",
    "record_shadow_diff",
    "run_shadow_compare",
]
