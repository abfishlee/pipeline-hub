"""외부 소스 DB 어댑터 (Phase 2.2.7).

도메인은 `SourceDbConnector` Protocol 만 본다 — PostgreSQL/MySQL 구현은 이 패키지
내부에 격리. SQLAlchemy `create_engine` 으로 driver 자동 매칭.
"""

from __future__ import annotations

from app.integrations.sourcedb.client import SqlAlchemySourceDb
from app.integrations.sourcedb.types import (
    SourceDbBatch,
    SourceDbConfig,
    SourceDbConnector,
    SourceDbError,
)

__all__ = [
    "SourceDbBatch",
    "SourceDbConfig",
    "SourceDbConnector",
    "SourceDbError",
    "SqlAlchemySourceDb",
]
