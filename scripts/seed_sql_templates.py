"""Phase 3.2.8 — `docs/sql_templates/*.sql` + `meta.yaml` 을 SQL Studio 에 적재.

각 템플릿은 `wf.sql_query` (1행) + `wf.sql_query_version` (DRAFT v1, 1행) 으로 시드.
시스템 사용자(login_id 'system') 가 owner. owner_user_id 는 ctl.app_user 에서 lookup.

멱등성: 같은 `name` 이 이미 있으면 skip — 운영자가 수정한 본문을 덮어쓰지 않게.
description 은 "[<카테고리>] <설명>" 형식으로 prefix 가 붙는다.

사용:
    cd backend
    .venv/Scripts/python ../scripts/seed_sql_templates.py
    .venv/Scripts/python ../scripts/seed_sql_templates.py --owner_login admin
    .venv/Scripts/python ../scripts/seed_sql_templates.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypedDict

import yaml
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.integrations.sqlglot_validator import SqlValidationError, validate
from app.models.wf import SqlQuery, SqlQueryVersion

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "docs" / "sql_templates"


class TemplateSpec(TypedDict, total=False):
    file: str
    name: str
    category: str
    description: str
    allowed_schemas: list[str]


def load_templates(directory: Path) -> list[TemplateSpec]:
    """meta.yaml 의 templates 목록 + 같은 디렉토리의 .sql 파일 검증.

    반환된 spec 에는 sql_text 가 인라인으로 채워진다.
    """
    meta_path = directory / "meta.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"{meta_path} not found")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or "templates" not in meta:
        raise ValueError(f"{meta_path}: must be a mapping with `templates`")
    out: list[TemplateSpec] = []
    for raw in meta["templates"]:
        if not isinstance(raw, dict):
            raise ValueError(f"{meta_path}: each template must be a mapping")
        spec = dict(raw)
        for key in ("file", "name", "category", "description"):
            if not spec.get(key):
                raise ValueError(f"{meta_path}: template missing required key '{key}'")
        sql_path = directory / str(spec["file"])
        if not sql_path.exists():
            raise FileNotFoundError(f"{sql_path} (referenced from meta.yaml) not found")
        spec["sql_text"] = sql_path.read_text(encoding="utf-8").strip()
        out.append(spec)  # type: ignore[arg-type]
    return out


def _lookup_system_user_id(session: Session, login_id: str) -> int:
    row = session.execute(
        text("SELECT user_id FROM ctl.app_user WHERE login_id = :lid LIMIT 1"),
        {"lid": login_id},
    ).first()
    if row is None:
        raise ValueError(
            f"owner login_id '{login_id}' not found in ctl.app_user. "
            "scripts/seed_admin.py 를 먼저 실행해 주세요."
        )
    return int(row[0])


def _seed_one(
    session: Session, spec: TemplateSpec, *, owner_user_id: int, dry_run: bool
) -> tuple[str, int | None]:
    """반환: (status, sql_query_id|None)."""
    name = str(spec["name"])
    sql_text = str(spec["sql_text"])
    # 1차 정적 검증 — sqlglot 로 통과해야 시드.
    try:
        validate(sql_text)
    except SqlValidationError as exc:
        return f"REJECTED({exc})", None

    existing = session.execute(
        select(SqlQuery).where(SqlQuery.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        return "SKIPPED", existing.sql_query_id

    if dry_run:
        return "WOULD_CREATE", None

    description = f"[{spec['category']}] {spec['description']}"
    query = SqlQuery(name=name, description=description, owner_user_id=owner_user_id)
    session.add(query)
    session.flush()

    version = SqlQueryVersion(
        sql_query_id=query.sql_query_id,
        version_no=1,
        sql_text=sql_text,
        referenced_tables=sorted(_extract_refs(sql_text)),
        status="DRAFT",
    )
    session.add(version)
    session.flush()

    query.current_version_id = version.sql_query_version_id
    session.flush()
    return "CREATED", query.sql_query_id


def _extract_refs(sql_text: str) -> set[str]:
    """validate 가 던진 referenced_tables 를 그대로 사용 (이미 통과한 SQL)."""
    _, refs = validate(sql_text)
    return refs


def idempotent_load_templates(
    session: Session,
    specs: Iterable[TemplateSpec],
    *,
    owner_user_id: int,
    dry_run: bool = False,
) -> list[tuple[str, str, int | None]]:
    """`spec` 모음을 받아 한 트랜잭션 안에서 모두 시드.

    반환: [(template_name, status, sql_query_id|None), ...]
    """
    results: list[tuple[str, str, int | None]] = []
    for spec in specs:
        status, qid = _seed_one(session, spec, owner_user_id=owner_user_id, dry_run=dry_run)
        results.append((str(spec["name"]), status, qid))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed wf.sql_query from docs/sql_templates.")
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=DEFAULT_DIR,
        help="템플릿 위치 (기본 docs/sql_templates)",
    )
    parser.add_argument(
        "--owner_login",
        default="admin",
        help="owner_user_id 를 lookup 할 ctl.app_user.login_id (기본 admin)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.templates_dir.exists():
        print(f"[seed_sql_templates] directory not found: {args.templates_dir}", file=sys.stderr)
        return 2

    specs: Any = load_templates(args.templates_dir)
    sm = get_sync_sessionmaker()
    try:
        with sm() as session:
            owner_id = _lookup_system_user_id(session, args.owner_login)
            results = idempotent_load_templates(
                session, specs, owner_user_id=owner_id, dry_run=args.dry_run
            )
            if not args.dry_run:
                session.commit()
    finally:
        dispose_sync_engine()

    for name, status, qid in results:
        ident = f"sql_query_id={qid}" if qid is not None else "—"
        print(f"[seed_sql_templates] {status:>20} {name:<40} {ident}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
