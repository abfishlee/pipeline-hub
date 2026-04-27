"""HTTP — `/v2/onboarding` (Phase 8.6 — 진입 가이드).

신규 운영자용 5 단계 진행도. 각 단계는 *시스템에 PUBLISHED 자산이 1건 이상 있는지* 로 판단.
도메인 무관 (공용 플랫폼 표현).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles

router = APIRouter(
    prefix="/v2/onboarding",
    tags=["v2-onboarding"],
    dependencies=[
        Depends(
            require_roles(
                "ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR", "REVIEWER"
            )
        )
    ],
)


class OnboardingStep(BaseModel):
    code: str
    label: str
    completed: bool
    count: int
    next_action_label: str
    next_action_href: str
    help_summary: str


class OnboardingProgress(BaseModel):
    steps: list[OnboardingStep]
    completed_count: int
    total: int
    is_ready: bool


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        return fn(session)


@router.get("/progress", response_model=OnboardingProgress)
async def progress() -> OnboardingProgress:
    """5 단계 진행도 — Dashboard QuickStartCard 가 사용."""

    def _do(s: Session) -> OnboardingProgress:
        source_count = int(
            s.execute(
                text(
                    "SELECT "
                    "  (SELECT COUNT(*) FROM domain.public_api_connector "
                    "   WHERE status='PUBLISHED') "
                    "+ (SELECT COUNT(*) FROM domain.inbound_channel "
                    "   WHERE status='PUBLISHED' AND is_active=true)"
                )
            ).scalar_one()
        )
        mapping_count = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM domain.field_mapping "
                    "WHERE status='PUBLISHED'"
                )
            ).scalar_one()
        )
        mart_count = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM domain.mart_design_draft "
                    "WHERE status='PUBLISHED'"
                )
            ).scalar_one()
        )
        workflow_count = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM wf.workflow_definition "
                    "WHERE status='PUBLISHED'"
                )
            ).scalar_one()
        )
        run_count = int(
            s.execute(text("SELECT COUNT(*) FROM run.pipeline_run")).scalar_one()
        )

        steps = [
            OnboardingStep(
                code="source",
                label="외부 데이터 소스 등록",
                completed=source_count > 0,
                count=source_count,
                next_action_label="+ Source 등록",
                next_action_href="/v2/connectors/public-api",
                help_summary=(
                    "외부 OpenAPI 또는 Inbound Push 채널을 등록합니다. "
                    "등록 후 ETL Canvas 에서 dropdown 으로 사용 가능."
                ),
            ),
            OnboardingStep(
                code="mapping",
                label="필드 매핑 등록",
                completed=mapping_count > 0,
                count=mapping_count,
                next_action_label="+ Field Mapping",
                next_action_href="/v2/mappings/designer",
                help_summary=(
                    "외부 응답의 path 를 mart 컬럼으로 매핑 + 변환 함수 적용. "
                    "JSON Path Picker 로 시각 매핑 지원."
                ),
            ),
            OnboardingStep(
                code="mart",
                label="마트 테이블 정의",
                completed=mart_count > 0,
                count=mart_count,
                next_action_label="+ Mart 설계",
                next_action_href="/v2/marts/designer",
                help_summary=(
                    "적재 대상 마트 테이블의 DDL 을 시각 설계 + load_policy 정의."
                ),
            ),
            OnboardingStep(
                code="workflow",
                label="ETL Canvas 워크플로",
                completed=workflow_count > 0,
                count=workflow_count,
                next_action_label="+ Canvas",
                next_action_href="/v2/pipelines/designer",
                help_summary=(
                    "등록된 자산을 끌어 노드 chain 으로 연결하여 코딩 0줄로 워크플로 완성."
                ),
            ),
            OnboardingStep(
                code="run",
                label="실행 + 결과 확인",
                completed=run_count > 0,
                count=run_count,
                next_action_label="Pipeline Runs",
                next_action_href="/pipelines/runs",
                help_summary=(
                    "PUBLISHED 워크플로를 trigger 또는 schedule_cron 으로 실행. "
                    "결과는 Pipeline Run Detail 의 노드별 timeline 으로 추적."
                ),
            ),
        ]
        completed = sum(1 for st in steps if st.completed)
        return OnboardingProgress(
            steps=steps,
            completed_count=completed,
            total=len(steps),
            is_ready=completed == len(steps),
        )

    return await asyncio.to_thread(_run_in_sync, _do)
