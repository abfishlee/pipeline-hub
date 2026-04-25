"""HTTP 경계 — `/v1/crowd-tasks` (검수 큐 조회/상태 전이).

Phase 2.2.10 운영자 화면 backend. Phase 4 정식 Crowd 검수 UI 도입 전 placeholder
관리 인터페이스. 권한: ADMIN / REVIEWER / APPROVER.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core import errors as app_errors
from app.deps import CurrentUserDep, SessionDep, require_roles
from app.repositories import crowd as crowd_repo
from app.schemas.crowd import (
    CrowdTaskDetail,
    CrowdTaskOut,
    CrowdTaskStatus,
    CrowdTaskStatusUpdate,
    OcrResultPreview,
)

router = APIRouter(
    prefix="/v1/crowd-tasks",
    tags=["crowd"],
    dependencies=[Depends(require_roles("ADMIN", "REVIEWER", "APPROVER"))],
)


@router.get("", response_model=list[CrowdTaskOut])
async def list_crowd_tasks(
    session: SessionDep,
    status: CrowdTaskStatus | None = Query(default=None),
    reason: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CrowdTaskOut]:
    rows = await crowd_repo.list_tasks(
        session, status=status, reason=reason, limit=limit, offset=offset
    )
    return [CrowdTaskOut.model_validate(r) for r in rows]


@router.get("/{crowd_task_id}", response_model=CrowdTaskDetail)
async def get_crowd_task(
    session: SessionDep,
    crowd_task_id: int,
) -> CrowdTaskDetail:
    task = await crowd_repo.get_task(session, crowd_task_id)
    if task is None:
        raise app_errors.NotFoundError(f"crowd_task {crowd_task_id} not found")
    raw = await crowd_repo.get_raw_object(
        session, raw_object_id=task.raw_object_id, partition_date=task.partition_date
    )
    ocr_rows = await crowd_repo.get_ocr_results(
        session, raw_object_id=task.raw_object_id, partition_date=task.partition_date
    )
    base = CrowdTaskOut.model_validate(task).model_dump()
    return CrowdTaskDetail(
        **base,
        raw_object_uri=(raw.object_uri if raw is not None else None),
        raw_object_payload=(raw.payload_json if raw is not None else None),
        ocr_results=[
            OcrResultPreview(
                ocr_result_id=o.ocr_result_id,
                page_no=o.page_no,
                text_content=o.text_content,
                confidence_score=float(o.confidence_score)
                if o.confidence_score is not None
                else None,
                engine_name=o.engine_name,
            )
            for o in ocr_rows
        ],
    )


@router.patch("/{crowd_task_id}/status", response_model=CrowdTaskOut)
async def update_crowd_task_status(
    session: SessionDep,
    user: CurrentUserDep,
    crowd_task_id: int,
    body: CrowdTaskStatusUpdate,
) -> CrowdTaskOut:
    task = await crowd_repo.get_task(session, crowd_task_id)
    if task is None:
        raise app_errors.NotFoundError(f"crowd_task {crowd_task_id} not found")

    # 전이 규칙 — Phase 2.2.10 단순 모델:
    #   PENDING → REVIEWING / APPROVED / REJECTED
    #   REVIEWING → APPROVED / REJECTED (또는 PENDING 으로 unclaim 은 미허용)
    #   APPROVED / REJECTED 는 종결 — 추가 전이 금지.
    valid_from = {
        "PENDING": {"REVIEWING", "APPROVED", "REJECTED"},
        "REVIEWING": {"APPROVED", "REJECTED"},
        "APPROVED": set(),
        "REJECTED": set(),
    }
    if body.status not in valid_from.get(task.status, set()):
        raise app_errors.ValidationError(
            f"invalid status transition: {task.status} → {body.status}"
        )

    updated = await crowd_repo.update_status(
        session, task=task, new_status=body.status, reviewer_user_id=user.user_id
    )
    await session.commit()
    return CrowdTaskOut.model_validate(updated)


__all__ = ["router"]
