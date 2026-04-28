"""Clean all non-user data for feature-by-feature validation.

남기는 것:
  - ctl.app_user / ctl.role / ctl.user_role — 로그인 계정과 전역 역할
  - public.alembic_version                  — 마이그레이션 상태

지우는 것:
  - 위 보호 테이블을 제외한 모든 업무/운영/테스트 데이터
  - API Key, 도메인 권한, source, mapping, workflow, run, raw, audit, mart,
    service mart, mock/demo 잔재 포함

실행:
  cd backend
  PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe ../scripts/phase8_6_wipe_all.py [--yes]
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable

if os.name == "nt":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from app.db.sync_session import get_sync_sessionmaker

PROTECTED_TABLES = frozenset(
    {
        ("ctl", "app_user"),
        ("ctl", "role"),
        ("ctl", "user_role"),
        ("public", "alembic_version"),
    }
)


def _wipe_targets(session: object) -> list[tuple[str, str, str]]:
    rows = session.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT
              n.nspname AS schema_name,
              c.relname AS table_name,
              format('%I.%I', n.nspname, c.relname) AS qualified_name
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
            ORDER BY
              CASE WHEN c.relkind = 'r' THEN 0 ELSE 1 END,
              n.nspname,
              c.relname
            """
        )
    ).all()
    targets: list[tuple[str, str, str]] = []
    for schema, table, qualified in rows:
        if (str(schema), str(table)) in PROTECTED_TABLES:
            continue
        targets.append((str(schema), str(table), str(qualified)))
    return targets


def main(args: Iterable[str]) -> None:
    auto_yes = "--yes" in args or os.getenv("WIPE_AUTO_YES") == "1"

    sm = get_sync_sessionmaker()
    with sm() as session:
        print("== Data Wipe — 사용자/역할 제외 전체 초기화 시작 ==")

        targets = _wipe_targets(session)
        if targets:
            qualified_targets = ", ".join(t[2] for t in targets)
            session.execute(text(f"TRUNCATE {qualified_targets} RESTART IDENTITY CASCADE"))

        wiped = [f"{schema}.{table}" for schema, table, _ in targets]

        # wf.tmp_run_* 임시 sandbox 테이블 정리 (이전 run 잔재)
        tmp_tables = session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='wf' AND tablename LIKE 'tmp_run_%'"
            )
        ).all()
        for r in tmp_tables:
            session.execute(text(f"DROP TABLE IF EXISTS wf.{r[0]} CASCADE"))
            wiped.append(f"wf.{r[0]} (DROPPED)")

        if not auto_yes:
            protected = ", ".join(f"{s}.{t}" for s, t in sorted(PROTECTED_TABLES))
            print(f"\n  truncated/dropped: {len(wiped)} 객체")
            print(f"  protected: {protected}")
            ans = input("commit 하시겠습니까? (y/N): ").strip().lower()
            if ans != "y":
                session.rollback()
                print("ROLLBACK — 데이터 그대로.")
                return

        session.commit()
        print(f"\n✓ wipe 완료 — {len(wiped)} 객체 정리.")
        print("  남은 것: ctl.app_user / ctl.role / ctl.user_role / public.alembic_version")
        print("  다음 단계: 기능 단위 실증 데이터를 화면에서 새로 생성")


if __name__ == "__main__":
    main(sys.argv[1:])
