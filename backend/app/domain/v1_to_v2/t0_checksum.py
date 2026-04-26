"""T0 snapshot — sha256 + partition 단위 checksum (Q3 답변).

PG의 `md5(string_agg(...))` 를 *전체 테이블* 에 적용하면 대용량 mart.price_fact 에서
부담이 큼 (single-pass scan). 본 모듈은 **월/일 partition 단위** 로 나눠 sha256 을 계산.

흐름:
  1. capture_table_snapshot(domain_code, resource_code, target_table,
                             partition_key='yymm') 호출.
  2. 본 모듈이 SELECT DISTINCT partition_key 로 partition 식별.
  3. 각 partition 마다 row_count + sha256(canonical row) → audit.t0_snapshot INSERT.
  4. 결과는 ShadowRun cutover 전후 동일성 검증에 사용.

canonical row 정의:
  - 각 row 의 *컬럼 값을 ordered* 으로 join → sha256.
  - timestamp/UUID 같은 row_changed_at 같은 변동 컬럼은 stable_columns 로만.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PartitionChecksum:
    partition_key: str | None
    partition_value: str | None
    row_count: int
    checksum: str


@dataclass(slots=True)
class T0SnapshotResult:
    domain_code: str
    resource_code: str
    target_table: str
    captured_at: datetime
    partitions: list[PartitionChecksum] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(p.row_count for p in self.partitions)


def _validate_ident(label: str, value: str) -> str:
    import re

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", value):
        raise ValueError(f"{label} {value!r} is not a safe identifier")
    return value


def _quote_table(table: str) -> tuple[str, str, str]:
    if "." not in table:
        raise ValueError(f"target_table must be schema.table (got {table!r})")
    schema, name = table.split(".", 1)
    return _validate_ident("schema", schema), _validate_ident("table", name), (
        f'"{schema}"."{name}"'
    )


def compute_partition_checksum(
    session: Session,
    *,
    target_table: str,
    stable_columns: Sequence[str],
    where_clause: str | None = None,
    where_params: dict[str, Any] | None = None,
    algo: str = "sha256",
) -> PartitionChecksum:
    """1 개 partition 의 row_count + sha256.

    canonical row = `|` 로 join 한 컬럼 값 (NULL → '\x01', 빈 문자열 → '\x02').
    검증을 위해 ORDER BY pk 보장.
    """
    if algo not in ("sha256", "md5"):
        raise ValueError(f"unsupported algo: {algo}")

    _, _, qualified = _quote_table(target_table)
    cols = [_validate_ident("column", c) for c in stable_columns]
    if not cols:
        raise ValueError("stable_columns must be non-empty")

    quoted_cols = ", ".join(f'"{c}"' for c in cols)
    sql = f"SELECT {quoted_cols} FROM {qualified}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    sql += f" ORDER BY {quoted_cols}"

    rows = session.execute(text(sql), where_params or {}).all()
    hasher = hashlib.sha256() if algo == "sha256" else hashlib.md5()
    for r in rows:
        canonical = "|".join(_canonical_value(v) for v in r)
        hasher.update(canonical.encode("utf-8"))
        hasher.update(b"\n")
    return PartitionChecksum(
        partition_key=None,
        partition_value=None,
        row_count=len(rows),
        checksum=hasher.hexdigest(),
    )


def _canonical_value(v: Any) -> str:
    if v is None:
        return "\x01"
    if v == "":
        return "\x02"
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _list_partition_values(
    session: Session,
    *,
    target_table: str,
    partition_key: str,
) -> list[str]:
    """partition_key 컬럼의 distinct 값 목록 (정렬)."""
    _, _, qualified = _quote_table(target_table)
    col = _validate_ident("partition_key", partition_key)
    rows = session.execute(
        text(f'SELECT DISTINCT "{col}" FROM {qualified} ORDER BY "{col}"')
    ).all()
    return [str(r[0]) for r in rows if r[0] is not None]


def capture_table_snapshot(
    session: Session,
    *,
    domain_code: str,
    resource_code: str,
    target_table: str,
    stable_columns: Sequence[str],
    partition_key: str | None = None,
    captured_at: datetime | None = None,
    algo: str = "sha256",
) -> T0SnapshotResult:
    """target_table 전체 또는 partition 단위 checksum 을 audit.t0_snapshot 에 기록.

    partition_key 가 None 이면 *전체 테이블* 1 행으로 기록. 있으면 distinct 값마다
    1 행. row_count + checksum 모두 보존.
    """
    when = captured_at or datetime.now(UTC)
    result = T0SnapshotResult(
        domain_code=domain_code,
        resource_code=resource_code,
        target_table=target_table,
        captured_at=when,
    )

    def _insert(part: PartitionChecksum) -> None:
        session.execute(
            text(
                "INSERT INTO audit.t0_snapshot "
                "(domain_code, resource_code, target_table, partition_key, "
                " partition_value, row_count, checksum, checksum_algo, captured_at) "
                "VALUES (:dom, :res, :tt, :pk, :pv, :rc, :ck, :algo, :ts) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "dom": domain_code,
                "res": resource_code,
                "tt": target_table,
                "pk": part.partition_key,
                "pv": part.partition_value,
                "rc": part.row_count,
                "ck": part.checksum,
                "algo": algo,
                "ts": when,
            },
        )

    if partition_key is None:
        part = compute_partition_checksum(
            session,
            target_table=target_table,
            stable_columns=stable_columns,
            algo=algo,
        )
        _insert(part)
        result.partitions.append(part)
        return result

    values = _list_partition_values(
        session, target_table=target_table, partition_key=partition_key
    )
    pk_quoted = _validate_ident("partition_key", partition_key)
    for val in values:
        sub = compute_partition_checksum(
            session,
            target_table=target_table,
            stable_columns=stable_columns,
            where_clause=f'"{pk_quoted}" = :pv',
            where_params={"pv": val},
            algo=algo,
        )
        sub_with_meta = PartitionChecksum(
            partition_key=partition_key,
            partition_value=val,
            row_count=sub.row_count,
            checksum=sub.checksum,
        )
        _insert(sub_with_meta)
        result.partitions.append(sub_with_meta)
    return result


__all__ = [
    "PartitionChecksum",
    "T0SnapshotResult",
    "capture_table_snapshot",
    "compute_partition_checksum",
]
