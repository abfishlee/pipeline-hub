"""Dead Letter 큐 repository (Phase 2.2.10)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import DeadLetter


async def list_dead_letters(
    session: AsyncSession,
    *,
    only_unreplayed: bool = True,
    origin: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[DeadLetter]:
    stmt = select(DeadLetter)
    if only_unreplayed:
        stmt = stmt.where(DeadLetter.replayed_at.is_(None))
    if origin:
        stmt = stmt.where(DeadLetter.origin == origin)
    stmt = stmt.order_by(DeadLetter.failed_at.desc()).limit(limit).offset(offset)
    return (await session.execute(stmt)).scalars().all()


async def get_dead_letter(session: AsyncSession, dl_id: int) -> DeadLetter | None:
    return await session.get(DeadLetter, dl_id)


async def mark_replayed(session: AsyncSession, *, row: DeadLetter, user_id: int) -> DeadLetter:
    row.replayed_at = datetime.now(UTC)
    row.replayed_by = user_id
    await session.flush()
    return row


__all__ = ["get_dead_letter", "list_dead_letters", "mark_replayed"]
