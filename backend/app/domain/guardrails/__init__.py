"""Phase 5.2.0 — 사용자 설계 가드레일 인프라.

5.2.1 의 entity 테이블 (source_contract / field_mapping / dq_rule /
mart_load_policy / sql_asset) 들이 모두 본 인프라 위에서 동작.

구성:
  - state_machine — DRAFT → REVIEW → APPROVED → PUBLISHED 전이 + ctl.approval_request
    적재
  - sql_guard     — 위험 SQL 차단 (v1+v2) + 도메인 인지 ALLOWED_SCHEMAS + 노드 타입
    별 read/write 제한
  - dry_run       — 트랜잭션 rollback 기반 SQL 미리보기 (실 mart 변경 없음)
  - publish_checklist — 공개 직전 N개 체크 항목을 composable 하게 실행

본 모듈은 5.2.0 한정 *infrastructure*. 실제 entity 별 검증 로직은 5.2.1 에서 plug-in.
"""

from __future__ import annotations

from app.domain.guardrails.dry_run import DryRunResult, run_dry
from app.domain.guardrails.publish_checklist import (
    CheckResult,
    CheckSpec,
    PublishChecklist,
)
from app.domain.guardrails.sql_guard import (
    SqlGuardError,
    SqlNodeContext,
    guard_sql,
)
from app.domain.guardrails.state_machine import (
    EntityType,
    Status,
    Transition,
    request_transition,
    resolve_request,
    valid_transitions,
)

__all__ = [
    "CheckResult",
    "CheckSpec",
    "DryRunResult",
    "EntityType",
    "PublishChecklist",
    "SqlGuardError",
    "SqlNodeContext",
    "Status",
    "Transition",
    "guard_sql",
    "request_transition",
    "resolve_request",
    "run_dry",
    "valid_transitions",
]
