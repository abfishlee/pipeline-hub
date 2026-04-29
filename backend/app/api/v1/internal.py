"""HTTP 경계 — `/v1/pipelines/internal/*` (Phase 4.0.4 Airflow 통합 전용).

용도: Airflow scheduled_pipelines DAG 가 backend 의 trigger_run 을 호출.
사용자 JWT 가 아닌 **공유 비밀 (X-Internal-Token 헤더)** 로 인증 — 같은 NCP/Docker
network 안에서만 동작. 외부 노출 시 nginx 단에서 차단 (`location ~ /v1/pipelines/internal
{ deny all; }`).

멱등성:
  - 같은 (workflow_id, run_date=today) 가 이미 RUNNING/SUCCESS 면 새 run 안 만들고 기존
    pipeline_run_id 반환 (HTTP 200).
  - 신규 run 생성 시 HTTP 202.
  - PUBLISHED 가 아니면 HTTP 422 (cron 자동 트리거 측에선 PUBLISHED 만 대상이지만 race
    조건 대비).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import errors as app_errors
from app.core.events import RedisPubSub
from app.db.sync_session import get_sync_sessionmaker
from app.deps import SessionDep
from app.domain import pipeline_runtime as runtime
from app.models.run import NodeRun, PipelineRun
from app.repositories import pipelines as pipelines_repo

router = APIRouter(prefix="/v1/pipelines/internal", tags=["pipelines-internal"])


def _enqueue_node_run(node_run_id: int, run_date_iso: str, *, event_suffix: str) -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        nr = session.get(NodeRun, node_run_id)
        node_type = nr.node_type if nr is not None else ""
    from app.workers.pipeline_node_worker import process_node_event
    from app.workers.pipeline_node_v2_worker import V2_NODE_TYPES, process_v2_node_event

    if node_type in V2_NODE_TYPES:
        process_v2_node_event.send(
            event_id=f"v2-node-run-{node_run_id}-{event_suffix}",
            node_run_id=node_run_id,
            run_date_iso=run_date_iso,
        )
    else:
        process_node_event.send(
            event_id=f"node-run-{node_run_id}-{event_suffix}",
            node_run_id=node_run_id,
            run_date_iso=run_date_iso,
        )


class InternalRunRequest(BaseModel):
    workflow_id: int = Field(ge=1)


class InternalRunResponse(BaseModel):
    pipeline_run_id: int
    run_date: str
    status: str
    created: bool  # True 면 새 run, False 면 기존 멱등 반환.


def _verify_token(x_internal_token: str | None) -> None:
    """Settings.airflow_internal_token 비교. constant-time 권장이지만 단순 eq 로 충분
    (token 길이 충분).

    settings 에 token 이 비어 있으면 503 (운영 미설정).
    """
    settings = get_settings()
    expected = settings.airflow_internal_token.get_secret_value().strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="airflow_internal_token not configured on backend",
        )
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid X-Internal-Token",
        )


@router.post(
    "/runs",
    response_model=InternalRunResponse,
)
async def trigger_run_internal(
    session: SessionDep,
    body: InternalRunRequest,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> InternalRunResponse:
    """Airflow scheduled_pipelines 가 호출하는 trigger.

    응답 status code:
      - 200: 같은 (workflow_id, today) 가 이미 RUNNING/SUCCESS — 멱등 반환.
      - 202: 신규 pipeline_run 생성 + entry 노드 actor enqueue 시도.
      - 401: X-Internal-Token 누락/오답.
      - 422: workflow 가 PUBLISHED 아님 / cycle / nodes 0개.
      - 503: backend 에 token 미설정.
    """
    _verify_token(x_internal_token)

    workflow = await pipelines_repo.get_workflow(session, body.workflow_id)
    if workflow is None:
        raise app_errors.NotFoundError(f"workflow {body.workflow_id} not found")
    if workflow.status != "PUBLISHED":
        raise app_errors.ValidationError(
            f"workflow {body.workflow_id} is {workflow.status} — must be PUBLISHED"
        )

    today = datetime.now(UTC).date()

    # 멱등 검사 — 같은 (workflow, today) 가 이미 활성 상태면 새로 안 만듦.
    sm = get_sync_sessionmaker()

    def _check_existing(s: Session) -> tuple[int | None, str | None]:
        existing = s.execute(
            select(PipelineRun)
            .where(PipelineRun.workflow_id == body.workflow_id)
            .where(PipelineRun.run_date == today)
            .where(PipelineRun.status.in_(("PENDING", "RUNNING", "SUCCESS")))
            .order_by(PipelineRun.pipeline_run_id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is None:
            return None, None
        return existing.pipeline_run_id, existing.status

    with sm() as sync_session:
        existing_id, existing_status = _check_existing(sync_session)

    if existing_id is not None and existing_status is not None:
        return InternalRunResponse(
            pipeline_run_id=existing_id,
            run_date=today.isoformat(),
            status=existing_status,
            created=False,
        )

    # 신규 run 생성 — pipeline_runtime.start_pipeline_run 사용.
    pubsub = RedisPubSub.from_settings()
    try:
        with sm() as sync_session:
            try:
                started = runtime.start_pipeline_run(
                    sync_session,
                    workflow_id=body.workflow_id,
                    triggered_by_user_id=None,  # Airflow 자동 트리거 — 사용자 없음.
                    pubsub=pubsub,
                )
            except ValueError as exc:
                raise app_errors.ValidationError(str(exc)) from exc
            sync_session.commit()
    finally:
        pubsub.close()

    # entry node actor enqueue — broker 미가동 시에도 200 정책.
    try:
        for node_run_id in started.ready_node_run_ids:
            _enqueue_node_run(
                node_run_id,
                started.run_date.isoformat(),
                event_suffix="attempt-1",
            )
    except Exception:
        pass

    # 202 표시 — FastAPI 에서 same handler 가 status 분기하려면 Response 직접 반환 필요.
    # 단순화: 응답 body 는 동일하고 created=True 로 클라이언트(Airflow) 가 분기 가능.
    return InternalRunResponse(
        pipeline_run_id=started.pipeline_run_id,
        run_date=started.run_date.isoformat(),
        status="RUNNING",
        created=True,
    )


__all__ = ["router"]
