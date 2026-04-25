"""seed ctl.role with system-defined RBAC roles

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-25 12:30:00+00:00

docs/03_DATA_MODEL.md 3.11 정합. 5개 시스템 역할.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES: tuple[tuple[str, str, str], ...] = (
    ("ADMIN", "관리자", "전 권한"),
    ("OPERATOR", "운영자", "수집/파이프라인 운영"),
    ("REVIEWER", "검수자", "크라우드 검수 전용"),
    ("APPROVER", "승인자", "SQL/Mart 반영 승인"),
    ("VIEWER", "조회자", "읽기 전용"),
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO ctl.role (role_code, role_name, description) VALUES
            ('ADMIN',    '관리자',  '전 권한'),
            ('OPERATOR', '운영자',  '수집/파이프라인 운영'),
            ('REVIEWER', '검수자',  '크라우드 검수 전용'),
            ('APPROVER', '승인자',  'SQL/Mart 반영 승인'),
            ('VIEWER',   '조회자',  '읽기 전용')
        ON CONFLICT (role_code) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ctl.role WHERE role_code IN "
        "('ADMIN','OPERATOR','REVIEWER','APPROVER','VIEWER');"
    )
