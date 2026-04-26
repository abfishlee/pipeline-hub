"""Phase 4.0.5 — RBAC 확장: PUBLIC_READER / MART_WRITER / SANDBOX_READER 추가.

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-26 12:00:00+00:00

Phase 3 종료 시점의 5 role (ADMIN/APPROVER/OPERATOR/REVIEWER/VIEWER) 위에 Phase 4 의
세 가지 분리된 역할 추가:

  - PUBLIC_READER  — 외부 API 키 전용. RLS 적용된 mart 조회만 가능 (Phase 4.2.4 RLS +
                     4.2.5 Public API 와 결합).
  - MART_WRITER    — LOAD_MASTER 노드 + APPROVED SQL 자산이 mart 에 직접 INSERT/UPDATE
                     하는 권한. 현재는 ADMIN/APPROVER 가 대신 가지지만 Phase 4 에서
                     분리 (단순 운영자가 mart write 권한 없이 워크플로 작성 가능).
  - SANDBOX_READER — SQL Studio sandbox 의 read-only role. Phase 4.0 게이트의 NCP
                     replica 도입 후 sandbox 가 그쪽으로 라우팅되면 본 role 만 replica
                     접근 (ADR-0008 의 마이그 트리거와 연결).

마이그레이션 정책: 기존 사용자에게 자동 부여하지 않음 — ADMIN 이 명시적으로 grant.
ADR-0010 참조.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PHASE4_ROLES: tuple[tuple[str, str, str], ...] = (
    ("PUBLIC_READER", "외부 API 키", "Public /public/v1/* 조회 전용 (Phase 4.2.5)"),
    ("MART_WRITER", "Mart 적재", "LOAD_MASTER 노드 + APPROVED SQL 의 mart write"),
    ("SANDBOX_READER", "Sandbox 조회", "SQL Studio sandbox read-only (replica 라우팅 후)"),
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO ctl.role (role_code, role_name, description) VALUES
            ('PUBLIC_READER',  '외부 API 키',     'Public /public/v1/* 조회 전용 (Phase 4.2.5)'),
            ('MART_WRITER',    'Mart 적재',       'LOAD_MASTER 노드 + APPROVED SQL 의 mart write'),
            ('SANDBOX_READER', 'Sandbox 조회',    'SQL Studio sandbox read-only (replica 라우팅 후)')
        ON CONFLICT (role_code) DO NOTHING;
        """
    )


def downgrade() -> None:
    # 기존 user_role 매핑이 있으면 FK 충돌 — 해당 role 의 매핑부터 정리.
    op.execute(
        """
        DELETE FROM ctl.user_role
         WHERE role_id IN (
            SELECT role_id FROM ctl.role
             WHERE role_code IN ('PUBLIC_READER','MART_WRITER','SANDBOX_READER')
         );
        """
    )
    op.execute(
        """
        DELETE FROM ctl.role
         WHERE role_code IN ('PUBLIC_READER','MART_WRITER','SANDBOX_READER');
        """
    )
