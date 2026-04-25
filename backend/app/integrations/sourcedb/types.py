"""SourceDb 추상 타입 — 도메인이 의존하는 인터페이스.

다른 driver(예: Oracle/MSSQL) 도입 시 같은 Protocol 구현만 추가.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


class SourceDbError(Exception):
    """소스 DB 호출 실패. caller 가 일시/영구 분리."""


@dataclass(slots=True, frozen=True)
class SourceDbConfig:
    """ctl.data_source.config_json 에 저장되는 connection 정보.

    - `driver` 는 SQLAlchemy URL prefix 와 매칭. postgresql / mysql 만 우선 지원.
    - `cursor_column` 은 incremental fetch 의 watermark 컬럼. ORDER BY 키.
    - `secret_ref` 는 비밀번호 등 secret manager / env 키 — 실제 password 는 별도
      lookup. Phase 2 단순화로 평문 password 도 허용 (`password` 필드).
    """

    driver: Literal["postgresql", "mysql"]
    host: str
    port: int
    database: str
    schema: str | None  # postgresql 에서 사용. mysql 은 None.
    table: str
    cursor_column: str
    user: str
    password: str = ""
    select_columns: Sequence[str] = field(default_factory=lambda: ["*"])
    extra_where: str | None = None  # 안전한 정적 표현 — 사용자 입력 직결 금지.


@dataclass(slots=True, frozen=True)
class SourceDbBatch:
    """fetch_incremental 1회 호출 결과."""

    rows: Sequence[dict[str, Any]]
    max_cursor: Any  # rows 가 비면 호출 전 cursor_value 가 그대로 들어옴.
    pulled_at_unix: float


@runtime_checkable
class SourceDbConnector(Protocol):
    """도메인이 보는 단일 인터페이스."""

    name: str

    def fetch_incremental(
        self,
        *,
        cursor_value: Any,
        batch_size: int,
    ) -> SourceDbBatch: ...

    def close(self) -> None: ...
