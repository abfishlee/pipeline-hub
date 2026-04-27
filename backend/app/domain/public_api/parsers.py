"""Phase 8.6 — 응답 포맷 7종 parser.

ResponseFormat 별로 raw bytes / text 를 list[dict] 로 평탄화.

지원:
  - json:   json.loads → list 또는 dict (response_path 적용 후)
  - xml:    xmltodict 로 dict 변환 후 response_path 적용
  - csv:    csv.DictReader (delimiter=',')
  - tsv:    csv.DictReader (delimiter='\t')
  - text:   1줄 = 1 dict, key='line', value='해당 줄'
  - excel:  openpyxl 로 첫 sheet → list[dict] (header=row1)
  - binary: parser 는 noop — 호출자가 raw 그대로 Object Storage 저장 후 후속 노드에서 처리
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.domain.public_api.spec import ResponseFormat


class ParseError(Exception):
    """response 파싱 실패."""


def _navigate(obj: Any, path: str) -> Any:
    """`$.a.b.c` 같은 단순 dot-path 추출. response_path 가 빈 문자열이면 그대로 반환."""
    if not path or not path.strip():
        return obj
    p = path.strip().lstrip("$").lstrip(".")
    if not p:
        return obj
    cur: Any = obj
    for part in p.split("."):
        if isinstance(cur, list):
            # path 도중 list 만나면 첫 원소로 진행 (간단화)
            cur = cur[0] if cur else None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _ensure_list_of_dict(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v if isinstance(v, dict) else {"value": v} for v in value]
    if isinstance(value, dict):
        return [value]
    return [{"value": value}]


def parse_response(
    *,
    body: bytes | str,
    response_format: ResponseFormat | str,
    response_path: str = "",
) -> list[dict[str, Any]]:
    """포맷별 파싱 → list[dict] 반환."""
    fmt = (
        response_format.value
        if isinstance(response_format, ResponseFormat)
        else str(response_format)
    )

    if fmt == "binary":
        # binary 는 parser 가 처리하지 않음 — caller 가 raw 보존만.
        return []

    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseError(f"failed to decode body as utf-8: {exc}") from exc
    else:
        text = body

    if fmt == "json":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON: {exc}") from exc
        return _ensure_list_of_dict(_navigate(obj, response_path))

    if fmt == "xml":
        try:
            import xmltodict  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ParseError(
                "xmltodict not installed — `pip install xmltodict`"
            ) from exc
        try:
            obj = xmltodict.parse(text)
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"invalid XML: {exc}") from exc
        return _ensure_list_of_dict(_navigate(obj, response_path))

    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        return [dict(row) for row in reader]

    if fmt == "text":
        return [{"line": ln} for ln in text.splitlines() if ln.strip()]

    if fmt == "excel":
        try:
            import openpyxl  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ParseError(
                "openpyxl not installed — `pip install openpyxl`"
            ) from exc
        wb = openpyxl.load_workbook(
            io.BytesIO(body if isinstance(body, bytes) else body.encode()),
            read_only=True,
            data_only=True,
        )
        ws = wb.active
        if ws is None:
            return []
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 1:
            return []
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
        out: list[dict[str, Any]] = []
        for row in rows[1:]:
            d = {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}
            out.append(d)
        return out

    raise ParseError(f"unsupported response_format: {fmt!r}")


__all__ = ["parse_response", "ParseError"]
