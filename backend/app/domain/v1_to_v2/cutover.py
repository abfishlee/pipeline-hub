"""Cutover Flag — (domain, resource) 별 active path 전환 (Q2, Q4 답변).

상태 전환:
  v1               (초기, v2 미작성)
   ↓ shadow 시작
  v1 + v2_read_enabled (shadow 활성)
   ↓ ADMIN 승인 (Q2)
  v2               (cutover 완료, v1_write_disabled=TRUE)

가드 (Q4):
  - mismatch_ratio_1h > 1% → cutover 차단 (CutoverError).
  - 0.01% ~ 1% → warning. cutover 가능하지만 ADMIN 의 명시적 acknowledge 필요.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


CUTOVER_BLOCK_THRESHOLD: Final[float] = 0.01  # 1% mismatch
CUTOVER_WARNING_THRESHOLD: Final[float] = 0.0001  # 0.01% mismatch


class CutoverError(RuntimeError):
    """cutover 가드 위반 — caller 가 422/409 변환."""


@dataclass(slots=True)
class CutoverFlag:
    domain_code: str
    resource_code: str
    active_path: str
    v2_read_enabled: bool
    v1_write_disabled: bool
    shadow_started_at: datetime | None
    cutover_at: datetime | None
    approved_by: int | None
    notes: str | None
    updated_at: datetime


def get_cutover_flag(
    session: Session, *, domain_code: str, resource_code: str
) -> CutoverFlag | None:
    row = session.execute(
        text(
            "SELECT domain_code, resource_code, active_path, v2_read_enabled, "
            "       v1_write_disabled, shadow_started_at, cutover_at, "
            "       approved_by, notes, updated_at "
            "FROM ctl.cutover_flag "
            "WHERE domain_code = :d AND resource_code = :r"
        ),
        {"d": domain_code, "r": resource_code},
    ).first()
    if row is None:
        return None
    return CutoverFlag(
        domain_code=str(row.domain_code),
        resource_code=str(row.resource_code),
        active_path=str(row.active_path),
        v2_read_enabled=bool(row.v2_read_enabled),
        v1_write_disabled=bool(row.v1_write_disabled),
        shadow_started_at=row.shadow_started_at,
        cutover_at=row.cutover_at,
        approved_by=int(row.approved_by) if row.approved_by else None,
        notes=str(row.notes) if row.notes else None,
        updated_at=row.updated_at,
    )


def upsert_cutover_flag(
    session: Session,
    *,
    domain_code: str,
    resource_code: str,
    active_path: str = "v1",
    v2_read_enabled: bool = False,
    v1_write_disabled: bool = False,
    notes: str | None = None,
) -> CutoverFlag:
    if active_path not in ("v1", "v2", "shadow"):
        raise ValueError(f"invalid active_path: {active_path}")
    session.execute(
        text(
            "INSERT INTO ctl.cutover_flag "
            "(domain_code, resource_code, active_path, v2_read_enabled, "
            " v1_write_disabled, notes, updated_at) "
            "VALUES (:d, :r, :ap, :vr, :wd, :n, now()) "
            "ON CONFLICT (domain_code, resource_code) DO UPDATE SET "
            "  active_path = EXCLUDED.active_path, "
            "  v2_read_enabled = EXCLUDED.v2_read_enabled, "
            "  v1_write_disabled = EXCLUDED.v1_write_disabled, "
            "  notes = COALESCE(EXCLUDED.notes, ctl.cutover_flag.notes), "
            "  updated_at = now()"
        ),
        {
            "d": domain_code,
            "r": resource_code,
            "ap": active_path,
            "vr": v2_read_enabled,
            "wd": v1_write_disabled,
            "n": notes,
        },
    )
    flag = get_cutover_flag(
        session, domain_code=domain_code, resource_code=resource_code
    )
    assert flag is not None
    return flag


def _mismatch_ratio_recent(
    session: Session,
    *,
    domain_code: str,
    resource_code: str,
    window: timedelta,
) -> tuple[float, int, int]:
    """지난 window 동안의 mismatch_ratio + (mismatch_count, total_count).

    identical 은 적재되지 않으므로 *분모* 는 v1 endpoint 호출 횟수 (audit.access_log)
    로 잡아야 정확. Phase 5 MVP — *적재된 row 수* 만으로 estimate (비교 안 된 건
    'identical_skipped' 가정).
    """
    since = datetime.now(UTC) - window
    mismatch_count = session.execute(
        text(
            "SELECT COUNT(*) FROM audit.shadow_diff "
            "WHERE domain_code = :d AND resource_code = :r "
            "  AND occurred_at >= :ts "
            "  AND diff_kind <> 'identical_skipped'"
        ),
        {"d": domain_code, "r": resource_code, "ts": since},
    ).scalar_one()
    # access_log 대신 *전체* shadow_diff (skip_identical=False 모드 사용 시) 로 추정.
    total_count = session.execute(
        text(
            "SELECT COUNT(*) FROM audit.shadow_diff "
            "WHERE domain_code = :d AND resource_code = :r "
            "  AND occurred_at >= :ts"
        ),
        {"d": domain_code, "r": resource_code, "ts": since},
    ).scalar_one()
    if int(total_count or 0) == 0:
        return 0.0, 0, 0
    return float(mismatch_count) / float(total_count), int(mismatch_count), int(total_count)


def apply_cutover(
    session: Session,
    *,
    domain_code: str,
    resource_code: str,
    target_path: str,  # 'v2' or 'shadow'
    approver_user_id: int,
    acknowledge_warning: bool = False,
    notes: str | None = None,
    window_hours: int = 1,
) -> CutoverFlag:
    """ADMIN 명시 승인 (Q2) — gate 통과 후 active_path 전환.

    target_path='v2' 면:
      - shadow_diff mismatch_ratio_1h ≥ 1% → CutoverError (block, Q4).
      - 0.01% ≤ ratio < 1% → acknowledge_warning=True 필수.
      - active_path='v2', v1_write_disabled=TRUE, cutover_at=now, approver_user_id 기록.

    target_path='shadow' 는 active_path='v1' 유지하면서 v2_read_enabled=TRUE 만 켜는
    *시작 신호*. 기존 cutover 를 다시 shadow 로 되돌리는 것은 별도 turn (rollback).
    """
    if target_path not in ("v2", "shadow"):
        raise ValueError(f"invalid target_path: {target_path}")

    flag = get_cutover_flag(
        session, domain_code=domain_code, resource_code=resource_code
    )
    if flag is None:
        raise CutoverError(
            f"cutover_flag for ({domain_code},{resource_code}) not found"
        )

    if target_path == "shadow":
        return upsert_cutover_flag(
            session,
            domain_code=domain_code,
            resource_code=resource_code,
            active_path="v1",
            v2_read_enabled=True,
            v1_write_disabled=False,
            notes=notes or "shadow start",
        )

    # target_path = 'v2' — full cutover.
    ratio, mismatch, total = _mismatch_ratio_recent(
        session,
        domain_code=domain_code,
        resource_code=resource_code,
        window=timedelta(hours=window_hours),
    )
    if ratio >= CUTOVER_BLOCK_THRESHOLD:
        raise CutoverError(
            f"mismatch_ratio_{window_hours}h={ratio:.4%} (>= {CUTOVER_BLOCK_THRESHOLD:.0%}) "
            f"— cutover BLOCKED ({mismatch}/{total})"
        )
    if ratio >= CUTOVER_WARNING_THRESHOLD and not acknowledge_warning:
        raise CutoverError(
            f"mismatch_ratio_{window_hours}h={ratio:.4%} — between warning and block; "
            f"set acknowledge_warning=true to proceed ({mismatch}/{total})"
        )

    session.execute(
        text(
            "UPDATE ctl.cutover_flag SET "
            "  active_path = 'v2', "
            "  v2_read_enabled = TRUE, "
            "  v1_write_disabled = TRUE, "
            "  cutover_at = now(), "
            "  approved_by = :ap, "
            "  notes = COALESCE(:n, notes), "
            "  updated_at = now() "
            "WHERE domain_code = :d AND resource_code = :r"
        ),
        {
            "d": domain_code,
            "r": resource_code,
            "ap": approver_user_id,
            "n": notes,
        },
    )
    new_flag = get_cutover_flag(
        session, domain_code=domain_code, resource_code=resource_code
    )
    assert new_flag is not None
    return new_flag


__all__ = [
    "CUTOVER_BLOCK_THRESHOLD",
    "CUTOVER_WARNING_THRESHOLD",
    "CutoverError",
    "CutoverFlag",
    "apply_cutover",
    "get_cutover_flag",
    "upsert_cutover_flag",
]
