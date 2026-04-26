"""HTTP 응답 파서 — JSON / XML 자동 변환 + JSONPath-lite 추출.

generic 이라 KAMIS / 식약처 / 통계청 어떤 응답 구조든 처리.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def parse_response_body(body_text: str, *, response_format: str) -> Any:
    """JSON 또는 XML 응답을 dict/list 로 변환.

    XML 은 xmltodict 가 있으면 사용, 없으면 표준 lib (제한적). 보통 xmltodict 의존.
    """
    if not body_text or not body_text.strip():
        return None
    fmt = response_format.lower()
    if fmt == "json":
        import json as _json

        return _json.loads(body_text)
    if fmt == "xml":
        try:
            import xmltodict  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "xmltodict not installed. Install with `pip install xmltodict`"
            ) from exc
        return xmltodict.parse(body_text)
    raise ValueError(f"unsupported response_format: {response_format}")


def extract_path(data: Any, path: str | None) -> Any:
    """JSONPath-lite — `$.a.b.c` / `$.a[0].b` / `$.a.b[*].c`.

    `[*]` 는 list 의 모든 요소를 *flat list* 로 반환. 없으면 단일 값.
    """
    if path is None or not path:
        return data
    if not path.startswith("$"):
        raise ValueError(f"path must start with $: {path!r}")

    cur: Any = data
    parts = _tokenize_path(path)
    for part in parts:
        if part == "[*]":
            if not isinstance(cur, list):
                # dict 였다면 list 화. (예: API 가 row 1개일 때 list 안 감싸진 경우)
                cur = [cur] if cur is not None else []
            continue
        if part.startswith("[") and part.endswith("]"):
            try:
                idx = int(part[1:-1])
            except ValueError as exc:
                raise ValueError(f"invalid index in path: {part}") from exc
            if isinstance(cur, list) and -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
            continue
        # field name.
        if isinstance(cur, list):
            # list 의 각 요소에 대해 field 적용 (flat).
            new: list[Any] = []
            for item in cur:
                if isinstance(item, Mapping) and part in item:
                    new.append(item[part])
            cur = new
        elif isinstance(cur, Mapping):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _tokenize_path(path: str) -> list[str]:
    """`$.a.b[0].c[*].d` → ['a', 'b', '[0]', 'c', '[*]', 'd']"""
    body = path.lstrip("$").lstrip(".")
    out: list[str] = []
    cur = ""
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == ".":
            if cur:
                out.append(cur)
                cur = ""
            i += 1
            continue
        if ch == "[":
            if cur:
                out.append(cur)
                cur = ""
            # bracket 까지.
            end = body.find("]", i)
            if end == -1:
                raise ValueError(f"unbalanced bracket in path: {path}")
            out.append(body[i : end + 1])
            i = end + 1
            continue
        cur += ch
        i += 1
    if cur:
        out.append(cur)
    return out


def normalize_to_rows(extracted: Any) -> list[dict[str, Any]]:
    """추출 결과를 *항상 list[dict]* 로 정규화.

    - dict 1개 → [dict]
    - list of dict → 그대로
    - list of scalar → [{"value": x}, ...]
    - None → []
    """
    if extracted is None:
        return []
    if isinstance(extracted, dict):
        return [dict(extracted)]
    if isinstance(extracted, list):
        out: list[dict[str, Any]] = []
        for item in extracted:
            if isinstance(item, dict):
                out.append(dict(item))
            elif item is None:
                continue
            else:
                out.append({"value": item})
        return out
    return [{"value": extracted}]


__all__ = [
    "extract_path",
    "normalize_to_rows",
    "parse_response_body",
]
