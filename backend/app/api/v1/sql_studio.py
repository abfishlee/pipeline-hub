"""HTTP 경계 — `/v1/sql-studio` (Phase 3.2.4 SQL 정적 검증).

Phase 3.2.4 한정으로 dry-run validate 1개 엔드포인트만. Phase 3.2.4.x 후속에서
sandbox 실행(EXPLAIN / 실제 SELECT) + 승인 플로우 + 버전 관리(`wf.sql_query` /
`wf.sql_query_version`) 추가 예정.

권한: ADMIN / APPROVER / OPERATOR (SELECT-only 검증이라 광범위 허용).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import require_roles
from app.integrations.sqlglot_validator import SqlValidationError, validate
from app.schemas.sql_studio import SqlValidateRequest, SqlValidateResponse

router = APIRouter(
    prefix="/v1/sql-studio",
    tags=["sql-studio"],
    dependencies=[Depends(require_roles("ADMIN", "APPROVER", "OPERATOR"))],
)


@router.post("/validate", response_model=SqlValidateResponse)
async def validate_sql(body: SqlValidateRequest) -> SqlValidateResponse:
    """sqlglot AST 분석 — 위반 시 200 with valid=false (UI 가 에러 메시지 노출)."""
    try:
        _ast, refs = validate(body.sql)
    except SqlValidationError as exc:
        return SqlValidateResponse(valid=False, error=str(exc))
    return SqlValidateResponse(valid=True, referenced_tables=sorted(refs))


__all__ = ["router"]
