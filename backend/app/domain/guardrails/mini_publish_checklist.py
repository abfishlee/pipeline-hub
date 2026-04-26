"""Mini Publish Checklist (Phase 5.2.4 STEP 7 Q5).

publish (=PUBLISHED 전이) 직전에 *5~7개* 자동 체크를 수행하고 결과를 보존.
모두 통과해야 ADMIN 의 '승인' 버튼이 enable 되는 *MVP 안전장치*.

체크 항목:
  1. dry_run_passed   — 최근 dry-run 이 errors=[] 로 통과했는가?
  2. dq_rules_present — 대상 mart 에 active DQ rule 1개 이상?
  3. mapping_complete — contract 의 required field 모두 mapping 됨?
  4. checksum_recorded — T0 checksum (Phase 5.2.5 의 구조) 가 등록됨? (없으면 skip)
  5. status_chain_valid — 현재 entity status 가 APPROVED 인가?
  6. approver_signed   — 결재자 서명 (ctl.approval_request) 1건 이상?
  7. owner_acknowledge — 도메인 ADMIN/APPROVER 의 ack flag (config 로 끔/켬)

확장 항목 (Phase 6):
  - lineage_complete / load_perf_baseline / sample_data_review.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CheckResult:
    code: str
    passed: bool
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "passed": self.passed,
            "detail": self.detail,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ChecklistOutcome:
    entity_type: str
    entity_id: int
    entity_version: int
    domain_code: str | None
    requested_by: int | None
    checks: list[CheckResult]
    requested_at: datetime

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_codes(self) -> list[str]:
        return [c.code for c in self.checks if not c.passed]


# ---------------------------------------------------------------------------
# 개별 체크
# ---------------------------------------------------------------------------
def check_dry_run_passed(
    session: Session, *, kind: str, target_table: str | None = None
) -> CheckResult:
    """최근 1건의 dry_run 결과를 확인. errors=[] 면 통과."""
    sql = (
        "SELECT errors, requested_at FROM ctl.dry_run_record "
        "WHERE kind = :k "
    )
    params: dict[str, Any] = {"k": kind}
    if target_table:
        sql += "AND target_summary->>'target_table' = :tt "
        params["tt"] = target_table
    sql += "ORDER BY requested_at DESC LIMIT 1"
    row = session.execute(text(sql), params).first()
    if row is None:
        return CheckResult(
            "dry_run_passed",
            False,
            "no recent dry-run found",
        )
    errors = list(row.errors or [])
    return CheckResult(
        "dry_run_passed",
        passed=len(errors) == 0,
        detail=f"errors={len(errors)}",
        metadata={"recent_at": row.requested_at.isoformat()},
    )


def check_dq_rules_present(
    session: Session, *, target_table: str
) -> CheckResult:
    """대상 mart 에 APPROVED/PUBLISHED dq_rule 가 1개 이상."""
    cnt = (
        session.execute(
            text(
                "SELECT COUNT(*) FROM domain.dq_rule "
                "WHERE target_table = :tt "
                "  AND status IN ('APPROVED','PUBLISHED')"
            ),
            {"tt": target_table},
        ).scalar_one()
        or 0
    )
    return CheckResult(
        "dq_rules_present",
        passed=int(cnt) >= 1,
        detail=f"count={cnt}",
        metadata={"target_table": target_table},
    )


def check_mapping_complete(
    session: Session, *, contract_id: int
) -> CheckResult:
    """contract 의 schema_json.properties 의 required 필드가 모두 mapping 됨."""
    row = session.execute(
        text(
            "SELECT schema_json FROM domain.source_contract "
            "WHERE contract_id = :cid"
        ),
        {"cid": contract_id},
    ).first()
    if row is None:
        return CheckResult("mapping_complete", False, "contract missing")
    schema = row.schema_json or {}
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except Exception:
            schema = {}
    required = list(schema.get("required", []))
    if not required:
        return CheckResult(
            "mapping_complete", True, "no required fields declared"
        )
    mapped = {
        r.target_column
        for r in session.execute(
            text(
                "SELECT target_column FROM domain.field_mapping "
                "WHERE contract_id = :cid "
                "  AND status IN ('APPROVED','PUBLISHED')"
            ),
            {"cid": contract_id},
        ).all()
    }
    missing = [c for c in required if c not in mapped]
    return CheckResult(
        "mapping_complete",
        passed=not missing,
        detail=f"missing={missing}" if missing else "all required fields mapped",
        metadata={"required_count": len(required), "missing": missing},
    )


def check_status_is_approved(current_status: str) -> CheckResult:
    return CheckResult(
        "status_chain_valid",
        passed=current_status == "APPROVED",
        detail=f"current={current_status}",
    )


def check_approver_signed(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    entity_version: int,
) -> CheckResult:
    cnt = session.execute(
        text(
            "SELECT COUNT(*) FROM ctl.approval_request "
            "WHERE entity_type = :et AND entity_id = :eid "
            "  AND entity_version = :ev "
            "  AND decision = 'APPROVE'"
        ),
        {"et": entity_type, "eid": entity_id, "ev": entity_version},
    ).scalar_one()
    return CheckResult(
        "approver_signed",
        passed=int(cnt or 0) >= 1,
        detail=f"approve_count={cnt}",
    )


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------
def run_checklist(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    entity_version: int = 1,
    domain_code: str | None = None,
    requested_by: int | None = None,
    current_status: str | None = None,
    target_table: str | None = None,
    contract_id: int | None = None,
    extra_checks: Mapping[str, CheckResult] | None = None,
) -> ChecklistOutcome:
    """체크리스트 실행 + ctl.publish_checklist_run 에 결과 보존."""
    checks: list[CheckResult] = []

    if current_status is not None:
        checks.append(check_status_is_approved(current_status))

    checks.append(
        check_approver_signed(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_version=entity_version,
        )
    )

    if target_table:
        checks.append(
            check_dry_run_passed(
                session,
                kind="load_target" if entity_type == "load_policy" else "field_mapping",
                target_table=target_table,
            )
        )
        checks.append(check_dq_rules_present(session, target_table=target_table))

    if contract_id is not None:
        checks.append(check_mapping_complete(session, contract_id=contract_id))

    if extra_checks:
        checks.extend(extra_checks.values())

    outcome = ChecklistOutcome(
        entity_type=entity_type,
        entity_id=entity_id,
        entity_version=entity_version,
        domain_code=domain_code,
        requested_by=requested_by,
        checks=checks,
        requested_at=datetime.now(UTC),
    )

    session.execute(
        text(
            "INSERT INTO ctl.publish_checklist_run "
            "(entity_type, entity_id, entity_version, domain_code, requested_by, "
            " checks_json, all_passed, failed_check_codes) "
            "VALUES (:et, :eid, :ev, :dom, :by, CAST(:checks AS JSONB), :ok, :failed)"
        ),
        {
            "et": entity_type,
            "eid": entity_id,
            "ev": entity_version,
            "dom": domain_code,
            "by": requested_by,
            "checks": json.dumps([c.to_dict() for c in checks], default=str),
            "ok": outcome.all_passed,
            "failed": outcome.failed_codes,
        },
    )
    return outcome


__all__ = [
    "CheckResult",
    "ChecklistOutcome",
    "check_approver_signed",
    "check_dq_rules_present",
    "check_dry_run_passed",
    "check_mapping_complete",
    "check_status_is_approved",
    "run_checklist",
]
