"""HTTP 경계 — `/v1/dead-letters` (DLQ 조회 + 재발송).

Phase 2.2.10. 권한: ADMIN 전용 (재발송이 운영 사고로 직결 가능).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core import errors as app_errors
from app.deps import CurrentUserDep, SessionDep, require_roles
from app.repositories import dead_letters as dl_repo
from app.schemas.dead_letters import DeadLetterOut, DeadLetterReplayResult
from app.workers import get_broker

router = APIRouter(
    prefix="/v1/dead-letters",
    tags=["dead-letters"],
    dependencies=[Depends(require_roles("ADMIN"))],
)


@router.get("", response_model=list[DeadLetterOut])
async def list_dead_letters(
    session: SessionDep,
    replayed: Annotated[bool, Query(description="false = 미처리만")] = False,
    origin: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DeadLetterOut]:
    rows = await dl_repo.list_dead_letters(
        session,
        only_unreplayed=not replayed,
        origin=origin,
        limit=limit,
        offset=offset,
    )
    return [DeadLetterOut.model_validate(r) for r in rows]


@router.get("/{dl_id}", response_model=DeadLetterOut)
async def get_dead_letter(session: SessionDep, dl_id: int) -> DeadLetterOut:
    row = await dl_repo.get_dead_letter(session, dl_id)
    if row is None:
        raise app_errors.NotFoundError(f"dead_letter {dl_id} not found")
    return DeadLetterOut.model_validate(row)


@router.post("/{dl_id}/replay", response_model=DeadLetterReplayResult)
async def replay_dead_letter(
    session: SessionDep,
    user: CurrentUserDep,
    dl_id: int,
) -> DeadLetterReplayResult:
    row = await dl_repo.get_dead_letter(session, dl_id)
    if row is None:
        raise app_errors.NotFoundError(f"dead_letter {dl_id} not found")
    if row.replayed_at is not None:
        raise app_errors.ValidationError(
            f"dead_letter {dl_id} already replayed at {row.replayed_at.isoformat()}"
        )

    broker = get_broker()
    actor_name = row.origin
    actor = broker.actors.get(actor_name)
    if actor is None:
        raise app_errors.ValidationError(
            f"actor '{actor_name}' not registered in current broker — cannot replay"
        )

    payload = row.payload_json or {}
    args = list(payload.get("args") or [])
    kwargs = dict(payload.get("kwargs") or {})

    message = actor.send_with_options(args=tuple(args), kwargs=kwargs)
    await dl_repo.mark_replayed(session, row=row, user_id=user.user_id)
    await session.commit()

    return DeadLetterReplayResult(
        dl_id=row.dl_id,
        origin=actor_name,
        enqueued_message_id=str(message.message_id) if message is not None else None,
        replayed_at=row.replayed_at or datetime.now(UTC),
        replayed_by=user.user_id,
    )


__all__ = ["router"]
