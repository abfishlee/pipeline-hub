"""Phase 1 부트스트랩 — 최초 ADMIN 사용자 생성.

POST /v1/users 는 ADMIN 가드가 걸려 있어, 첫 사용자는 별도 채널로 만들어야 한다.
이 스크립트는 backend 의 hash_password 와 동일 알고리즘(argon2id)으로 password_hash 를
계산해 ctl.app_user / ctl.app_user_role 에 idempotent 하게 INSERT 한다.

사용:
    cd backend
    uv run python ../scripts/seed_admin.py            # 기본 admin / admin
    uv run python ../scripts/seed_admin.py --login_id ops --password '<강력비밀번호>'

운영 환경에서는 1회 실행 후 즉시 비밀번호 변경.
"""

from __future__ import annotations

import argparse
import sys

# backend.app 임포트 — 이 스크립트는 cwd=backend 에서 `python ../scripts/seed_admin.py` 로 실행.
from app.config import get_settings
from app.core.security import hash_password


def _sync_database_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the first ADMIN user.")
    parser.add_argument("--login_id", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--display_name", default="Bootstrap Admin")
    parser.add_argument("--email", default="admin@example.local")
    parser.add_argument(
        "--role",
        default="ADMIN",
        help="role_code in ctl.role — default ADMIN",
    )
    args = parser.parse_args()

    if args.password in {"admin", "password", "1234"}:
        print(
            "[seed_admin] WARNING: weak default password — change immediately after first login.",
            file=sys.stderr,
        )

    settings = get_settings()
    sync_url = _sync_database_url(settings.database_url)

    import psycopg

    pw_hash = hash_password(args.password)

    with psycopg.connect(sync_url, autocommit=True) as conn, conn.cursor() as cur:
        # 1. ctl.app_user UPSERT.
        cur.execute(
            """
            INSERT INTO ctl.app_user (login_id, display_name, email, password_hash, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (login_id) DO UPDATE
               SET display_name  = EXCLUDED.display_name,
                   email         = EXCLUDED.email,
                   password_hash = EXCLUDED.password_hash,
                   is_active     = TRUE
            RETURNING user_id
            """,
            (args.login_id, args.display_name, args.email, pw_hash),
        )
        row = cur.fetchone()
        assert row is not None
        user_id = row[0]

        # 2. role_id 조회 (Phase 4+ — ctl.role + ctl.user_role 분리).
        cur.execute(
            "SELECT role_id FROM ctl.role WHERE role_code = %s",
            (args.role,),
        )
        role_row = cur.fetchone()
        if role_row is None:
            print(
                f"[seed_admin] ERROR: role '{args.role}' not found in ctl.role. "
                "Run alembic upgrade head first.",
                file=sys.stderr,
            )
            return 2
        role_id = role_row[0]

        # 3. user_role 매핑 (idempotent).
        cur.execute(
            """
            INSERT INTO ctl.user_role (user_id, role_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (user_id, role_id),
        )

    print(
        f"[seed_admin] OK: user_id={user_id} login_id={args.login_id} role={args.role}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
