"""Phase 5.2.6 STEP 9 — alias-based 표준화 (POS payment_method 등).

POS 같은 거래 도메인은 임베딩 매칭 없이 alias 사전 만으로 충분 (Q3 답변 — 결제수단
7종 + alias 약 15~20개).

본 모듈은 도메인의 *standard_code_namespace* + alias 테이블 (`<schema>.<table>_alias`)
을 조회하여 raw → std_code 매핑.

agri 의 임베딩 + 3단계 폴백 (`app.domain.standardization`) 과 다른 *light-weight*
경로 — 새 도메인 검증의 KPI 척도 중 하나 (pos 가 별도 코드 없이 alias 매핑만으로 동작).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class AliasMatch:
    std_code: str
    matched_via: str  # 'std_code' | 'alias' | 'fallback_other'


# 도메인-namespace → (std_table, alias_table, fallback_code) 등록.
_ALIAS_REGISTRY: Final[dict[tuple[str, str], tuple[str, str, str]]] = {
    ("pos", "PAYMENT_METHOD"): (
        "pos_mart.std_payment_method",
        "pos_mart.std_payment_method_alias",
        "OTHER",
    ),
    ("pos", "STORE_CHANNEL"): (
        "pos_mart.std_store_channel",
        "",
        "OTHER",
    ),
}


def lookup_alias(
    session: Session,
    *,
    domain_code: str,
    namespace: str,
    raw_value: str,
) -> AliasMatch:
    """raw_value → std_code. 매치 실패 시 fallback (예: 'OTHER').

    검색 순서:
      1. raw_value 가 std_code 자체와 정확히 일치 → 'std_code'.
      2. alias 테이블에서 1:1 매치 → 'alias'.
      3. fallback (등록 없으면 raw_value 그대로 반환).
    """
    key = (domain_code, namespace)
    if key not in _ALIAS_REGISTRY:
        return AliasMatch(std_code=raw_value, matched_via="fallback_other")

    std_table, alias_table, fallback = _ALIAS_REGISTRY[key]

    direct = session.execute(
        text(
            f"SELECT std_code FROM {std_table} "
            "WHERE std_code = :rv AND is_active = TRUE LIMIT 1"
        ),
        {"rv": raw_value},
    ).scalar_one_or_none()
    if direct:
        return AliasMatch(std_code=str(direct), matched_via="std_code")

    if alias_table:
        via_alias = session.execute(
            text(
                f"SELECT std_code FROM {alias_table} WHERE alias = :rv LIMIT 1"
            ),
            {"rv": raw_value},
        ).scalar_one_or_none()
        if via_alias:
            return AliasMatch(std_code=str(via_alias), matched_via="alias")

    return AliasMatch(std_code=fallback, matched_via="fallback_other")


_SAFE_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def standardize_column_in_table(
    session: Session,
    *,
    domain_code: str,
    namespace: str,
    target_table: str,
    raw_column: str,
    std_column: str,
    where_clause: str = "TRUE",
    where_params: dict[str, object] | None = None,
    limit_rows: int = 100_000,
) -> dict[str, int]:
    """target_table.raw_column 의 값을 std_column 으로 멱등 채움.

    UPDATE 는 row 단위 — 100k 미만 sandbox 검증 + 실 production 은 별도 worker.
    빈 std 만 채우는 멱등 (재실행 안전).

    반환: {'matched_via_std_code': N, 'matched_via_alias': M, 'fallback': K}.
    """
    if not _SAFE_IDENT_RE.match(raw_column) or not _SAFE_IDENT_RE.match(std_column):
        raise ValueError(f"unsafe column names: {raw_column!r}, {std_column!r}")
    if "." not in target_table:
        raise ValueError(f"target_table must be schema.table (got {target_table!r})")
    schema, name = target_table.split(".", 1)
    if not _SAFE_IDENT_RE.match(schema) or not _SAFE_IDENT_RE.match(name):
        raise ValueError(f"unsafe target_table: {target_table!r}")

    rows = session.execute(
        text(
            f'SELECT DISTINCT "{raw_column}" AS rv '
            f'FROM "{schema}"."{name}" '
            f"WHERE ({where_clause}) AND \"{std_column}\" IS NULL "
            f"LIMIT :lim"
        ),
        {**(where_params or {}), "lim": limit_rows},
    ).all()

    counts = {"matched_via_std_code": 0, "matched_via_alias": 0, "fallback": 0}
    for r in rows:
        raw_value = r.rv
        if raw_value is None:
            continue
        match = lookup_alias(
            session,
            domain_code=domain_code,
            namespace=namespace,
            raw_value=str(raw_value),
        )
        if match.matched_via == "std_code":
            counts["matched_via_std_code"] += 1
        elif match.matched_via == "alias":
            counts["matched_via_alias"] += 1
        else:
            counts["fallback"] += 1
        session.execute(
            text(
                f'UPDATE "{schema}"."{name}" '
                f'SET "{std_column}" = :sc '
                f'WHERE "{raw_column}" = :rv AND "{std_column}" IS NULL'
            ),
            {"sc": match.std_code, "rv": raw_value},
        )
    return counts


__all__ = [
    "AliasMatch",
    "lookup_alias",
    "standardize_column_in_table",
]
