"""Phase 6.1 — generic Public API connector.

설계 원칙 (사용자 결정):
  > "사용자는 API 주소 + KEY값 + 파라미터 + 수집 주기만 설정. 코딩 0줄."

본 패키지는 *단 1개* 의 generic engine 으로 KAMIS / 식약처 / 통계청 / 공공데이터포털
등 *어떤 REST API 든* 처리. 새 API 추가 = `domain.public_api_connector` 에 row 1건
INSERT 끝. 코드 수정 절대 X.

지원 매트릭스:
  * HTTP method      — GET / POST
  * Auth             — none / query_param / header / basic / bearer
  * Pagination       — none / page_number / offset_limit / cursor
  * Response format  — JSON / XML (xmltodict 자동 변환)
  * Templating       — query/body 안에 {ymd} {page} {cursor} {custom} 치환
  * Response extract — JSONPath-lite (`$.response.body.items.item` 등)

미지원 (Phase 6.5+ plugin):
  * SOAP / GraphQL / gRPC
  * binary 응답 (PDF, ZIP)
  * OAuth2 token refresh
"""

from __future__ import annotations

from app.domain.public_api.engine import (
    ConnectorCallResult,
    PublicApiError,
    call_connector,
    test_connector,
)
from app.domain.public_api.spec import (
    AuthMethod,
    ConnectorSpec,
    HttpMethod,
    PaginationKind,
    ResponseFormat,
    load_spec_from_db,
    save_spec_to_db,
)

__all__ = [
    "AuthMethod",
    "ConnectorCallResult",
    "ConnectorSpec",
    "HttpMethod",
    "PaginationKind",
    "PublicApiError",
    "ResponseFormat",
    "call_connector",
    "load_spec_from_db",
    "save_spec_to_db",
    "test_connector",
]
