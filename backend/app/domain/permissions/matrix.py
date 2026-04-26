"""user × domain 권한 매트릭스 헬퍼 (Phase 5.2.4 STEP 7 Q1).

위계 (높을수록 권한 큼):
    VIEWER (1) < EDITOR (2) < APPROVER (3) < ADMIN (4)

상위 역할은 하위 역할 권한 포함:
    APPROVER 는 EDITOR / VIEWER 도 가능.

전역 ADMIN(ctl.role.role_code='ADMIN') 은 *모든 도메인* 의 DOMAIN_ADMIN 자동 보유.
별도 user_domain_role row 없어도 통과.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from sqlalchemy import text
from sqlalchemy.orm import Session


class DomainRole(StrEnum):
    VIEWER = "VIEWER"
    EDITOR = "EDITOR"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


_ROLE_RANK: Final[dict[str, int]] = {
    DomainRole.VIEWER: 1,
    DomainRole.EDITOR: 2,
    DomainRole.APPROVER: 3,
    DomainRole.ADMIN: 4,
}


class DomainRoleError(PermissionError):
    """권한 부족 — caller 가 403 으로 변환."""


def _is_global_admin(session: Session, *, user_id: int) -> bool:
    """ctl.user_role 에 ADMIN role 부여 여부."""
    row = session.execute(
        text(
            "SELECT 1 FROM ctl.user_role ur "
            "JOIN ctl.role r ON r.role_id = ur.role_id "
            "WHERE ur.user_id = :uid AND r.role_code = 'ADMIN' LIMIT 1"
        ),
        {"uid": user_id},
    ).first()
    return row is not None


def _user_domain_role(
    session: Session, *, user_id: int, domain_code: str
) -> str | None:
    row = session.execute(
        text(
            "SELECT role FROM ctl.user_domain_role "
            "WHERE user_id = :uid AND domain_code = :dom"
        ),
        {"uid": user_id, "dom": domain_code},
    ).first()
    return str(row.role) if row else None


def has_domain_role(
    session: Session,
    *,
    user_id: int,
    domain_code: str,
    required: DomainRole,
) -> bool:
    """user 가 domain 에 대해 *required 이상* 권한을 가지는지 체크."""
    if _is_global_admin(session, user_id=user_id):
        return True
    cur = _user_domain_role(session, user_id=user_id, domain_code=domain_code)
    if cur is None:
        return False
    return _ROLE_RANK[cur] >= _ROLE_RANK[required]


def require_domain_role(
    session: Session,
    *,
    user_id: int,
    domain_code: str,
    required: DomainRole,
) -> None:
    """has_domain_role 의 throwing 버전. 권한 없으면 DomainRoleError."""
    if not has_domain_role(
        session, user_id=user_id, domain_code=domain_code, required=required
    ):
        raise DomainRoleError(
            f"user {user_id} lacks {required} on domain {domain_code!r}"
        )


def grant_domain_role(
    session: Session,
    *,
    user_id: int,
    domain_code: str,
    role: DomainRole,
    granted_by: int | None = None,
) -> None:
    """role 부여 (UPSERT)."""
    session.execute(
        text(
            "INSERT INTO ctl.user_domain_role "
            "(user_id, domain_code, role, granted_by) "
            "VALUES (:uid, :dom, :role, :by) "
            "ON CONFLICT (user_id, domain_code) DO UPDATE SET "
            "  role = EXCLUDED.role, granted_by = EXCLUDED.granted_by, "
            "  granted_at = now()"
        ),
        {"uid": user_id, "dom": domain_code, "role": role.value, "by": granted_by},
    )


def revoke_domain_role(
    session: Session, *, user_id: int, domain_code: str
) -> None:
    session.execute(
        text(
            "DELETE FROM ctl.user_domain_role "
            "WHERE user_id = :uid AND domain_code = :dom"
        ),
        {"uid": user_id, "dom": domain_code},
    )


def list_user_domain_roles(
    session: Session, *, user_id: int
) -> list[tuple[str, str]]:
    """user_id 의 (domain_code, role) 목록. 전역 ADMIN 은 (*, 'ADMIN') 1행 추가."""
    rows = session.execute(
        text(
            "SELECT domain_code, role FROM ctl.user_domain_role "
            "WHERE user_id = :uid ORDER BY domain_code"
        ),
        {"uid": user_id},
    ).all()
    out: list[tuple[str, str]] = [(str(r.domain_code), str(r.role)) for r in rows]
    if _is_global_admin(session, user_id=user_id):
        out.insert(0, ("*", DomainRole.ADMIN.value))
    return out


__all__ = [
    "DomainRole",
    "DomainRoleError",
    "grant_domain_role",
    "has_domain_role",
    "list_user_domain_roles",
    "require_domain_role",
    "revoke_domain_role",
]
