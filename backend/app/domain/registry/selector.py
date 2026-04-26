"""resource_selector matcher — raw payload 가 어느 (domain, resource) 에 속하는지 분기.

우선순위 (Q3 답변):
  1. endpoint match     — payload 의 endpoint 와 selector.endpoint 비교
  2. payload.type       — payload[type_field] 와 selector.payload_type 비교
  3. JSONPath           — payload 트리에서 jsonpath 평가 (값 있으면 매치)

여러 contract 가 같은 source 에 등록되어 있을 때, 본 모듈이 *각 contract 의 selector*
를 평가하고 *우선순위 1순위 부터 매치되는 것* 을 선택. 동률 시 schema_version 가장
높은 contract 채택.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class SelectorMatch:
    contract_id: int
    domain_code: str
    resource_code: str
    schema_version: int
    matched_by: str  # "endpoint" | "payload_type" | "jsonpath" | "no_selector"


def _payload_type(payload: Mapping[str, Any], type_field: str = "type") -> str | None:
    """payload.type 또는 payload[type_field] 추출. 점 표기 (`meta.type`) 도 지원."""
    if "." not in type_field:
        v = payload.get(type_field)
        return str(v) if v is not None else None
    cur: Any = payload
    for part in type_field.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return str(cur)


def _jsonpath_eval(payload: Mapping[str, Any], path: str) -> bool:
    """매우 단순한 JSONPath 서브셋 평가 — `$.a.b.c` 또는 `$.a[0].b` 형태.

    PoC 단계 — production 에서는 jsonpath-ng 도입 검토. 현재 코드는 *값이 존재하면
    True* 만 판정 (조건식 `?(@.x==y)` 미지원).
    """
    if not path or not path.startswith("$"):
        return False
    if path == "$":
        return bool(payload)
    parts = path.lstrip("$").lstrip(".").replace("[", ".[").split(".")
    cur: Any = payload
    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            try:
                idx = int(part[1:-1])
            except ValueError:
                return False
            if not isinstance(cur, list) or idx >= len(cur):
                return False
            cur = cur[idx]
            continue
        if isinstance(cur, Mapping):
            if part not in cur:
                return False
            cur = cur[part]
        else:
            return False
    return cur is not None and cur != [] and cur != {}


def _endpoint_match(selector: Mapping[str, Any], request_endpoint: str | None) -> bool:
    sel_endpoint = selector.get("endpoint")
    if not sel_endpoint or not request_endpoint:
        return False
    return str(request_endpoint).rstrip("/") == str(sel_endpoint).rstrip("/")


def _payload_type_match(selector: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    sel_type = selector.get("payload_type")
    if not sel_type:
        return False
    type_field = str(selector.get("payload_type_field", "type"))
    actual = _payload_type(payload, type_field=type_field)
    return actual is not None and str(actual) == str(sel_type)


def _jsonpath_match(selector: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    sel_path = selector.get("jsonpath")
    if not sel_path:
        return False
    return _jsonpath_eval(payload, str(sel_path))


@dataclass(slots=True, frozen=True)
class _ContractCandidate:
    contract_id: int
    domain_code: str
    resource_code: str
    schema_version: int
    selector: Mapping[str, Any]


def match_resource_selector(
    *,
    payload: Mapping[str, Any],
    request_endpoint: str | None,
    candidates: Iterable[_ContractCandidate | Mapping[str, Any]],
) -> SelectorMatch | None:
    """우선순위 [endpoint > payload_type > jsonpath] 로 후보 1개 선택.

    candidates 는 `_ContractCandidate` 또는 동일 키를 가진 dict.
    동순위 매치 시 schema_version 가장 높은 contract 채택.
    """
    normalized: list[_ContractCandidate] = []
    for c in candidates:
        if isinstance(c, _ContractCandidate):
            normalized.append(c)
        else:
            normalized.append(
                _ContractCandidate(
                    contract_id=int(c["contract_id"]),
                    domain_code=str(c["domain_code"]),
                    resource_code=str(c["resource_code"]),
                    schema_version=int(c.get("schema_version", 1)),
                    selector=dict(c.get("resource_selector_json") or {}),
                )
            )

    matched: list[tuple[int, _ContractCandidate, str]] = []  # (priority, candidate, matched_by)
    for cand in normalized:
        sel = cand.selector or {}
        if _endpoint_match(sel, request_endpoint):
            matched.append((1, cand, "endpoint"))
        elif _payload_type_match(sel, payload):
            matched.append((2, cand, "payload_type"))
        elif _jsonpath_match(sel, payload):
            matched.append((3, cand, "jsonpath"))
        elif not sel:
            # 셀렉터 미설정 contract — 마지막 fallback (priority 4).
            matched.append((4, cand, "no_selector"))

    if not matched:
        return None

    # 우선순위 + 버전 가장 높은 후보 채택.
    matched.sort(key=lambda x: (x[0], -x[1].schema_version))
    best_priority, best, matched_by = matched[0]
    return SelectorMatch(
        contract_id=best.contract_id,
        domain_code=best.domain_code,
        resource_code=best.resource_code,
        schema_version=best.schema_version,
        matched_by=matched_by,
    )


__all__ = ["SelectorMatch", "match_resource_selector"]
