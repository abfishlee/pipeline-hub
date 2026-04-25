"""Phase 3.2.8 — `docs/pipelines/*.yaml` 을 워크플로 DB 에 적재.

설계:
  - 멱등성: 같은 `name` (workflow_definition.name) 이 이미 있으면 그래프는 그대로
    두고 (overwrite 안 함) skip — 운영자가 UI 에서 수정한 것을 덮어쓰지 않게.
  - schedule_cron 만은 같은 name 의 PUBLISHED 가 있으면 동기화 (운영자가 새 cron 으로
    바꿨으면 그쪽 우선). 본 시드는 처음 진입 시점의 기본값만 채운다.
  - YAML 1개 = workflow_definition 1행 + N개의 node + M개의 edge.
  - 출력: 각 파일별 status (CREATED / SKIPPED / NOT_PUBLISHED_YET) 1줄씩.

사용:
    cd backend
    .venv/Scripts/python ../scripts/seed_default_pipelines.py
    .venv/Scripts/python ../scripts/seed_default_pipelines.py --dry-run
    .venv/Scripts/python ../scripts/seed_default_pipelines.py --pipelines-dir ../docs/pipelines
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypedDict

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.wf import EdgeDefinition, NodeDefinition, WorkflowDefinition

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "docs" / "pipelines"


class PipelineSpec(TypedDict, total=False):
    name: str
    description: str
    schedule_cron: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def load_yaml_files(directory: Path) -> list[tuple[Path, PipelineSpec]]:
    """디렉토리의 모든 .yaml/.yml 을 로드. 파일명 기준 정렬해 결정적 순서 보장."""
    files: list[Path] = sorted(
        [p for p in directory.iterdir() if p.suffix in (".yaml", ".yml") and p.is_file()]
    )
    out: list[tuple[Path, PipelineSpec]] = []
    for p in files:
        spec = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or "name" not in spec or "nodes" not in spec:
            raise ValueError(f"{p}: must be a mapping with at least `name` and `nodes`")
        out.append((p, spec))
    return out


def _validate_spec(spec: PipelineSpec) -> None:
    """YAML 본문이 본 시드가 처리 가능한 형태인지 검증.

    - node_key 유일.
    - edge.from/to 가 nodes 안에 존재.
    - 알려지지 않은 node_type 거부 (DB CHECK 와 같은 화이트리스트).
    """
    nodes = spec.get("nodes") or []
    if not nodes:
        raise ValueError(f"pipeline {spec.get('name')!r} has no nodes")
    valid_types = {
        "NOOP",
        "SOURCE_API",
        "SQL_TRANSFORM",
        "DEDUP",
        "DQ_CHECK",
        "LOAD_MASTER",
        "NOTIFY",
    }
    keys: set[str] = set()
    for n in nodes:
        nk = str(n.get("node_key") or "")
        if not nk:
            raise ValueError(f"pipeline {spec.get('name')!r}: node missing node_key")
        if nk in keys:
            raise ValueError(f"pipeline {spec.get('name')!r}: duplicate node_key {nk!r}")
        keys.add(nk)
        nt = str(n.get("node_type") or "")
        if nt not in valid_types:
            raise ValueError(
                f"pipeline {spec.get('name')!r}: unknown node_type {nt!r} for node {nk!r}"
            )
    for e in spec.get("edges") or []:
        src = str(e.get("from_node_key") or "")
        tgt = str(e.get("to_node_key") or "")
        if src not in keys or tgt not in keys:
            raise ValueError(
                f"pipeline {spec.get('name')!r}: edge references unknown node "
                f"({src!r} → {tgt!r})"
            )


def _seed_one(
    session: Session, spec: PipelineSpec, *, dry_run: bool
) -> tuple[str, int | None]:
    """반환: (status, workflow_id|None)."""
    _validate_spec(spec)
    name = spec["name"]
    existing = session.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        return "SKIPPED", existing.workflow_id

    if dry_run:
        return "WOULD_CREATE", None

    wf = WorkflowDefinition(
        name=name,
        version=1,
        description=spec.get("description"),
        status="DRAFT",
        schedule_cron=spec.get("schedule_cron"),
        # schedule_enabled 은 항상 False 로 시작 — 운영자가 UI 에서 활성화.
    )
    session.add(wf)
    session.flush()  # workflow_id 채움.

    by_key: dict[str, NodeDefinition] = {}
    for n in spec.get("nodes") or []:
        pos = n.get("position") or {}
        nd = NodeDefinition(
            workflow_id=wf.workflow_id,
            node_key=str(n["node_key"]),
            node_type=str(n["node_type"]),
            config_json=dict(n.get("config_json") or {}),
            position_x=int(pos.get("x") or n.get("position_x") or 0),
            position_y=int(pos.get("y") or n.get("position_y") or 0),
        )
        session.add(nd)
        by_key[nd.node_key] = nd
    session.flush()

    for e in spec.get("edges") or []:
        session.add(
            EdgeDefinition(
                workflow_id=wf.workflow_id,
                from_node_id=by_key[str(e["from_node_key"])].node_id,
                to_node_id=by_key[str(e["to_node_key"])].node_id,
                condition_expr=e.get("condition_expr"),
            )
        )
    session.flush()
    return "CREATED", wf.workflow_id


def idempotent_load_yaml(
    session: Session, specs: Iterable[tuple[Path, Mapping[str, Any]]], *, dry_run: bool = False
) -> list[tuple[Path, str, int | None]]:
    """`(path, spec)` 페어 모음을 받아 한 트랜잭션 안에서 모두 시드.

    호출자(스크립트/테스트) 가 commit 책임.
    """
    results: list[tuple[Path, str, int | None]] = []
    for path, spec in specs:
        status, wf_id = _seed_one(session, dict(spec), dry_run=dry_run)
        results.append((path, status, wf_id))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed wf.workflow_definition from YAML files.")
    parser.add_argument(
        "--pipelines-dir",
        type=Path,
        default=DEFAULT_DIR,
        help="YAML 위치 (기본 docs/pipelines)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 변경 없이 어떤 워크플로가 새로 생성될지만 출력.",
    )
    args = parser.parse_args()

    if not args.pipelines_dir.exists():
        print(f"[seed_pipelines] directory not found: {args.pipelines_dir}", file=sys.stderr)
        return 2

    specs = load_yaml_files(args.pipelines_dir)
    if not specs:
        print(f"[seed_pipelines] no YAML files in {args.pipelines_dir}")
        return 0

    sm = get_sync_sessionmaker()
    try:
        with sm() as session:
            results = idempotent_load_yaml(session, specs, dry_run=args.dry_run)
            if not args.dry_run:
                session.commit()
    finally:
        dispose_sync_engine()

    for path, status, wf_id in results:
        wid = f"workflow_id={wf_id}" if wf_id is not None else "—"
        print(f"[seed_pipelines] {status:>13} {path.name:<32} {wid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
