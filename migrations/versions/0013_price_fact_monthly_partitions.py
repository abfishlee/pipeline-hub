"""mart.price_fact 월별 파티션 (2026-05 ~ 2026-12) 추가.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-25 20:00:00+00:00

Phase 2.2.6 가격 팩트 자동 반영. 2026-04 파티션은 0006 에서 이미 생성. 운영팀 9월
합류 + Phase 2~3 진행 중 적재 가능 범위로 12월까지 8개월치 파티션을 사전 확보.

운영(Phase 4) 에서는 Airflow DAG `system_monthly_partition` (Phase 2.2.3 후속) 이
매월 1일 03:00 다음 달 파티션을 자동 생성. 이 migration 은 그 DAG 가 도입되기 전의
브릿지 — DAG 가 안정화되면 본 migration 의 책임은 종료.

부모 테이블의 BRIN(observed_at) / (product_id, observed_at DESC) /
(seller_id, observed_at DESC) 인덱스는 PostgreSQL 11+ 의 declarative partitioning
규칙으로 자동 상속되므로 별도 CREATE INDEX 불필요.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (year, month) 쌍. 다음 달은 자동 계산.
_MONTHS: tuple[tuple[int, int], ...] = (
    (2026, 5),
    (2026, 6),
    (2026, 7),
    (2026, 8),
    (2026, 9),
    (2026, 10),
    (2026, 11),
    (2026, 12),
)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def upgrade() -> None:
    for year, month in _MONTHS:
        ny, nm = _next_month(year, month)
        partition = f"price_fact_{year}_{month:02d}"
        from_d = f"{year}-{month:02d}-01"
        to_d = f"{ny}-{nm:02d}-01"
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS mart.{partition}
                PARTITION OF mart.price_fact
                FOR VALUES FROM ('{from_d}') TO ('{to_d}');
            """
        )


def downgrade() -> None:
    for year, month in _MONTHS:
        partition = f"price_fact_{year}_{month:02d}"
        op.execute(f"DROP TABLE IF EXISTS mart.{partition} CASCADE;")
