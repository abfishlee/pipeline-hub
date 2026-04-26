"""HTTP — `/v2/namespaces` (Phase 6 Wave 6 — Quality Workbench Standardization 탭).

`domain.standard_code_namespace` list-light + std_code_table 미리보기.
복잡한 alias CRUD 는 Phase 7 backlog (별도 designer).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles
from app.models.domain import StandardCodeNamespace

router = APIRouter(
    prefix="/v2/namespaces",
    tags=["v2-namespaces"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class NamespaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    namespace_id: int
    domain_code: str
    name: str
    description: str | None
    std_code_table: str | None
    created_at: datetime


class StdCodeRow(BaseModel):
    std_code: str
    display_name: str | None = None
    description: str | None = None
    sort_order: int | None = None


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        return fn(session)


@router.get("", response_model=list[NamespaceOut])
async def list_namespaces(domain_code: str | None = None) -> list[NamespaceOut]:
    def _do(s: Session) -> list[NamespaceOut]:
        q = select(StandardCodeNamespace).order_by(
            StandardCodeNamespace.domain_code, StandardCodeNamespace.name
        )
        if domain_code:
            q = q.where(StandardCodeNamespace.domain_code == domain_code)
        rows = s.execute(q).scalars().all()
        return [NamespaceOut.model_validate(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


_FQDN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}\.[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


@router.get("/{namespace_id}/codes", response_model=list[StdCodeRow])
async def list_std_codes(namespace_id: int, limit: int = 200) -> list[StdCodeRow]:
    """namespace 의 std_code_table 내용 미리보기 (read-only)."""

    def _do(s: Session) -> list[StdCodeRow]:
        ns = s.get(StandardCodeNamespace, namespace_id)
        if ns is None:
            raise HTTPException(404, detail=f"namespace {namespace_id} not found")
        if not ns.std_code_table:
            return []
        if not _FQDN_RE.match(ns.std_code_table):
            raise HTTPException(
                422, detail=f"invalid std_code_table: {ns.std_code_table!r}"
            )
        # information_schema 로 컬럼 존재 검증.
        schema, table = ns.std_code_table.split(".", 1)
        cols = {
            str(r.column_name)
            for r in s.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": schema, "t": table},
            ).all()
        }
        if "std_code" not in cols:
            raise HTTPException(
                422,
                detail=(
                    f"{ns.std_code_table} 에 std_code 컬럼 없음 — "
                    "namespace 표준 형식 (std_code, display_name?, description?, sort_order?)"
                ),
            )
        select_cols: list[str] = ["std_code"]
        for opt in ("display_name", "description", "sort_order"):
            if opt in cols:
                select_cols.append(opt)
        select_clause = ", ".join(select_cols)
        order = "sort_order, std_code" if "sort_order" in cols else "std_code"
        rows = s.execute(
            text(
                f'SELECT {select_clause} FROM "{schema}"."{table}" '
                f"ORDER BY {order} LIMIT :lim"
            ),
            {"lim": min(max(limit, 1), 1000)},
        ).all()
        return [
            StdCodeRow(
                std_code=str(r.std_code),
                display_name=str(r.display_name) if "display_name" in cols and r.display_name else None,
                description=str(r.description) if "description" in cols and r.description else None,
                sort_order=int(r.sort_order) if "sort_order" in cols and r.sort_order is not None else None,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
