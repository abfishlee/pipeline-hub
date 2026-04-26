"""트랜잭션 rollback 기반 dry-run helper.

5.2.4 의 Mart Designer / DQ Rule Builder 가 *실 mart 변경 없이* 검증하기 위한 공통
인프라. 5.2.0 단계는 generic helper 만 제공 — entity 별 사용은 5.2.1+.

원리:
  1. 새 트랜잭션 시작
  2. SQL/명령 실행
  3. row_count / 영향 받은 row 수 / 에러 / 경고 수집
  4. **항상 ROLLBACK** — 실 데이터 변경 0

사용 예 (Mart Designer 의 LOAD_TARGET 미리보기):

    >>> result = run_dry(
    ...     engine=sync_engine,
    ...     queries=[
    ...         "INSERT INTO mart.price_fact (...) SELECT ... FROM stg.cleaned",
    ...     ],
    ...     fetch_after=[
    ...         "SELECT COUNT(*) FROM mart.price_fact WHERE observed_at::date = current_date"
    ...     ],
    ... )
    >>> result.row_counts  # [365]
    >>> result.errors      # []

주의:
  - 본 helper 는 *sync engine* 사용. 비동기 호출자는 asyncio.to_thread.
  - 한 트랜잭션 안에서 실행되므로 *외부 사이드 이펙트* (SAVEPOINT 외부 NOTIFY,
    pg_notify, 외부 API 호출 등) 는 rollback 안 됨. 호출 전 가드 필요.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DryRunResult:
    """실행 결과 — 모두 rollback 됨."""

    rows_affected: list[int] = field(default_factory=list)  # INSERT/UPDATE/DELETE 영향
    row_counts: list[int] = field(default_factory=list)     # fetch_after 의 결과
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    rolled_back: bool = True


def run_dry(
    *,
    engine: Engine,
    queries: Sequence[str],
    fetch_after: Sequence[str] = (),
    parameters: Sequence[dict[str, Any]] | None = None,
) -> DryRunResult:
    """queries 를 한 트랜잭션 안에서 실행 + fetch_after 의 SELECT 결과 row_count.

    queries 와 parameters 는 1:1. parameters 없으면 빈 dict 로 처리.
    트랜잭션은 *항상 ROLLBACK*.
    """
    params_list: list[dict[str, Any]] = list(parameters or [{} for _ in queries])
    if len(params_list) != len(queries):
        raise ValueError(
            f"queries and parameters length mismatch ({len(queries)} vs {len(params_list)})"
        )

    result = DryRunResult()
    started = time.perf_counter()
    conn = engine.connect()
    trans = conn.begin()
    try:
        for sql, params in zip(queries, params_list, strict=False):
            cursor_result = conn.execute(text(sql), params)
            # rowcount 가 -1 이면 dialect 가 미보고 — 0 으로 기록.
            result.rows_affected.append(max(0, int(cursor_result.rowcount or 0)))
        for sql in fetch_after:
            scalar = conn.execute(text(sql)).scalar_one_or_none()
            result.row_counts.append(int(scalar) if scalar is not None else 0)
    except Exception as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}"[:1000])
    finally:
        # 항상 rollback — 본 helper 의 *불변 조건*.
        import contextlib

        with contextlib.suppress(Exception):
            trans.rollback()
        with contextlib.suppress(Exception):
            conn.close()
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        result.rolled_back = True
    logger.info(
        "dry_run.completed queries=%s rows_affected=%s row_counts=%s duration_ms=%s errors=%s",
        len(queries),
        result.rows_affected,
        result.row_counts,
        result.duration_ms,
        len(result.errors),
    )
    return result


__all__ = ["DryRunResult", "run_dry"]
