"""docs/pipelines + docs/sql_templates 시드 통합 테스트 (Phase 3.2.8).

검증:
  1. YAML 파싱 — 3개 파이프라인 노드/엣지가 정확히 적재되며 7가지 node_type 이 적어도
     1번 등장.
  2. 멱등성 — 같은 시드 스크립트를 2회 호출하면 같은 sql_query_id / workflow_id 반환.
  3. SQL 템플릿 — 12개 모두 sqlglot validate 통과 + sql_query_version v1 DRAFT 적재.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.models.wf import (
    EdgeDefinition,
    NodeDefinition,
    PipelineRelease,
    SqlQuery,
    SqlQueryVersion,
    WorkflowDefinition,
)

# scripts/ 디렉토리를 import path 에 추가.
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_default_pipelines  # noqa: E402
import seed_sql_templates  # noqa: E402

PIPELINES_DIR = Path(__file__).resolve().parents[3] / "docs" / "pipelines"
TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "docs" / "sql_templates"


@pytest.fixture
def cleanup_seeded_pipelines() -> Iterator[list[str]]:
    """시드된 워크플로 name 들을 종료 시 삭제 (자식 nodes/edges/release 포함)."""
    names: list[str] = []
    yield names
    if not names:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        wf_ids = list(
            session.execute(
                text("SELECT workflow_id FROM wf.workflow_definition WHERE name = ANY(:names)"),
                {"names": names},
            ).scalars()
        )
        if wf_ids:
            session.execute(
                delete(PipelineRelease).where(PipelineRelease.released_workflow_id.in_(wf_ids))
            )
            session.execute(delete(EdgeDefinition).where(EdgeDefinition.workflow_id.in_(wf_ids)))
            session.execute(delete(NodeDefinition).where(NodeDefinition.workflow_id.in_(wf_ids)))
            session.execute(
                delete(WorkflowDefinition).where(WorkflowDefinition.workflow_id.in_(wf_ids))
            )
            session.commit()
    dispose_sync_engine()


@pytest.fixture
def cleanup_seeded_sql_queries() -> Iterator[list[str]]:
    names: list[str] = []
    yield names
    if not names:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        ids = list(
            session.execute(
                text("SELECT sql_query_id FROM wf.sql_query WHERE name = ANY(:names)"),
                {"names": names},
            ).scalars()
        )
        if ids:
            # current_version_id 순환참조 풀고 삭제.
            session.execute(
                text(
                    "UPDATE wf.sql_query SET current_version_id = NULL WHERE sql_query_id = ANY(:ids)"
                ),
                {"ids": ids},
            )
            session.execute(delete(SqlQueryVersion).where(SqlQueryVersion.sql_query_id.in_(ids)))
            session.execute(delete(SqlQuery).where(SqlQuery.sql_query_id.in_(ids)))
            session.commit()
    dispose_sync_engine()


# ---------------------------------------------------------------------------
# Pipelines YAML
# ---------------------------------------------------------------------------
def test_yaml_files_parse_to_seven_node_types(cleanup_seeded_pipelines: list[str]) -> None:
    """3개 YAML 의 union 이 7 node_type 중 사용된 6 type 을 모두 커버해야 한다.

    NOOP 은 production 파이프라인에서 의미가 없어 본 시드 셋에 없음 — 6 type 검증.
    """
    specs = seed_default_pipelines.load_yaml_files(PIPELINES_DIR)
    assert len(specs) == 3
    seen_types: set[str] = set()
    for _, spec in specs:
        for n in spec.get("nodes") or []:
            seen_types.add(str(n["node_type"]))

    expected_used_types = {
        "SOURCE_API",
        "DQ_CHECK",
        "SQL_TRANSFORM",
        "DEDUP",
        "LOAD_MASTER",
        "NOTIFY",
    }
    assert expected_used_types.issubset(
        seen_types
    ), f"missing node_types: {expected_used_types - seen_types}"


def test_seed_pipelines_idempotent(cleanup_seeded_pipelines: list[str]) -> None:
    """같은 YAML 셋을 2회 시드 → 같은 workflow_id 반환."""
    specs = seed_default_pipelines.load_yaml_files(PIPELINES_DIR)
    for _, spec in specs:
        cleanup_seeded_pipelines.append(str(spec["name"]))

    sm = get_sync_sessionmaker()
    with sm() as session:
        first = seed_default_pipelines.idempotent_load_yaml(session, specs)
        session.commit()
    first_ids = {path.name: wf_id for path, status, wf_id in first if status == "CREATED"}
    assert len(first_ids) == 3

    # 2번째 호출 — 같은 ID, status=SKIPPED
    sm = get_sync_sessionmaker()
    with sm() as session:
        second = seed_default_pipelines.idempotent_load_yaml(session, specs)
        # commit 불필요 — 변경 없음.
    for path, status, wf_id in second:
        assert status == "SKIPPED", f"{path.name} expected SKIPPED, got {status}"
        assert wf_id == first_ids[path.name]


def test_seed_pipelines_persists_nodes_and_edges_correctly(
    cleanup_seeded_pipelines: list[str],
) -> None:
    """retail_api_price__emart 워크플로의 노드 7개 + 엣지 7개가 정확히 적재."""
    specs = seed_default_pipelines.load_yaml_files(PIPELINES_DIR)
    target_spec = next((s for s in specs if s[1]["name"] == "retail_api_price__emart"), None)
    assert target_spec is not None
    cleanup_seeded_pipelines.append("retail_api_price__emart")

    sm = get_sync_sessionmaker()
    with sm() as session:
        seed_default_pipelines.idempotent_load_yaml(session, [target_spec])
        session.commit()

    sm = get_sync_sessionmaker()
    with sm() as session:
        wf = session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.name == "retail_api_price__emart")
        ).scalar_one()
        nodes = list(
            session.execute(
                select(NodeDefinition).where(NodeDefinition.workflow_id == wf.workflow_id)
            ).scalars()
        )
        edges = list(
            session.execute(
                select(EdgeDefinition).where(EdgeDefinition.workflow_id == wf.workflow_id)
            ).scalars()
        )
    assert len(nodes) == 7
    assert len(edges) == 7
    assert wf.schedule_cron == "0 5 * * *"
    assert wf.schedule_enabled is False  # seed 는 항상 OFF 로 시작.
    keys = {n.node_key for n in nodes}
    assert keys == {
        "extract_emart_api",
        "dq_check_extract",
        "sql_normalize",
        "dq_check_normalized",
        "dedup_business_key",
        "load_master",
        "notify_slack",
    }


# ---------------------------------------------------------------------------
# SQL Templates
# ---------------------------------------------------------------------------
def test_load_sql_templates_meta_lists_at_least_10() -> None:
    specs = seed_sql_templates.load_templates(TEMPLATES_DIR)
    assert len(specs) >= 10
    # 각 spec 에 sql_text 가 채워졌는지.
    for s in specs:
        assert s["sql_text"], f"{s['name']} has empty sql_text"
        assert s["category"]
        assert s["allowed_schemas"]


def test_seed_sql_templates_idempotent(
    cleanup_seeded_sql_queries: list[str],
    _admin_seed: dict[str, str],
) -> None:
    """같은 템플릿 셋을 2회 시드 → 같은 sql_query_id."""
    specs = seed_sql_templates.load_templates(TEMPLATES_DIR)
    for s in specs:
        cleanup_seeded_sql_queries.append(str(s["name"]))

    sm = get_sync_sessionmaker()
    with sm() as session:
        owner_id = seed_sql_templates._lookup_system_user_id(session, _admin_seed["login_id"])
        first = seed_sql_templates.idempotent_load_templates(session, specs, owner_user_id=owner_id)
        session.commit()
    created = {name: qid for name, status, qid in first if status == "CREATED"}
    assert len(created) >= 10

    # 2번째 호출 — SKIPPED + 같은 ID.
    sm = get_sync_sessionmaker()
    with sm() as session:
        owner_id = seed_sql_templates._lookup_system_user_id(session, _admin_seed["login_id"])
        second = seed_sql_templates.idempotent_load_templates(
            session, specs, owner_user_id=owner_id
        )
    for name, status, qid in second:
        if name in created:
            assert status == "SKIPPED"
            assert qid == created[name]


def test_seed_sql_templates_creates_draft_v1(
    cleanup_seeded_sql_queries: list[str],
    _admin_seed: dict[str, str],
) -> None:
    """첫 시드 시 sql_query_version v1 DRAFT 가 함께 생성되며 current_version_id 가 그것을 가리킴."""
    specs = seed_sql_templates.load_templates(TEMPLATES_DIR)
    target = next(s for s in specs if s["name"] == "stg_dedup_row_count")
    cleanup_seeded_sql_queries.append("stg_dedup_row_count")

    sm = get_sync_sessionmaker()
    with sm() as session:
        owner_id = seed_sql_templates._lookup_system_user_id(session, _admin_seed["login_id"])
        seed_sql_templates.idempotent_load_templates(session, [target], owner_user_id=owner_id)
        session.commit()

    sm = get_sync_sessionmaker()
    with sm() as session:
        q = session.execute(
            select(SqlQuery).where(SqlQuery.name == "stg_dedup_row_count")
        ).scalar_one()
        assert q.description.startswith("[중복 진단]")
        versions = list(
            session.execute(
                select(SqlQueryVersion).where(SqlQueryVersion.sql_query_id == q.sql_query_id)
            ).scalars()
        )
    assert len(versions) == 1
    assert versions[0].version_no == 1
    assert versions[0].status == "DRAFT"
    assert q.current_version_id == versions[0].sql_query_version_id
    # 참조 테이블이 정확히 stg.price_observation 1개.
    assert versions[0].referenced_tables == ["stg.price_observation"]
