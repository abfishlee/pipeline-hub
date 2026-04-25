"""HTTP 경계 — `/v1/sql-studio` (Phase 3.2.4 정적 검증 + 3.2.5 sandbox/승인).

엔드포인트 (Phase 3.2.5 종합):
  POST /v1/sql-studio/validate            — sqlglot 정적 분석 (모든 권한 OK 한)
  POST /v1/sql-studio/preview             — sandbox 실행 + LIMIT (ADMIN/APPROVER/OPERATOR)
  POST /v1/sql-studio/explain             — EXPLAIN (FORMAT JSON)

  POST /v1/sql-studio/queries             — 새 SQL 자산 + DRAFT v1 (OPERATOR+)
  GET  /v1/sql-studio/queries             — 자산 목록
  GET  /v1/sql-studio/queries/{id}        — 자산 상세 + 모든 버전
  POST /v1/sql-studio/queries/{id}/versions          — 새 DRAFT 버전 (소유자)
  POST /v1/sql-studio/versions/{vid}/submit          — DRAFT → PENDING (소유자)
  POST /v1/sql-studio/versions/{vid}/approve         — PENDING → APPROVED (APPROVER)
  POST /v1/sql-studio/versions/{vid}/reject          — PENDING → REJECTED (APPROVER)

권한 매트릭스:
  - VIEWER 는 전체 차단 (검증 포함). 데이터 노출 우려.
  - OPERATOR 는 validate/preview/explain + 자기 query CRUD/submit. approve/reject 불가.
  - APPROVER / ADMIN 는 모든 행위.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import errors as app_errors
from app.db.sync_session import get_sync_sessionmaker
from app.deps import CurrentUserDep, require_roles
from app.domain import sql_studio as studio
from app.models.wf import SqlQuery, SqlQueryVersion
from app.schemas.sql_studio import (
    SqlExplainRequest,
    SqlExplainResponse,
    SqlPreviewRequest,
    SqlPreviewResponse,
    SqlQueryCreate,
    SqlQueryDetail,
    SqlQueryOut,
    SqlQueryVersionOut,
    SqlValidateRequest,
    SqlValidateResponse,
    SqlVersionCreate,
    SqlVersionReview,
)

router = APIRouter(
    prefix="/v1/sql-studio",
    tags=["sql-studio"],
    dependencies=[Depends(require_roles("ADMIN", "APPROVER", "OPERATOR"))],
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
T = TypeVar("T")


async def _in_sync_session(fn: Callable[[Session], T]) -> T:
    """sync domain call 을 thread 로 offload + 자동 rollback.

    호출자는 `(session) -> T` 형태의 클로저를 넘긴다. 함수가 정상 반환하면 commit,
    예외면 rollback 후 재던짐. 도메인 내부에서 audit row 를 별도 commit 했더라도
    여기서 다시 commit 호출은 멱등 (no-op).
    """

    def _wrapped() -> T:
        sm = get_sync_sessionmaker()
        with sm() as session:
            try:
                result = fn(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise

    return await asyncio.to_thread(_wrapped)


# ---------------------------------------------------------------------------
# VALIDATE / PREVIEW / EXPLAIN
# ---------------------------------------------------------------------------
@router.post("/validate", response_model=SqlValidateResponse)
async def validate_sql(
    body: SqlValidateRequest,
    user: CurrentUserDep,
) -> SqlValidateResponse:
    """sqlglot AST 분석 — 위반 시 200 with valid=false (UI 가 에러 메시지 노출)."""
    outcome = await _in_sync_session(
        lambda s: studio.validate_with_audit(s, user_id=user.user_id, sql=body.sql)
    )
    return SqlValidateResponse(
        valid=outcome.valid,
        error=outcome.error,
        referenced_tables=outcome.referenced_tables,
    )


@router.post("/preview", response_model=SqlPreviewResponse)
async def preview_sql(
    body: SqlPreviewRequest,
    user: CurrentUserDep,
) -> SqlPreviewResponse:
    """sandbox 실행 — read-only 트랜잭션 + LIMIT 부착 + ROLLBACK.

    위반/실패 시 422 (ValidationError). audit 는 도메인이 별도 sub-tx 로 커밋.
    """
    result = await _in_sync_session(
        lambda s: studio.preview(
            s,
            user_id=user.user_id,
            sql=body.sql,
            limit=body.limit,
            sql_query_version_id=body.sql_query_version_id,
        )
    )
    return SqlPreviewResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
    )


@router.post("/explain", response_model=SqlExplainResponse)
async def explain_sql(
    body: SqlExplainRequest,
    user: CurrentUserDep,
) -> SqlExplainResponse:
    result = await _in_sync_session(
        lambda s: studio.explain(
            s,
            user_id=user.user_id,
            sql=body.sql,
            sql_query_version_id=body.sql_query_version_id,
        )
    )
    return SqlExplainResponse(plan_json=result.plan_json, elapsed_ms=result.elapsed_ms)


# ---------------------------------------------------------------------------
# Query / Version CRUD
# ---------------------------------------------------------------------------
@router.post("/queries", response_model=SqlQueryDetail, status_code=201)
async def create_query(
    body: SqlQueryCreate,
    user: CurrentUserDep,
) -> SqlQueryDetail:
    def _do(session: Session) -> tuple[SqlQuery, list[SqlQueryVersion]]:
        version = studio.create_query(
            session,
            name=body.name,
            description=body.description,
            sql_text=body.sql_text,
            owner_user_id=user.user_id,
        )
        query = session.get(SqlQuery, version.sql_query_id)
        assert query is not None
        versions = list(
            session.execute(
                select(SqlQueryVersion)
                .where(SqlQueryVersion.sql_query_id == query.sql_query_id)
                .order_by(SqlQueryVersion.version_no.asc())
            ).scalars()
        )
        return query, versions

    query, versions = await _in_sync_session(_do)
    return _to_detail(query, versions)


@router.get("/queries", response_model=list[SqlQueryOut])
async def list_queries(
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SqlQueryOut]:
    rows = await _in_sync_session(
        lambda s: list(
            s.execute(select(SqlQuery).order_by(SqlQuery.updated_at.desc()).limit(limit)).scalars()
        )
    )
    return [SqlQueryOut.model_validate(r) for r in rows]


@router.get("/queries/{query_id}", response_model=SqlQueryDetail)
async def get_query(
    user: CurrentUserDep,
    query_id: int = Path(..., ge=1),
) -> SqlQueryDetail:
    def _do(session: Session) -> tuple[SqlQuery, list[SqlQueryVersion]]:
        q = session.get(SqlQuery, query_id)
        if q is None:
            raise app_errors.NotFoundError(f"sql_query {query_id} not found")
        versions = list(
            session.execute(
                select(SqlQueryVersion)
                .where(SqlQueryVersion.sql_query_id == query_id)
                .order_by(SqlQueryVersion.version_no.asc())
            ).scalars()
        )
        return q, versions

    q, versions = await _in_sync_session(_do)
    return _to_detail(q, versions)


@router.post(
    "/queries/{query_id}/versions",
    response_model=SqlQueryVersionOut,
    status_code=201,
)
async def add_version(
    body: SqlVersionCreate,
    user: CurrentUserDep,
    query_id: int = Path(..., ge=1),
) -> SqlQueryVersionOut:
    version = await _in_sync_session(
        lambda s: studio.add_version(
            s,
            sql_query_id=query_id,
            sql_text=body.sql_text,
            owner_user_id=user.user_id,
        )
    )
    return SqlQueryVersionOut.model_validate(version)


@router.post("/versions/{version_id}/submit", response_model=SqlQueryVersionOut)
async def submit_version(
    user: CurrentUserDep,
    version_id: int = Path(..., ge=1),
) -> SqlQueryVersionOut:
    version = await _in_sync_session(
        lambda s: studio.submit_version(s, sql_query_version_id=version_id, by_user_id=user.user_id)
    )
    return SqlQueryVersionOut.model_validate(version)


@router.post(
    "/versions/{version_id}/approve",
    response_model=SqlQueryVersionOut,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def approve_version(
    body: SqlVersionReview,
    user: CurrentUserDep,
    version_id: int = Path(..., ge=1),
) -> SqlQueryVersionOut:
    version = await _in_sync_session(
        lambda s: studio.approve_version(
            s,
            sql_query_version_id=version_id,
            reviewer_user_id=user.user_id,
            comment=body.comment,
        )
    )
    return SqlQueryVersionOut.model_validate(version)


@router.post(
    "/versions/{version_id}/reject",
    response_model=SqlQueryVersionOut,
    dependencies=[Depends(require_roles("ADMIN", "APPROVER"))],
)
async def reject_version(
    body: SqlVersionReview,
    user: CurrentUserDep,
    version_id: int = Path(..., ge=1),
) -> SqlQueryVersionOut:
    version = await _in_sync_session(
        lambda s: studio.reject_version(
            s,
            sql_query_version_id=version_id,
            reviewer_user_id=user.user_id,
            comment=body.comment,
        )
    )
    return SqlQueryVersionOut.model_validate(version)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _to_detail(query: SqlQuery, versions: list[SqlQueryVersion]) -> SqlQueryDetail:
    base = SqlQueryOut.model_validate(query).model_dump()
    return SqlQueryDetail(
        **base,
        versions=[SqlQueryVersionOut.model_validate(v) for v in versions],
    )


__all__ = ["router"]
