"""user × domain 권한 매트릭스 (Phase 5.2.4 STEP 7 Q1).

전역 ADMIN 은 모든 도메인 ADMIN 권한 자동 보유.
도메인 단위 역할은 ctl.user_domain_role 에서 조회.

위계: VIEWER < EDITOR < APPROVER < ADMIN.
"""

from __future__ import annotations

from app.domain.permissions.matrix import (
    DomainRole,
    DomainRoleError,
    grant_domain_role,
    has_domain_role,
    list_user_domain_roles,
    require_domain_role,
    revoke_domain_role,
)

__all__ = [
    "DomainRole",
    "DomainRoleError",
    "grant_domain_role",
    "has_domain_role",
    "list_user_domain_roles",
    "require_domain_role",
    "revoke_domain_role",
]
