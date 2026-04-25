"""SQLAlchemy 기반 SourceDb 어댑터 — PostgreSQL/MySQL 동시 지원.

URL 형태:
  - postgresql: `postgresql+psycopg://user:pw@host:port/database`
  - mysql:      `mysql+pymysql://user:pw@host:port/database`

소스 테이블 식별자(`schema.table`) 는 동적이라 SQLAlchemy `quoted_name` 으로 식별자
이스케이프. 본문은 parameterized query 만 — SQL injection 방지.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.integrations.sourcedb.types import SourceDbBatch, SourceDbConfig, SourceDbError


def _build_url(config: SourceDbConfig) -> str:
    if config.driver == "postgresql":
        scheme = "postgresql+psycopg"
    elif config.driver == "mysql":
        scheme = "mysql+pymysql"
    else:  # pragma: no cover — Literal 가 막아줌.
        raise SourceDbError(f"unsupported driver: {config.driver}")
    pw = quote_plus(config.password) if config.password else ""
    auth = f"{quote_plus(config.user)}:{pw}@" if config.user else ""
    return f"{scheme}://{auth}{config.host}:{config.port}/{config.database}"


def _qualified_table(config: SourceDbConfig) -> str:
    """`"schema"."table"` 또는 `` `db`.`table` `` 형태로 식별자 인용."""
    if config.driver == "postgresql" and config.schema:
        return f'"{config.schema}"."{config.table}"'
    if config.driver == "mysql":
        return f"`{config.database}`.`{config.table}`"
    return f'"{config.table}"'


def _columns_clause(config: SourceDbConfig) -> str:
    if not config.select_columns or list(config.select_columns) == ["*"]:
        return "*"
    if config.driver == "postgresql":
        return ", ".join(f'"{c}"' for c in config.select_columns)
    return ", ".join(f"`{c}`" for c in config.select_columns)


def _cursor_ident(config: SourceDbConfig) -> str:
    if config.driver == "postgresql":
        return f'"{config.cursor_column}"'
    return f"`{config.cursor_column}`"


class SqlAlchemySourceDb:
    """`SourceDbConnector` 구현 — Engine 1개를 인스턴스 lifecycle 동안 보유."""

    def __init__(self, config: SourceDbConfig) -> None:
        self.name = f"{config.driver}:{config.host}:{config.database}.{config.table}"
        self._config = config
        try:
            self._engine: Engine = create_engine(
                _build_url(config),
                pool_size=2,
                max_overflow=2,
                pool_pre_ping=True,
                future=True,
            )
        except SQLAlchemyError as exc:
            raise SourceDbError(f"engine init failed: {exc}") from exc

    def fetch_incremental(
        self,
        *,
        cursor_value: Any,
        batch_size: int,
    ) -> SourceDbBatch:
        if batch_size <= 0:
            raise SourceDbError("batch_size must be > 0")

        cols = _columns_clause(self._config)
        table = _qualified_table(self._config)
        cursor_col = _cursor_ident(self._config)
        where_extra = f" AND ({self._config.extra_where})" if self._config.extra_where else ""

        # cursor_value 가 None 이면 "처음부터" — IS NOT NULL 만 걸어 전체 fetch.
        if cursor_value is None:
            sql = text(
                f"SELECT {cols} FROM {table} "
                f"WHERE {cursor_col} IS NOT NULL{where_extra} "
                f"ORDER BY {cursor_col} ASC LIMIT :limit"
            )
            params: dict[str, Any] = {"limit": batch_size}
        else:
            sql = text(
                f"SELECT {cols} FROM {table} "
                f"WHERE {cursor_col} > :cursor{where_extra} "
                f"ORDER BY {cursor_col} ASC LIMIT :limit"
            )
            params = {"cursor": cursor_value, "limit": batch_size}

        try:
            with self._engine.connect() as conn:
                result = conn.execute(sql, params)
                rows: Sequence[dict[str, Any]] = [dict(row) for row in result.mappings()]
        except SQLAlchemyError as exc:
            raise SourceDbError(f"fetch failed: {exc}") from exc

        if rows:
            max_cursor: Any = rows[-1].get(self._config.cursor_column)
        else:
            max_cursor = cursor_value
        return SourceDbBatch(
            rows=tuple(rows),
            max_cursor=max_cursor,
            pulled_at_unix=time.time(),
        )

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._engine.dispose()


__all__ = ["SqlAlchemySourceDb"]
