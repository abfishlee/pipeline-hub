"""FUNCTION_TRANSFORM 허용 함수 ~25종 (Phase 5.2.2 Q4 답변).

핵심 원칙:
  1. **부작용 없음 (pure)** — 외부 IO / 환경 / 시각 의존 금지.
       예외: `date.now_kst` 만 (KST 기준 현재 시각 — 결정론은 caller 가 timestamp 주입).
  2. **타입 보존** — 입력 타입 그대로 또는 명시적 캐스팅 결과.
  3. **에러 정책** — 실패 시 `FunctionCallError` (caller 가 row error 로 분류).
  4. **eval 절대 금지** — `apply_expression` 은 `func_name(arg1=..., arg2=...)` 형태의
     매우 제한된 mini-DSL 만 파싱.

분류 (총 26종):
  text     — trim, upper, lower, normalize_unicode_nfc, replace, regex_extract,
             starts_with, length
  number   — parse_decimal, round_n, abs_value, clamp
  date     — parse, to_kst, to_iso, format
  phone    — normalize_kr
  address  — extract_sido, extract_sigungu
  json     — get_path, to_string, parse
  hash     — sha256, md5
  id       — make_content_hash, slugify

이 레지스트리는 Phase 5.2.2 generic 노드 + Phase 5.2.4 ETL UX (mapping 함수 빌더) 의
공통 기반.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

KST = timezone(timedelta(hours=9))


class FunctionCallError(ValueError):
    """allowlist 검증 실패 또는 실행 중 에러."""


@dataclass(slots=True, frozen=True)
class FunctionSpec:
    name: str
    category: str
    fn: Callable[..., Any]
    description: str
    arity_min: int = 1
    arity_max: int | None = None  # None = unbounded


# ---------------------------------------------------------------------------
# text.* — 문자열 정규화/추출.
# ---------------------------------------------------------------------------
def _text_trim(value: Any) -> str:
    return _coerce_str(value).strip()


def _text_upper(value: Any) -> str:
    return _coerce_str(value).upper()


def _text_lower(value: Any) -> str:
    return _coerce_str(value).lower()


def _text_normalize_unicode_nfc(value: Any) -> str:
    return unicodedata.normalize("NFC", _coerce_str(value))


def _text_replace(value: Any, old: str, new: str) -> str:
    return _coerce_str(value).replace(_coerce_str(old), _coerce_str(new))


def _text_regex_extract(value: Any, pattern: str, group: int = 0) -> str | None:
    """패턴이 매치되면 group, 아니면 None."""
    try:
        compiled = re.compile(_coerce_str(pattern))
    except re.error as exc:
        raise FunctionCallError(f"text.regex_extract: invalid pattern: {exc}") from exc
    m = compiled.search(_coerce_str(value))
    if m is None:
        return None
    try:
        return m.group(int(group))
    except (IndexError, ValueError) as exc:
        raise FunctionCallError(f"text.regex_extract: bad group {group}") from exc


def _text_starts_with(value: Any, prefix: str) -> bool:
    return _coerce_str(value).startswith(_coerce_str(prefix))


def _text_length(value: Any) -> int:
    return len(_coerce_str(value))


# ---------------------------------------------------------------------------
# number.* — 수치 파싱/정규화.
# ---------------------------------------------------------------------------
def _number_parse_decimal(value: Any) -> Decimal | None:
    """문자/숫자 → Decimal. 콤마/공백 제거. None/'' → None."""
    if value is None or value == "":
        return None
    s = _coerce_str(value).replace(",", "").replace(" ", "")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError) as exc:
        raise FunctionCallError(f"number.parse_decimal: cannot parse {value!r}") from exc


def _number_round_n(value: Any, ndigits: int = 0) -> Decimal | None:
    if value is None:
        return None
    dec = value if isinstance(value, Decimal) else _number_parse_decimal(value)
    if dec is None:
        return None
    quant = Decimal(1).scaleb(-int(ndigits))
    return dec.quantize(quant)


def _number_abs(value: Any) -> Decimal | None:
    dec = value if isinstance(value, Decimal) else _number_parse_decimal(value)
    return None if dec is None else abs(dec)


def _number_clamp(value: Any, lo: Any, hi: Any) -> Decimal | None:
    dec = value if isinstance(value, Decimal) else _number_parse_decimal(value)
    if dec is None:
        return None
    lo_d = Decimal(str(lo))
    hi_d = Decimal(str(hi))
    if lo_d > hi_d:
        raise FunctionCallError(f"number.clamp: lo({lo}) > hi({hi})")
    return max(lo_d, min(hi_d, dec))


# ---------------------------------------------------------------------------
# date.* — 시각 파싱/변환.
# ---------------------------------------------------------------------------
_ISO_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y%m%d%H%M%S",
    "%Y%m%d",
)


def _date_parse(value: Any, fmt: str | None = None) -> datetime | None:
    """문자/datetime → naive UTC datetime. 시각 정보 없으면 00:00. None → None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = _coerce_str(value).strip()
    if fmt:
        try:
            return datetime.strptime(s, _coerce_str(fmt))
        except ValueError as exc:
            raise FunctionCallError(f"date.parse: format mismatch {fmt!r}") from exc
    for f in _ISO_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    raise FunctionCallError(f"date.parse: cannot parse {value!r}")


def _date_to_kst(value: Any) -> datetime | None:
    """naive datetime 은 UTC 로 간주 → KST 변환. tz-aware 면 KST 로 변환."""
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(KST)


def _date_to_iso(value: Any) -> str | None:
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def _date_format(value: Any, fmt: str) -> str | None:
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    return parsed.strftime(_coerce_str(fmt))


# ---------------------------------------------------------------------------
# phone.* — 한국 전화번호 정규화 (E.164 변환은 Phase 6 후속).
# ---------------------------------------------------------------------------
_PHONE_DIGITS_RE = re.compile(r"\D+")


def _phone_normalize_kr(value: Any) -> str | None:
    """한국 휴대전화/유선 → 'XXX-XXXX-XXXX' 형식. 길이 9~11 만 허용."""
    if value is None or value == "":
        return None
    digits = _PHONE_DIGITS_RE.sub("", _coerce_str(value))
    # 국제 형식 +82 → 0 접두로 정규화 후 길이 검사.
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    if not (9 <= len(digits) <= 11):
        raise FunctionCallError(f"phone.normalize_kr: invalid length {len(digits)}")
    if len(digits) == 11:
        return f"{digits[0:3]}-{digits[3:7]}-{digits[7:11]}"
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return f"{digits[0:2]}-{digits[2:5]}-{digits[5:9]}"


# ---------------------------------------------------------------------------
# address.* — 주소 토큰화 (간이 휴리스틱; 상세는 Phase 6 외부 API).
# ---------------------------------------------------------------------------
_SIDO_LIST: tuple[str, ...] = (
    "서울특별시", "서울시", "서울",
    "부산광역시", "부산시", "부산",
    "대구광역시", "대구시", "대구",
    "인천광역시", "인천시", "인천",
    "광주광역시", "광주시", "광주",
    "대전광역시", "대전시", "대전",
    "울산광역시", "울산시", "울산",
    "세종특별자치시", "세종시", "세종",
    "경기도", "경기",
    "강원특별자치도", "강원도", "강원",
    "충청북도", "충북",
    "충청남도", "충남",
    "전북특별자치도", "전라북도", "전북",
    "전라남도", "전남",
    "경상북도", "경북",
    "경상남도", "경남",
    "제주특별자치도", "제주도", "제주",
)


def _address_extract_sido(value: Any) -> str | None:
    """주소 문자열에서 시·도 토큰을 가장 긴 매치로 반환. 미매치 시 None."""
    if value is None:
        return None
    s = _coerce_str(value).strip()
    if not s:
        return None
    for token in sorted(_SIDO_LIST, key=len, reverse=True):
        if s.startswith(token):
            return token
    return None


_SIGUNGU_RE = re.compile(r"([가-힣]+(?:시|군|구))")


def _address_extract_sigungu(value: Any) -> str | None:
    """첫 번째로 등장하는 '...시/군/구' 토큰 반환."""
    if value is None:
        return None
    s = _coerce_str(value).strip()
    sido = _address_extract_sido(s)
    rest = s[len(sido):].lstrip() if sido else s
    m = _SIGUNGU_RE.search(rest)
    if m is None:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# json.* — JSONPath-lite + serialize/parse.
# ---------------------------------------------------------------------------
def _json_get_path(value: Any, path: str) -> Any:
    """`a.b.c` 또는 `a.b[0].c` 의 value 를 안전 추출. 없으면 None."""
    if value is None:
        return None
    parts = _coerce_str(path).replace("[", ".[").split(".")
    cur: Any = value
    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            try:
                idx = int(part[1:-1])
            except ValueError:
                return None
            if not isinstance(cur, list) or idx >= len(cur) or idx < -len(cur):
                return None
            cur = cur[idx]
            continue
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _json_to_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_parse(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict | list):
        return value
    try:
        return json.loads(_coerce_str(value))
    except json.JSONDecodeError as exc:
        raise FunctionCallError(f"json.parse: invalid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# hash.* / id.*
# ---------------------------------------------------------------------------
def _hash_sha256(value: Any) -> str:
    return hashlib.sha256(_coerce_str(value).encode("utf-8")).hexdigest()


def _hash_md5(value: Any) -> str:
    return hashlib.md5(
        _coerce_str(value).encode("utf-8")
    ).hexdigest()


def _id_make_content_hash(*parts: Any) -> str:
    """parts 를 `|` 로 join 후 sha256. raw 행의 idempotency key 표준."""
    joined = "|".join(_coerce_str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _id_slugify(value: Any) -> str:
    s = unicodedata.normalize("NFKD", _coerce_str(value)).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    return _SLUG_NON_ALNUM.sub("-", s).strip("-")


# ---------------------------------------------------------------------------
# helpers — 강제 변환.
# ---------------------------------------------------------------------------
def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return _date_parse(value)


# ---------------------------------------------------------------------------
# 등록 — name → spec.
# ---------------------------------------------------------------------------
FUNCTION_REGISTRY: dict[str, FunctionSpec] = {
    spec.name: spec
    for spec in (
        # text
        FunctionSpec("text.trim", "text", _text_trim, "공백 제거", 1, 1),
        FunctionSpec("text.upper", "text", _text_upper, "대문자", 1, 1),
        FunctionSpec("text.lower", "text", _text_lower, "소문자", 1, 1),
        FunctionSpec(
            "text.normalize_unicode_nfc",
            "text",
            _text_normalize_unicode_nfc,
            "유니코드 NFC 정규화",
            1, 1,
        ),
        FunctionSpec("text.replace", "text", _text_replace, "치환", 3, 3),
        FunctionSpec(
            "text.regex_extract", "text", _text_regex_extract,
            "정규식 추출 (group 인자, 기본 0)", 2, 3,
        ),
        FunctionSpec("text.starts_with", "text", _text_starts_with, "접두사 검사", 2, 2),
        FunctionSpec("text.length", "text", _text_length, "문자열 길이", 1, 1),
        # number
        FunctionSpec(
            "number.parse_decimal", "number", _number_parse_decimal,
            "Decimal 파싱 (콤마/공백 제거)", 1, 1,
        ),
        FunctionSpec(
            "number.round_n", "number", _number_round_n,
            "소수점 N 자리 반올림 (banker's)", 1, 2,
        ),
        FunctionSpec("number.abs", "number", _number_abs, "절댓값", 1, 1),
        FunctionSpec("number.clamp", "number", _number_clamp, "lo/hi 범위 제한", 3, 3),
        # date
        FunctionSpec(
            "date.parse", "date", _date_parse,
            "ISO/YYYYMMDD 등 자동 파싱 (fmt 옵션)", 1, 2,
        ),
        FunctionSpec("date.to_kst", "date", _date_to_kst, "UTC/naive → KST", 1, 1),
        FunctionSpec("date.to_iso", "date", _date_to_iso, "ISO8601 문자열", 1, 1),
        FunctionSpec("date.format", "date", _date_format, "strftime 포맷", 2, 2),
        # phone
        FunctionSpec(
            "phone.normalize_kr", "phone", _phone_normalize_kr,
            "한국 전화번호 정규화 (XXX-XXXX-XXXX)", 1, 1,
        ),
        # address
        FunctionSpec(
            "address.extract_sido", "address", _address_extract_sido,
            "주소에서 시·도 추출", 1, 1,
        ),
        FunctionSpec(
            "address.extract_sigungu", "address", _address_extract_sigungu,
            "주소에서 시/군/구 추출", 1, 1,
        ),
        # json
        FunctionSpec("json.get_path", "json", _json_get_path, "JSONPath-lite 추출", 2, 2),
        FunctionSpec("json.to_string", "json", _json_to_string, "JSON 직렬화", 1, 1),
        FunctionSpec("json.parse", "json", _json_parse, "JSON 파싱", 1, 1),
        # hash
        FunctionSpec("hash.sha256", "hash", _hash_sha256, "SHA-256", 1, 1),
        FunctionSpec("hash.md5", "hash", _hash_md5, "MD5", 1, 1),
        # id
        FunctionSpec(
            "id.make_content_hash", "id", _id_make_content_hash,
            "parts join sha256 — raw idempotency key", 1, None,
        ),
        FunctionSpec("id.slugify", "id", _id_slugify, "ASCII slug", 1, 1),
    )
}


def list_functions() -> list[FunctionSpec]:
    """레지스트리의 전체 함수 목록 (UX/문서용)."""
    return sorted(FUNCTION_REGISTRY.values(), key=lambda s: s.name)


def call_function(name: str, *args: Any, **kwargs: Any) -> Any:
    """allowlist 검증 후 호출. 미등록 함수면 `FunctionCallError`."""
    spec = FUNCTION_REGISTRY.get(name)
    if spec is None:
        raise FunctionCallError(f"function {name!r} is not in allowlist")
    n_args = len(args) + len(kwargs)
    if n_args < spec.arity_min:
        raise FunctionCallError(
            f"{name}: expected at least {spec.arity_min} args, got {n_args}"
        )
    if spec.arity_max is not None and n_args > spec.arity_max:
        raise FunctionCallError(
            f"{name}: expected at most {spec.arity_max} args, got {n_args}"
        )
    try:
        return spec.fn(*args, **kwargs)
    except FunctionCallError:
        raise
    except Exception as exc:
        raise FunctionCallError(f"{name}: {type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Mini-DSL — `func_name(arg, key=val, ...)` 형태만 허용.
#
# field_mapping.transform_expr / FUNCTION_TRANSFORM.config 의 표현식을 안전 파싱.
# eval() 절대 금지 — ast.parse(mode='eval') 로 *호출 1개* 만 허용, 인자는 literal 만.
# ---------------------------------------------------------------------------
_LITERAL_TYPES = (
    ast.Constant,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.UnaryOp,
)


def _eval_literal(node: ast.AST) -> Any:
    """ast.literal_eval 의 보조 — Tuple/List/Dict/UnaryOp 모두 처리.
    Name 노드는 *컨텍스트 변수* 로 caller 가 별도 처리하므로 여기선 거부.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _eval_literal(node.operand)
        if isinstance(v, int | float | Decimal):
            return -v
        raise FunctionCallError("unary minus only on numbers")
    if isinstance(node, ast.List):
        return [_eval_literal(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        keys: list[Any] = [_eval_literal(k) for k in node.keys if k is not None]
        vals: list[Any] = [_eval_literal(v) for v in node.values]
        return dict(zip(keys, vals, strict=False))
    raise FunctionCallError(f"unsupported literal node: {type(node).__name__}")


_COLUMN_REF_PREFIX = "__DPCOL__"
_COLUMN_REF_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")


def _encode_column_refs(expr: str) -> str:
    """`$col` → `__DPCOL__col` (ast.parse 통과 가능한 식별자)."""
    return _COLUMN_REF_RE.sub(lambda m: f"{_COLUMN_REF_PREFIX}{m.group(1)}", expr)


def apply_expression(
    expression: str,
    *,
    row: Mapping[str, Any] | None = None,
) -> Any:
    """transform_expr 평가 — 다음 형태만 허용:

      1. `func_name(arg, key=val, ...)` — 단일 함수 호출.
      2. `$col_name`  — row[col_name].
      3. literal      — 'foo', 42, True 등.

    인자도 literal 또는 `$col` 만. 중첩 호출은 미지원 (Phase 5 MVP).
    Phase 6 에서 chain 표현 검토.
    """
    if not expression:
        return None
    expr = expression.strip()
    encoded = _encode_column_refs(expr)
    try:
        parsed = ast.parse(encoded, mode="eval")
    except SyntaxError as exc:
        raise FunctionCallError(f"invalid expression: {exc}") from exc

    body = parsed.body
    # literal 단일 값.
    if isinstance(body, _LITERAL_TYPES):
        return _eval_literal(body)
    # `$col` → row[col].
    if isinstance(body, ast.Name):
        return _resolve_name(body, row)
    if not isinstance(body, ast.Call):
        raise FunctionCallError(f"expected function call, got {type(body).__name__}")

    func_name = _resolve_func_name(body.func)
    args: list[Any] = [_resolve_arg(a, row) for a in body.args]
    kwargs: dict[str, Any] = {}
    for kw in body.keywords:
        if kw.arg is None:
            raise FunctionCallError("**kwargs not supported")
        kwargs[kw.arg] = _resolve_arg(kw.value, row)
    return call_function(func_name, *args, **kwargs)


def _resolve_func_name(func: ast.AST) -> str:
    """`text.trim` 같은 dotted name 을 평탄화."""
    if isinstance(func, ast.Name):
        if func.id.startswith(_COLUMN_REF_PREFIX):
            raise FunctionCallError("column reference cannot be used as function name")
        return func.id
    if isinstance(func, ast.Attribute):
        head = _resolve_func_name(func.value)
        return f"{head}.{func.attr}"
    raise FunctionCallError(f"unsupported function reference: {ast.dump(func)}")


def _resolve_name(node: ast.Name, row: Mapping[str, Any] | None) -> Any:
    if node.id.startswith(_COLUMN_REF_PREFIX):
        col = node.id[len(_COLUMN_REF_PREFIX):]
        if row is None:
            raise FunctionCallError(f"row is required for column ref ${col}")
        return row.get(col)
    raise FunctionCallError(
        f"bare identifier {node.id!r} not allowed; use $col for row reference"
    )


def _resolve_arg(node: ast.AST, row: Mapping[str, Any] | None) -> Any:
    """literal 또는 `$col` 만 허용. 중첩 함수 호출 미지원."""
    if isinstance(node, ast.Name):
        return _resolve_name(node, row)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _eval_literal(node)
    if isinstance(node, _LITERAL_TYPES):
        return _eval_literal(node)
    raise FunctionCallError(f"unsupported argument node: {type(node).__name__}")


__all__ = [
    "FUNCTION_REGISTRY",
    "FunctionCallError",
    "FunctionSpec",
    "apply_expression",
    "call_function",
    "list_functions",
]
