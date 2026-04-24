"""SQLAlchemy DeclarativeBase + 공통 타입 alias.

모든 ORM 모델은 `Base` 를 상속한다. Phase 1.2.3 에서 스키마별 모델을 추가하면서
이 파일은 거의 수정 없이 안정 유지.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Naming convention — Alembic autogenerate 시 일관된 제약조건 이름 생성.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """프로젝트 ORM 루트. 스키마/네이밍 정책을 단일화."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# 공통 타입 alias — `bigserial` PK / FK 단순화.
BigIntPK = Annotated[
    int,
    mapped_column(BigInteger, primary_key=True, autoincrement=True),
]
BigIntFK = Annotated[int, mapped_column(BigInteger)]


# 시간 컬럼 helpers — 모델에서 직접 default 함수 작성하지 않도록.
def utcnow() -> datetime:
    """Alembic / 모델 default 용. tz-aware UTC."""
    from datetime import UTC

    return datetime.now(UTC)


__all__ = ["NAMING_CONVENTION", "Base", "BigIntFK", "BigIntPK", "utcnow"]
