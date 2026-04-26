"""Phase 5.2.5 STEP 8 — v1 → v2 plugin migration 인프라.

핵심 개념:
  * **shadow run** = v1 응답이 사용자에게, v2 결과는 audit 비교만 (Q1 dual-active).
  * **T0 snapshot** = cutover 전 시점 mart row_count + sha256 checksum 보존 (Q3).
  * **cutover_flag** = (domain, resource) 별 active_path. ADMIN 명시 승인으로 전환 (Q2).

본 패키지의 3 모듈:
  - t0_checksum.py — sha256/md5 + partition 단위 checksum.
  - shadow_run.py — v1/v2 결과 비교 + audit.shadow_diff 적재.
  - cutover.py — cutover_flag CRUD + 임계값 가드 (Q4: alert + cutover_block).
"""

from __future__ import annotations

from app.domain.v1_to_v2.cutover import (
    CutoverError,
    CutoverFlag,
    apply_cutover,
    get_cutover_flag,
    upsert_cutover_flag,
)
from app.domain.v1_to_v2.shadow_run import (
    ShadowDiffOutcome,
    diff_kind_for,
    record_shadow_diff,
    run_shadow_compare,
)
from app.domain.v1_to_v2.t0_checksum import (
    PartitionChecksum,
    T0SnapshotResult,
    capture_table_snapshot,
    compute_partition_checksum,
)

__all__ = [
    "CutoverError",
    "CutoverFlag",
    "PartitionChecksum",
    "ShadowDiffOutcome",
    "T0SnapshotResult",
    "apply_cutover",
    "capture_table_snapshot",
    "compute_partition_checksum",
    "diff_kind_for",
    "get_cutover_flag",
    "record_shadow_diff",
    "run_shadow_compare",
    "upsert_cutover_flag",
]
