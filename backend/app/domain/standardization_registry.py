"""Phase 5.1 Wave 3 — namespace-aware standardization registry.

도메인별 standardization 경로를 *DB registry* 에서 결정:
  domain.standard_code_namespace.std_code_table → strategy 자동 선택.

Strategy:
  * `alias_only` — pos 처럼 enum + alias 사전. `app.domain.std_alias`.
  * `embedding_3stage` — agri 처럼 trigram + embedding. `app.domain.standardization`
    (v1 기존 모듈 재사용).
  * `noop` — 표준화 미적용 (raw 그대로 보존).

본 모듈은 *strategy 결정 + 적용 함수 dispatch* 만. 실 매칭 로직은 각 모듈에 위임.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class StdStrategy(StrEnum):
    ALIAS_ONLY = "alias_only"
    EMBEDDING_3STAGE = "embedding_3stage"
    NOOP = "noop"


# strategy 결정 룰 — namespace 별 명시. yaml schema 확장 시 자동 추론으로 변경.
_STRATEGY_OVERRIDES: dict[tuple[str, str], StdStrategy] = {
    ("agri", "AGRI_FOOD"): StdStrategy.EMBEDDING_3STAGE,
    ("pos", "PAYMENT_METHOD"): StdStrategy.ALIAS_ONLY,
    ("pos", "STORE_CHANNEL"): StdStrategy.ALIAS_ONLY,
}


@dataclass(slots=True, frozen=True)
class NamespaceSpec:
    domain_code: str
    name: str
    std_code_table: str | None
    strategy: StdStrategy


def resolve_namespace(
    session: Session, *, domain_code: str, namespace: str
) -> NamespaceSpec | None:
    """domain.standard_code_namespace 조회 + strategy 결정."""
    row = session.execute(
        text(
            "SELECT name, std_code_table FROM domain.standard_code_namespace "
            "WHERE domain_code = :d AND name = :n LIMIT 1"
        ),
        {"d": domain_code, "n": namespace},
    ).first()
    if row is None:
        return None
    strategy = _STRATEGY_OVERRIDES.get((domain_code, namespace), StdStrategy.NOOP)
    return NamespaceSpec(
        domain_code=domain_code,
        name=str(row.name),
        std_code_table=str(row.std_code_table) if row.std_code_table else None,
        strategy=strategy,
    )


def standardize_value(
    session: Session,
    *,
    domain_code: str,
    namespace: str,
    raw_value: str,
) -> tuple[str, str]:
    """raw → (std_code, matched_via). 미해결 값은 raw 그대로 반환 (noop)."""
    spec = resolve_namespace(
        session, domain_code=domain_code, namespace=namespace
    )
    if spec is None:
        return raw_value, "noop_no_namespace"

    if spec.strategy == StdStrategy.ALIAS_ONLY:
        from app.domain.std_alias import lookup_alias

        match = lookup_alias(
            session,
            domain_code=domain_code,
            namespace=namespace,
            raw_value=raw_value,
        )
        return match.std_code, match.matched_via

    if spec.strategy == StdStrategy.EMBEDDING_3STAGE:
        # v1 의 standardization 모듈 재사용 — 임베딩 + trigram + crowd.
        # embedding_client=None → trigram 만 (외부 API 호출 회피, generic node 안전).
        try:
            from app.domain.standardization import resolve_std_code

            res = resolve_std_code(session, raw_value, embedding_client=None)
            return (res.std_code or raw_value, res.strategy)
        except Exception as exc:
            logger.warning(
                "embedding_3stage failed for (%s,%s,%s): %s",
                domain_code,
                namespace,
                raw_value,
                exc,
            )
            return raw_value, "noop_embedding_failed"

    return raw_value, "noop"


def standardize_column(
    session: Session,
    *,
    domain_code: str,
    namespace: str,
    target_table: str,
    raw_column: str,
    std_column: str,
    where_clause: str = "TRUE",
    where_params: Mapping[str, object] | None = None,
    limit_rows: int = 100_000,
) -> dict[str, int]:
    """target_table.raw_column 일괄 표준화. strategy 별 dispatch."""
    spec = resolve_namespace(
        session, domain_code=domain_code, namespace=namespace
    )
    if spec is None or spec.strategy == StdStrategy.NOOP:
        return {"matched": 0, "fallback": 0, "skipped_no_strategy": 1}

    if spec.strategy == StdStrategy.ALIAS_ONLY:
        from app.domain.std_alias import standardize_column_in_table

        return standardize_column_in_table(
            session,
            domain_code=domain_code,
            namespace=namespace,
            target_table=target_table,
            raw_column=raw_column,
            std_column=std_column,
            where_clause=where_clause,
            where_params=dict(where_params or {}),
            limit_rows=limit_rows,
        )

    # EMBEDDING_3STAGE — row 단위. 대량은 v1 transform_worker 권장.
    counts = {"matched": 0, "fallback": 0, "embedding_calls": 0}
    rows = session.execute(
        text(
            f'SELECT DISTINCT "{raw_column}" AS rv '
            f'FROM "{target_table.split(".")[0]}"."{target_table.split(".")[1]}" '
            f"WHERE ({where_clause}) AND \"{std_column}\" IS NULL "
            f"LIMIT :lim"
        ),
        {**dict(where_params or {}), "lim": limit_rows},
    ).all()
    for r in rows:
        if r.rv is None:
            continue
        std_code, _matched_via = standardize_value(
            session,
            domain_code=domain_code,
            namespace=namespace,
            raw_value=str(r.rv),
        )
        counts["embedding_calls"] += 1
        if std_code != r.rv:
            counts["matched"] += 1
        else:
            counts["fallback"] += 1
        session.execute(
            text(
                f'UPDATE "{target_table.split(".")[0]}"."{target_table.split(".")[1]}" '
                f'SET "{std_column}" = :sc '
                f'WHERE "{raw_column}" = :rv AND "{std_column}" IS NULL'
            ),
            {"sc": std_code, "rv": r.rv},
        )
    return counts


__all__ = [
    "NamespaceSpec",
    "StdStrategy",
    "resolve_namespace",
    "standardize_column",
    "standardize_value",
]
