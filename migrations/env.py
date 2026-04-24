"""Alembic env — async SQLAlchemy + app.config 에서 URL 주입.

실행 방법: `cd backend && alembic upgrade head` (Makefile `make db-migrate`).
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Windows 로컬에서 psycopg async 호환 (운영 Linux 무영향).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# app/* 모듈 import 가능하도록 (alembic.ini 의 prepend_sys_path 와 함께).
from app.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

# Alembic Config 객체 (alembic.ini 내용).
config = context.config

# 로깅 설정 적용.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 런타임에 DB URL 주입 (alembic.ini 의 placeholder 덮어씀).
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

# autogenerate / 검증 시 비교 대상 metadata.
target_metadata = Base.metadata

# 검증 옵션 — schema 별 분리, 인덱스 비교 활성화.
INCLUDE_SCHEMAS = True


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=INCLUDE_SCHEMAS,
        compare_type=True,
        compare_server_default=True,
        # 모든 스키마 마이그레이션 통과시키되, 시스템 schema 는 제외.
        include_object=lambda obj, name, type_, reflected, compare_to: not (
            type_ == "schema" and name in ("public", "information_schema")
        ),
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Online 모드 — async engine 으로 실행."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_offline() -> None:
    """Offline 모드 — 실행하지 않고 SQL 만 출력 (`alembic upgrade head --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=INCLUDE_SCHEMAS,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
