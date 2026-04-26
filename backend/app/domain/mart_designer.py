"""Mart Designer (Phase 5.2.4 STEP 7 Q2).

UI 의 컬럼/타입/key/partition 폼 → 안전한 DDL 텍스트 생성 + diff 요약.

흐름:
  1. UI 가 spec (table_name, columns[], primary_key[], partition_key, indexes[]) 전달.
  2. 본 모듈이 *idempotent* DDL (CREATE TABLE IF NOT EXISTS 또는 ALTER) 생성.
  3. domain.mart_design_draft 에 DRAFT 로 INSERT.
  4. 상태머신: DRAFT → REVIEW → APPROVED → (alembic 적용) PUBLISHED.
  5. local/dev = ADMIN 승인 후 자동 적용 가능 (Q2 답변).
     staging/prod = release migration 으로 분리 (PR 검토).

가드:
  - 도메인별 schema (`<domain>_mart`) 또는 mart 만 허용.
  - 컬럼명/테이블명/타입은 화이트리스트 (`Text/Integer/BigInt/Numeric/Bool/Timestamp/...`).
  - 기존 테이블에 *새 컬럼* (NULL 허용) 만 ALTER 가능. drop/rename 금지 (별도 ADR).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_SAFE_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "TEXT",
        "VARCHAR",
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "NUMERIC",
        "DECIMAL",
        "REAL",
        "DOUBLE PRECISION",
        "BOOLEAN",
        "DATE",
        "TIMESTAMP",
        "TIMESTAMPTZ",
        "TIMESTAMP WITH TIME ZONE",
        "JSONB",
        "JSON",
        "UUID",
        "BYTEA",
    }
)


class MartDesignError(ValueError):
    """입력 spec 위반."""


@dataclass(slots=True, frozen=True)
class ColumnSpec:
    name: str
    type: str
    nullable: bool = True
    default: str | None = None
    description: str | None = None


@dataclass(slots=True, frozen=True)
class IndexSpec:
    name: str
    columns: tuple[str, ...]
    unique: bool = False


@dataclass(slots=True)
class MartDesignSpec:
    domain_code: str
    target_table: str  # `<schema>.<table>` FQDN
    columns: list[ColumnSpec]
    primary_key: list[str] = field(default_factory=list)
    partition_key: str | None = None
    indexes: list[IndexSpec] = field(default_factory=list)
    description: str | None = None


@dataclass(slots=True)
class DesignResult:
    ddl_text: str
    diff_summary: dict[str, Any]
    is_alter: bool


def _validate_ident(label: str, value: str) -> str:
    if not _SAFE_IDENT_RE.match(value):
        raise MartDesignError(f"{label} {value!r} is not a safe identifier")
    return value


def _validate_type(t: str) -> str:
    upper = t.upper().strip()
    if upper not in _ALLOWED_TYPES:
        raise MartDesignError(
            f"type {t!r} not in allowlist (allowed: {sorted(_ALLOWED_TYPES)})"
        )
    return upper


def _allowed_target_schemas(domain_code: str) -> frozenset[str]:
    return frozenset({"mart", f"{domain_code.lower()}_mart"})


def _split_fqdn(table: str) -> tuple[str, str]:
    if "." not in table:
        raise MartDesignError(f"target_table must be schema.table (got {table!r})")
    schema, name = table.split(".", 1)
    return _validate_ident("schema", schema), _validate_ident("table", name)


def _columns_present(session: Session, *, schema: str, table: str) -> list[str]:
    rows = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            "ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    ).all()
    return [str(r.column_name) for r in rows]


def _table_exists(session: Session, *, schema: str, table: str) -> bool:
    return bool(_columns_present(session, schema=schema, table=table))


def _column_ddl(col: ColumnSpec) -> str:
    parts = [f'"{_validate_ident("column", col.name)}"', _validate_type(col.type)]
    parts.append("NULL" if col.nullable else "NOT NULL")
    if col.default is not None:
        # default 는 *literal* 만 — DDL injection 회피.
        if not re.match(r"^[A-Za-z0-9_'\"\(\)\.,:\-\+ ]{0,200}$", col.default):
            raise MartDesignError(
                f"column {col.name} default contains unsafe chars"
            )
        parts.append(f"DEFAULT {col.default}")
    return " ".join(parts)


def design_table(
    session: Session, spec: MartDesignSpec
) -> DesignResult:
    """spec → DDL + diff. 기존 테이블 있으면 ALTER (새 NULL 컬럼 추가만).

    drop/rename 은 본 함수 범위 밖 — 별도 운영자 작업 (ADR-0021 예정).
    """
    schema, table_name = _split_fqdn(spec.target_table)
    allowed = _allowed_target_schemas(spec.domain_code)
    if schema.lower() not in allowed:
        raise MartDesignError(
            f"schema {schema!r} not allowed for domain {spec.domain_code} "
            f"(allowed: {sorted(allowed)})"
        )

    for col in spec.columns:
        _validate_ident("column", col.name)
        _validate_type(col.type)

    for k in spec.primary_key:
        if not any(c.name == k for c in spec.columns):
            raise MartDesignError(f"primary_key column {k!r} not in columns")
    if spec.partition_key and not any(
        c.name == spec.partition_key for c in spec.columns
    ):
        raise MartDesignError(
            f"partition_key {spec.partition_key!r} not in columns"
        )

    existing = _columns_present(session, schema=schema, table=table_name)
    is_alter = bool(existing)

    if not is_alter:
        # CREATE TABLE.
        col_defs = [_column_ddl(c) for c in spec.columns]
        if spec.primary_key:
            quoted_pk = ", ".join(f'"{k}"' for k in spec.primary_key)
            col_defs.append(f"CONSTRAINT pk_{table_name} PRIMARY KEY ({quoted_pk})")
        ddl_lines = [
            f'CREATE TABLE IF NOT EXISTS "{schema}"."{table_name}" (',
            "    " + ",\n    ".join(col_defs),
            ")",
        ]
        if spec.partition_key:
            ddl_lines.append(f'PARTITION BY RANGE ("{spec.partition_key}")')
        ddl_text = "\n".join(ddl_lines) + ";"
        # 인덱스.
        for idx in spec.indexes:
            for c in idx.columns:
                _validate_ident("index_column", c)
            _validate_ident("index_name", idx.name)
            unique = "UNIQUE " if idx.unique else ""
            ddl_text += (
                f'\nCREATE {unique}INDEX IF NOT EXISTS "{idx.name}" '
                f'ON "{schema}"."{table_name}" '
                f"({', '.join(f'\"{c}\"' for c in idx.columns)});"
            )
        diff_summary = {
            "kind": "create",
            "schema": schema,
            "table": table_name,
            "columns_added": [c.name for c in spec.columns],
            "primary_key": list(spec.primary_key),
            "partition_key": spec.partition_key,
            "indexes_added": [idx.name for idx in spec.indexes],
        }
        return DesignResult(ddl_text=ddl_text, diff_summary=diff_summary, is_alter=False)

    # ALTER — 새 NULL 컬럼만 추가.
    new_cols = [c for c in spec.columns if c.name not in existing]
    if not new_cols:
        return DesignResult(
            ddl_text="-- no new columns; existing table unchanged",
            diff_summary={
                "kind": "noop",
                "schema": schema,
                "table": table_name,
                "existing": existing,
            },
            is_alter=True,
        )
    not_null = [c for c in new_cols if not c.nullable and c.default is None]
    if not_null:
        raise MartDesignError(
            f"cannot add NOT NULL columns without DEFAULT: {[c.name for c in not_null]}"
        )
    statements = [
        f'ALTER TABLE "{schema}"."{table_name}" ADD COLUMN {_column_ddl(c)};'
        for c in new_cols
    ]
    ddl_text = "\n".join(statements)
    diff_summary = {
        "kind": "alter",
        "schema": schema,
        "table": table_name,
        "columns_added": [c.name for c in new_cols],
        "existing_columns": existing,
    }
    return DesignResult(ddl_text=ddl_text, diff_summary=diff_summary, is_alter=True)


def save_draft(
    session: Session,
    *,
    spec: MartDesignSpec,
    result: DesignResult,
    created_by: int | None,
) -> int:
    """DRAFT 상태로 domain.mart_design_draft 에 저장. draft_id 반환."""
    draft_id = session.execute(
        text(
            "INSERT INTO domain.mart_design_draft "
            "(domain_code, target_table, ddl_text, diff_summary, created_by, status) "
            "VALUES (:dom, :tt, :ddl, CAST(:diff AS JSONB), :by, 'DRAFT') "
            "RETURNING draft_id"
        ),
        {
            "dom": spec.domain_code,
            "tt": spec.target_table,
            "ddl": result.ddl_text,
            "diff": _to_json(result.diff_summary),
            "by": created_by,
        },
    ).scalar_one()
    return int(draft_id)


def _to_json(data: Mapping[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, default=str)


__all__ = [
    "ColumnSpec",
    "DesignResult",
    "IndexSpec",
    "MartDesignError",
    "MartDesignSpec",
    "design_table",
    "save_draft",
]
