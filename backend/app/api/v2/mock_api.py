"""HTTP — `/v2/mock-api` (Phase 8.6 — 자체 검증용 Mock API).

운영자가 외부 API 의존 없이 시스템을 검증할 수 있도록, *우리 시스템 안에서* 외부 API
endpoint 를 흉내낼 수 있게 한다.

흐름:
  1. /v2/mock-api/endpoints (CRUD) — mock 응답 등록/관리 (ADMIN/APPROVER)
  2. /v2/mock-api/serve/{code} — *공개 endpoint* (인증 불필요), 등록된 mock 응답 그대로
     반환. 같은 시스템의 Source/API Connector 가 이 URL 을 호출하여 dry-run / 수집 검증.

응답 포맷 5 종 지원: json / xml / csv / tsv / text. 각 포맷에 맞는 Content-Type 자동 설정.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles

# ---------------------------------------------------------------------------
# CRUD router (인증 필요)
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/v2/mock-api",
    tags=["v2-mock-api"],
)


class MockEndpointIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name: str
    description: str | None = None
    response_format: str = Field(..., pattern=r"^(json|xml|csv|tsv|text)$")
    response_body: str
    response_headers: dict[str, str] = Field(default_factory=dict)
    status_code: int = Field(default=200, ge=100, le=599)
    delay_ms: int = Field(default=0, ge=0, le=30000)
    is_active: bool = True


class MockEndpointOut(BaseModel):
    mock_id: int
    code: str
    name: str
    description: str | None
    response_format: str
    response_body: str
    response_headers: dict[str, Any]
    status_code: int
    delay_ms: int
    is_active: bool
    call_count: int
    last_called_at: datetime | None
    created_at: datetime
    updated_at: datetime
    serve_url_path: str


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


def _serialize(row: Any) -> MockEndpointOut:
    return MockEndpointOut(
        mock_id=int(row.mock_id),
        code=str(row.code),
        name=str(row.name),
        description=row.description,
        response_format=str(row.response_format),
        response_body=str(row.response_body),
        response_headers=dict(row.response_headers or {}),
        status_code=int(row.status_code),
        delay_ms=int(row.delay_ms),
        is_active=bool(row.is_active),
        call_count=int(row.call_count),
        last_called_at=row.last_called_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        serve_url_path=f"/v2/mock-api/serve/{row.code}",
    )


@router.get(
    "/endpoints",
    response_model=list[MockEndpointOut],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)
async def list_endpoints() -> list[MockEndpointOut]:
    def _do(s: Session) -> list[MockEndpointOut]:
        rows = s.execute(
            text(
                "SELECT * FROM ctl.mock_api_endpoint ORDER BY updated_at DESC"
            )
        ).all()
        return [_serialize(r) for r in rows]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.post(
    "/endpoints",
    response_model=MockEndpointOut,
    status_code=201,
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER"))],
)
async def create_endpoint(body: MockEndpointIn) -> MockEndpointOut:
    def _do(s: Session) -> MockEndpointOut:
        import json as _json

        try:
            row = s.execute(
                text(
                    """
                    INSERT INTO ctl.mock_api_endpoint
                      (code, name, description, response_format, response_body,
                       response_headers, status_code, delay_ms, is_active)
                    VALUES (:code, :name, :desc, :fmt, :body,
                            CAST(:hdrs AS JSONB), :sc, :dly, :act)
                    RETURNING *
                    """
                ),
                {
                    "code": body.code,
                    "name": body.name,
                    "desc": body.description,
                    "fmt": body.response_format,
                    "body": body.response_body,
                    "hdrs": _json.dumps(body.response_headers),
                    "sc": body.status_code,
                    "dly": body.delay_ms,
                    "act": body.is_active,
                },
            ).first()
        except Exception as exc:
            if "mock_api_endpoint_code_key" in str(exc):
                raise HTTPException(
                    409, detail=f"code {body.code!r} already exists"
                ) from exc
            raise
        assert row is not None
        return _serialize(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.put(
    "/endpoints/{mock_id}",
    response_model=MockEndpointOut,
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER"))],
)
async def update_endpoint(mock_id: int, body: MockEndpointIn) -> MockEndpointOut:
    def _do(s: Session) -> MockEndpointOut:
        import json as _json

        row = s.execute(
            text(
                """
                UPDATE ctl.mock_api_endpoint SET
                  name=:name, description=:desc,
                  response_format=:fmt, response_body=:body,
                  response_headers=CAST(:hdrs AS JSONB),
                  status_code=:sc, delay_ms=:dly, is_active=:act,
                  updated_at=now()
                WHERE mock_id=:mid
                RETURNING *
                """
            ),
            {
                "mid": mock_id,
                "name": body.name,
                "desc": body.description,
                "fmt": body.response_format,
                "body": body.response_body,
                "hdrs": _json.dumps(body.response_headers),
                "sc": body.status_code,
                "dly": body.delay_ms,
                "act": body.is_active,
            },
        ).first()
        if row is None:
            raise HTTPException(404, detail=f"mock_id {mock_id} not found")
        return _serialize(row)

    return await asyncio.to_thread(_run_in_sync, _do)


@router.delete(
    "/endpoints/{mock_id}",
    status_code=204,
    dependencies=[Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER"))],
)
async def delete_endpoint(mock_id: int) -> Response:
    def _do(s: Session) -> int:
        result = s.execute(
            text("DELETE FROM ctl.mock_api_endpoint WHERE mock_id=:mid"),
            {"mid": mock_id},
        )
        return result.rowcount or 0

    affected = await asyncio.to_thread(_run_in_sync, _do)
    if affected == 0:
        raise HTTPException(404, detail=f"mock_id {mock_id} not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Public serve endpoint (인증 불필요 — 외부 API 흉내)
# ---------------------------------------------------------------------------
serve_router = APIRouter(
    prefix="/v2/mock-api/serve",
    tags=["v2-mock-api-serve"],
)

_FORMAT_CONTENT_TYPE: dict[str, str] = {
    "json": "application/json; charset=utf-8",
    "xml": "application/xml; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8",
    "text": "text/plain; charset=utf-8",
}


@serve_router.get("/{code}", response_class=Response)
async def serve_mock(
    code: str = Path(..., pattern=r"^[a-z][a-z0-9_]{1,62}$"),
) -> Response:
    """등록된 mock 응답을 그대로 반환 (외부 API 흉내).

    같은 시스템의 Source/API Connector 가 이 URL 을 호출 가능. 인증 없음 — 공개.
    """

    def _do(s: Session) -> Any:
        row = s.execute(
            text(
                "SELECT * FROM ctl.mock_api_endpoint "
                "WHERE code=:code AND is_active=true"
            ),
            {"code": code},
        ).first()
        if row is None:
            return None
        # 호출 카운트 증가 (best-effort).
        s.execute(
            text(
                "UPDATE ctl.mock_api_endpoint "
                "SET call_count=call_count+1, last_called_at=now() "
                "WHERE mock_id=:mid"
            ),
            {"mid": row.mock_id},
        )
        return row

    row = await asyncio.to_thread(_run_in_sync, _do)
    if row is None:
        raise HTTPException(404, detail=f"mock endpoint {code!r} not found or inactive")

    if row.delay_ms > 0:
        time.sleep(row.delay_ms / 1000.0)

    headers: dict[str, str] = dict(row.response_headers or {})
    if "Content-Type" not in headers and "content-type" not in headers:
        headers["Content-Type"] = _FORMAT_CONTENT_TYPE.get(
            str(row.response_format), "application/octet-stream"
        )
    return Response(
        content=str(row.response_body),
        status_code=int(row.status_code),
        headers=headers,
    )
