"""HTTP — `/v2/checklist` (Phase 5.2.4 STEP 7 Q5).

Mini Publish Checklist 실행 + 결과 조회.
publish 시점에 7개 항목 자동 체크 → all_passed 면 ADMIN 의 publish 버튼 enable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain.guardrails.mini_publish_checklist import run_checklist

router = APIRouter(
    prefix="/v2/checklist",
    tags=["v2-checklist"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER"))
    ],
)


class ChecklistRunRequest(BaseModel):
    entity_type: str = Field(
        pattern=r"^(source_contract|field_mapping|dq_rule|"
        r"mart_load_policy|sql_asset|load_policy)$"
    )
    entity_id: int = Field(ge=1)
    entity_version: int = Field(default=1, ge=1)
    domain_code: str | None = None
    current_status: str | None = None
    target_table: str | None = None
    contract_id: int | None = None


class CheckEntry(BaseModel):
    code: str
    passed: bool
    detail: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChecklistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    checklist_id: int | None = None
    entity_type: str
    entity_id: int
    entity_version: int
    domain_code: str | None
    all_passed: bool
    failed_check_codes: list[str]
    checks: list[CheckEntry]
    requested_at: datetime


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        try:
            res = fn(session)
            session.commit()
            return res
        except Exception:
            session.rollback()
            raise


@router.post("/run", response_model=ChecklistOut)
async def run_publish_checklist(
    body: ChecklistRunRequest, user: CurrentUserDep
) -> ChecklistOut:
    def _do(s: Session) -> ChecklistOut:
        outcome = run_checklist(
            s,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            entity_version=body.entity_version,
            domain_code=body.domain_code,
            requested_by=user.user_id,
            current_status=body.current_status,
            target_table=body.target_table,
            contract_id=body.contract_id,
        )
        s.flush()
        # 새로 INSERT 된 row 의 id 조회.
        cid = s.execute(
            text(
                "SELECT checklist_id FROM ctl.publish_checklist_run "
                "WHERE entity_type = :et AND entity_id = :eid "
                "  AND entity_version = :ev "
                "ORDER BY requested_at DESC LIMIT 1"
            ),
            {
                "et": body.entity_type,
                "eid": body.entity_id,
                "ev": body.entity_version,
            },
        ).scalar_one_or_none()
        return ChecklistOut(
            checklist_id=int(cid) if cid else None,
            entity_type=outcome.entity_type,
            entity_id=outcome.entity_id,
            entity_version=outcome.entity_version,
            domain_code=outcome.domain_code,
            all_passed=outcome.all_passed,
            failed_check_codes=outcome.failed_codes,
            checks=[
                CheckEntry(
                    code=c.code,
                    passed=c.passed,
                    detail=c.detail,
                    metadata=c.metadata,
                )
                for c in outcome.checks
            ],
            requested_at=outcome.requested_at,
        )

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/recent", response_model=list[ChecklistOut])
async def recent_checklists(
    entity_type: str | None = None,
    domain_code: str | None = None,
    limit: int = 20,
) -> list[ChecklistOut]:
    def _do(s: Session) -> list[ChecklistOut]:
        sql = (
            "SELECT checklist_id, entity_type, entity_id, entity_version, "
            "       domain_code, all_passed, failed_check_codes, checks_json, "
            "       requested_at FROM ctl.publish_checklist_run "
        )
        clauses: list[str] = []
        params: dict[str, Any] = {"lim": min(max(limit, 1), 100)}
        if entity_type:
            clauses.append("entity_type = :et")
            params["et"] = entity_type
        if domain_code:
            clauses.append("domain_code = :dom")
            params["dom"] = domain_code
        if clauses:
            sql += "WHERE " + " AND ".join(clauses) + " "
        sql += "ORDER BY requested_at DESC LIMIT :lim"
        rows = s.execute(text(sql), params).all()
        out: list[ChecklistOut] = []
        for r in rows:
            checks_raw = r.checks_json or []
            if isinstance(checks_raw, str):
                import json as _json

                checks_raw = _json.loads(checks_raw)
            out.append(
                ChecklistOut(
                    checklist_id=int(r.checklist_id),
                    entity_type=str(r.entity_type),
                    entity_id=int(r.entity_id),
                    entity_version=int(r.entity_version),
                    domain_code=str(r.domain_code) if r.domain_code else None,
                    all_passed=bool(r.all_passed),
                    failed_check_codes=list(r.failed_check_codes or []),
                    checks=[CheckEntry(**c) for c in checks_raw],
                    requested_at=r.requested_at,
                )
            )
        return out

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
