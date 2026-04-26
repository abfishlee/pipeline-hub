"""Public API Connector spec — DB row ↔ Python dataclass.

generic spec 이므로 *공급자별 분기 절대 X*. 사용자가 채우는 모든 항목을 표현.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class AuthMethod(StrEnum):
    NONE = "none"
    QUERY_PARAM = "query_param"
    HEADER = "header"
    BASIC = "basic"
    BEARER = "bearer"


class PaginationKind(StrEnum):
    NONE = "none"
    PAGE_NUMBER = "page_number"      # ?page=1, 2, 3 ...
    OFFSET_LIMIT = "offset_limit"    # ?offset=0, limit=100
    CURSOR = "cursor"                # 응답에서 다음 cursor 추출


class ResponseFormat(StrEnum):
    JSON = "json"
    XML = "xml"


@dataclass(slots=True)
class ConnectorSpec:
    """사용자가 화면에서 입력한 모든 값. DB row 1건 = 이 spec 1개."""

    connector_id: int | None
    domain_code: str
    resource_code: str
    name: str
    description: str | None = None

    endpoint_url: str = ""
    http_method: HttpMethod = HttpMethod.GET

    # Auth.
    auth_method: AuthMethod = AuthMethod.NONE
    auth_param_name: str | None = None     # 예: 'cert_key' (KAMIS), 'serviceKey' (data.go.kr)
    secret_ref: str | None = None          # env / Secret Manager 참조 이름

    request_headers: dict[str, str] = field(default_factory=dict)
    query_template: dict[str, Any] = field(default_factory=dict)
    body_template: dict[str, Any] | None = None

    # Pagination.
    pagination_kind: PaginationKind = PaginationKind.NONE
    pagination_config: dict[str, Any] = field(default_factory=dict)

    # Response.
    response_format: ResponseFormat = ResponseFormat.JSON
    response_path: str | None = None       # JSONPath-lite. 예: '$.response.body.items.item'

    # 운영 정책.
    timeout_sec: int = 15
    retry_max: int = 2
    rate_limit_per_min: int = 60

    schedule_cron: str | None = None
    schedule_enabled: bool = False
    status: str = "DRAFT"
    is_active: bool = True


def _coerce_dict(v: Any) -> dict[str, Any]:
    if v is None:
        return {}
    if isinstance(v, dict):
        return dict(v)
    if isinstance(v, str):
        try:
            return json.loads(v) if v else {}
        except json.JSONDecodeError:
            return {}
    return {}


def load_spec_from_db(session: Session, *, connector_id: int) -> ConnectorSpec | None:
    row = session.execute(
        text(
            "SELECT connector_id, domain_code, resource_code, name, description, "
            "       endpoint_url, http_method, auth_method, auth_param_name, secret_ref, "
            "       request_headers, query_template, body_template, "
            "       pagination_kind, pagination_config, "
            "       response_format, response_path, "
            "       timeout_sec, retry_max, rate_limit_per_min, "
            "       schedule_cron, schedule_enabled, status, is_active "
            "FROM domain.public_api_connector WHERE connector_id = :id"
        ),
        {"id": connector_id},
    ).first()
    if row is None:
        return None
    return ConnectorSpec(
        connector_id=int(row.connector_id),
        domain_code=str(row.domain_code),
        resource_code=str(row.resource_code),
        name=str(row.name),
        description=str(row.description) if row.description else None,
        endpoint_url=str(row.endpoint_url),
        http_method=HttpMethod(row.http_method),
        auth_method=AuthMethod(row.auth_method),
        auth_param_name=str(row.auth_param_name) if row.auth_param_name else None,
        secret_ref=str(row.secret_ref) if row.secret_ref else None,
        request_headers=_coerce_dict(row.request_headers),
        query_template=_coerce_dict(row.query_template),
        body_template=_coerce_dict(row.body_template) if row.body_template else None,
        pagination_kind=PaginationKind(row.pagination_kind),
        pagination_config=_coerce_dict(row.pagination_config),
        response_format=ResponseFormat(row.response_format),
        response_path=str(row.response_path) if row.response_path else None,
        timeout_sec=int(row.timeout_sec),
        retry_max=int(row.retry_max),
        rate_limit_per_min=int(row.rate_limit_per_min),
        schedule_cron=str(row.schedule_cron) if row.schedule_cron else None,
        schedule_enabled=bool(row.schedule_enabled),
        status=str(row.status),
        is_active=bool(row.is_active),
    )


def save_spec_to_db(
    session: Session,
    spec: ConnectorSpec,
    *,
    created_by: int | None = None,
) -> int:
    """INSERT or UPDATE. spec.connector_id 가 None 이면 INSERT, 있으면 UPDATE."""
    payload = {
        "domain_code": spec.domain_code,
        "resource_code": spec.resource_code,
        "name": spec.name,
        "description": spec.description,
        "endpoint_url": spec.endpoint_url,
        "http_method": spec.http_method.value,
        "auth_method": spec.auth_method.value,
        "auth_param_name": spec.auth_param_name,
        "secret_ref": spec.secret_ref,
        "request_headers": json.dumps(spec.request_headers, ensure_ascii=False),
        "query_template": json.dumps(spec.query_template, ensure_ascii=False),
        "body_template": (
            json.dumps(spec.body_template, ensure_ascii=False)
            if spec.body_template is not None
            else None
        ),
        "pagination_kind": spec.pagination_kind.value,
        "pagination_config": json.dumps(spec.pagination_config, ensure_ascii=False),
        "response_format": spec.response_format.value,
        "response_path": spec.response_path,
        "timeout_sec": spec.timeout_sec,
        "retry_max": spec.retry_max,
        "rate_limit_per_min": spec.rate_limit_per_min,
        "schedule_cron": spec.schedule_cron,
        "schedule_enabled": spec.schedule_enabled,
        "status": spec.status,
        "is_active": spec.is_active,
    }

    if spec.connector_id is None:
        payload["created_by"] = created_by
        cid = session.execute(
            text(
                "INSERT INTO domain.public_api_connector "
                "(domain_code, resource_code, name, description, endpoint_url, "
                " http_method, auth_method, auth_param_name, secret_ref, "
                " request_headers, query_template, body_template, "
                " pagination_kind, pagination_config, response_format, response_path, "
                " timeout_sec, retry_max, rate_limit_per_min, "
                " schedule_cron, schedule_enabled, status, is_active, created_by) "
                "VALUES (:domain_code, :resource_code, :name, :description, :endpoint_url, "
                "        :http_method, :auth_method, :auth_param_name, :secret_ref, "
                "        CAST(:request_headers AS JSONB), CAST(:query_template AS JSONB), "
                "        CAST(:body_template AS JSONB), "
                "        :pagination_kind, CAST(:pagination_config AS JSONB), "
                "        :response_format, :response_path, "
                "        :timeout_sec, :retry_max, :rate_limit_per_min, "
                "        :schedule_cron, :schedule_enabled, :status, :is_active, :created_by) "
                "RETURNING connector_id"
            ),
            payload,
        ).scalar_one()
        return int(cid)

    payload["connector_id"] = spec.connector_id
    session.execute(
        text(
            "UPDATE domain.public_api_connector SET "
            "  domain_code = :domain_code, resource_code = :resource_code, "
            "  name = :name, description = :description, endpoint_url = :endpoint_url, "
            "  http_method = :http_method, auth_method = :auth_method, "
            "  auth_param_name = :auth_param_name, secret_ref = :secret_ref, "
            "  request_headers = CAST(:request_headers AS JSONB), "
            "  query_template = CAST(:query_template AS JSONB), "
            "  body_template = CAST(:body_template AS JSONB), "
            "  pagination_kind = :pagination_kind, "
            "  pagination_config = CAST(:pagination_config AS JSONB), "
            "  response_format = :response_format, response_path = :response_path, "
            "  timeout_sec = :timeout_sec, retry_max = :retry_max, "
            "  rate_limit_per_min = :rate_limit_per_min, "
            "  schedule_cron = :schedule_cron, schedule_enabled = :schedule_enabled, "
            "  status = :status, is_active = :is_active, updated_at = now() "
            "WHERE connector_id = :connector_id"
        ),
        payload,
    )
    return spec.connector_id


def render_template(template: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, Any]:
    """`{ymd}` `{page}` `{cursor}` 등 템플릿 변수를 runtime 값으로 치환.

    값이 단독 `{name}` 이면 *원본 타입* 보존 (예: int 가 str 로 안 변함).
    부분 치환 (`prefix-{ymd}`) 이면 str 강제.
    """
    import re as _re

    out: dict[str, Any] = {}
    pattern = _re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    for k, v in template.items():
        if isinstance(v, str):
            full = pattern.fullmatch(v)
            if full is not None:
                key = full.group(1)
                out[k] = runtime.get(key, v)
            else:
                out[k] = pattern.sub(
                    lambda m: str(runtime.get(m.group(1), "")),
                    v,
                )
        elif isinstance(v, dict):
            out[k] = render_template(v, runtime)
        elif isinstance(v, list):
            out[k] = [
                render_template({"_": x}, runtime)["_"]
                if isinstance(x, dict | str)
                else x
                for x in v
            ]
        else:
            out[k] = v
    return out


__all__ = [
    "AuthMethod",
    "ConnectorSpec",
    "HttpMethod",
    "PaginationKind",
    "ResponseFormat",
    "load_spec_from_db",
    "render_template",
    "save_spec_to_db",
]
