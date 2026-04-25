"""SQL Studio sandbox / EXPLAIN / 승인 플로우 통합 테스트 (Phase 3.2.5).

실 PG 의존. mart/stg/wf schema 의 임시 더미 테이블을 만들어 preview 결과를 검증한다.
모든 sandbox 트랜잭션은 ROLLBACK 으로 끝나므로 INSERT 한 row 가 다음 호출에 보이지
않는다 — 이를 활용해 read-only 격리도 동시에 검증한다.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker

DUMMY_TABLE = "stg.it_sql_studio_dummy"


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@pytest.fixture(scope="module")
def _dummy_table(integration_settings: Settings) -> Iterator[None]:
    """preview 가 실제로 row 를 읽을 수 있도록 stg 에 더미 테이블 시드.

    ROLLBACK 격리 검증을 위해서도 필요 — sandbox 내부에서 INSERT 시도 시 read-only
    오류가 나거나, 강제로 통과해도 ROLLBACK 으로 사라져야 한다.
    """
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(f"DROP TABLE IF EXISTS {DUMMY_TABLE}")
        cur.execute(
            f"""
            CREATE TABLE {DUMMY_TABLE} (
                id          BIGSERIAL PRIMARY KEY,
                product     TEXT NOT NULL,
                price       NUMERIC(12,2) NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            f"INSERT INTO {DUMMY_TABLE} (product, price) VALUES "
            "('apple', 1500), ('banana', 800), ('cabbage', 2400)"
        )
    yield
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(f"DROP TABLE IF EXISTS {DUMMY_TABLE}")
    dispose_sync_engine()


@pytest.fixture
def cleanup_sql_queries(integration_settings: Settings) -> Iterator[list[str]]:
    """생성된 sql_query.name 을 종료 시 정리."""
    names: list[str] = []
    yield names
    if not names:
        return
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "DELETE FROM audit.sql_execution_log WHERE sql_query_version_id IN ("
            " SELECT v.sql_query_version_id"
            "   FROM wf.sql_query_version v"
            "   JOIN wf.sql_query q ON q.sql_query_id = v.sql_query_id"
            "  WHERE q.name = ANY(%s)"
            ")",
            (names,),
        )
        # current_version_id 자기참조 FK 때문에 NULL 후 row 삭제.
        cur.execute(
            "UPDATE wf.sql_query SET current_version_id = NULL WHERE name = ANY(%s)", (names,)
        )
        cur.execute(
            "DELETE FROM wf.sql_query_version WHERE sql_query_id IN ("
            "  SELECT sql_query_id FROM wf.sql_query WHERE name = ANY(%s)"
            ")",
            (names,),
        )
        cur.execute("DELETE FROM wf.sql_query WHERE name = ANY(%s)", (names,))


# ---------------------------------------------------------------------------
# preview / explain
# ---------------------------------------------------------------------------
def test_preview_returns_rows_and_truncates(
    it_client: TestClient, admin_auth: dict[str, str], _dummy_table: None
) -> None:
    r = it_client.post(
        "/v1/sql-studio/preview",
        json={"sql": f"SELECT product, price FROM {DUMMY_TABLE}", "limit": 2},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["product", "price"]
    assert body["row_count"] == 2
    assert body["truncated"] is True
    assert len(body["rows"]) == 2


def test_preview_blocks_dangerous_sql(
    it_client: TestClient, admin_auth: dict[str, str], _dummy_table: None
) -> None:
    """sqlglot 가 1차로 차단 → 422."""
    r = it_client.post(
        "/v1/sql-studio/preview",
        json={"sql": "DROP TABLE stg.daily_prices"},
        headers=admin_auth,
    )
    assert r.status_code == 422, r.text


def test_preview_read_only_isolation(
    it_client: TestClient, admin_auth: dict[str, str], _dummy_table: None
) -> None:
    """sqlglot 화이트리스트가 INSERT/UPDATE 모두 거부 → 422.

    `transaction_read_only` 까지 도달하지 않더라도 첫 단계에서 차단되는 게 정상.
    """
    r = it_client.post(
        "/v1/sql-studio/preview",
        json={"sql": f"INSERT INTO {DUMMY_TABLE} (product, price) VALUES ('x', 1)"},
        headers=admin_auth,
    )
    assert r.status_code == 422, r.text

    # 정말로 row 가 추가되지 않았는지 확인 (audit 격리 + 도메인 이전 단계 차단).
    sm = get_sync_sessionmaker()
    with sm() as session:
        n = session.execute(text(f"SELECT count(*) FROM {DUMMY_TABLE}")).scalar()
    assert n == 3


def test_explain_returns_plan_json(
    it_client: TestClient, admin_auth: dict[str, str], _dummy_table: None
) -> None:
    r = it_client.post(
        "/v1/sql-studio/explain",
        json={"sql": f"SELECT product FROM {DUMMY_TABLE}"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["plan_json"], list) and body["plan_json"]
    assert "Plan" in body["plan_json"][0]


def test_preview_viewer_forbidden(
    it_client: TestClient, viewer_auth: dict[str, str], _dummy_table: None
) -> None:
    r = it_client.post(
        "/v1/sql-studio/preview",
        json={"sql": f"SELECT 1 FROM {DUMMY_TABLE}"},
        headers=viewer_auth,
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Query / Version 승인 플로우
# ---------------------------------------------------------------------------
def test_query_lifecycle_create_submit_approve(
    it_client: TestClient,
    admin_auth: dict[str, str],
    operator_auth: dict[str, str],
    rand_suffix: str,
    cleanup_sql_queries: list[str],
    _dummy_table: None,
) -> None:
    """OPERATOR 가 query 생성 + submit, ADMIN 이 approve.

    self-approval 차단을 같이 검증하기 위해 OPERATOR 가 submit 한 뒤 ADMIN 이 approve.
    """
    name = f"it_studio_{rand_suffix}"
    cleanup_sql_queries.append(name)

    # 1) OPERATOR — create (자동 v1 DRAFT)
    r = it_client.post(
        "/v1/sql-studio/queries",
        json={
            "name": name,
            "description": "IT lifecycle",
            "sql_text": f"SELECT product FROM {DUMMY_TABLE}",
        },
        headers=operator_auth,
    )
    assert r.status_code == 201, r.text
    detail = r.json()
    qid = detail["sql_query_id"]
    v1_id = detail["versions"][0]["sql_query_version_id"]
    assert detail["versions"][0]["status"] == "DRAFT"

    # 2) OPERATOR — submit → PENDING
    r = it_client.post(
        f"/v1/sql-studio/versions/{v1_id}/submit",
        headers=operator_auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PENDING"

    # 3) self-approval 차단 — submitter 자신이 approve 시도하면 422
    r = it_client.post(
        f"/v1/sql-studio/versions/{v1_id}/approve",
        json={"comment": None},
        headers=operator_auth,
    )
    # OPERATOR 는 approve dependency 자체에서 403.
    assert r.status_code == 403, r.text

    # 4) ADMIN — approve
    r = it_client.post(
        f"/v1/sql-studio/versions/{v1_id}/approve",
        json={"comment": "looks good"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["review_comment"] == "looks good"

    # 5) detail 재조회 → current_version_id 갱신 확인
    r = it_client.get(f"/v1/sql-studio/queries/{qid}", headers=operator_auth)
    assert r.status_code == 200
    assert r.json()["current_version_id"] == v1_id


def test_approve_self_submitted_blocked(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_sql_queries: list[str],
    _dummy_table: None,
) -> None:
    """ADMIN 이 자신이 submit 한 버전을 직접 approve 시도 → 422 (self-approval)."""
    name = f"it_studio_self_{rand_suffix}"
    cleanup_sql_queries.append(name)

    r = it_client.post(
        "/v1/sql-studio/queries",
        json={"name": name, "sql_text": f"SELECT 1 FROM {DUMMY_TABLE}"},
        headers=admin_auth,
    )
    assert r.status_code == 201, r.text
    v1_id = r.json()["versions"][0]["sql_query_version_id"]

    r = it_client.post(f"/v1/sql-studio/versions/{v1_id}/submit", headers=admin_auth)
    assert r.status_code == 200

    r = it_client.post(
        f"/v1/sql-studio/versions/{v1_id}/approve",
        json={"comment": None},
        headers=admin_auth,
    )
    assert r.status_code == 422, r.text
    assert "self" in r.text.lower()


def test_reject_then_new_draft(
    it_client: TestClient,
    admin_auth: dict[str, str],
    operator_auth: dict[str, str],
    rand_suffix: str,
    cleanup_sql_queries: list[str],
    _dummy_table: None,
) -> None:
    """REJECTED 후 새 DRAFT 추가 — version_no 증가."""
    name = f"it_studio_reject_{rand_suffix}"
    cleanup_sql_queries.append(name)

    r = it_client.post(
        "/v1/sql-studio/queries",
        json={"name": name, "sql_text": f"SELECT product FROM {DUMMY_TABLE}"},
        headers=operator_auth,
    )
    assert r.status_code == 201
    detail = r.json()
    qid = detail["sql_query_id"]
    v1_id = detail["versions"][0]["sql_query_version_id"]

    it_client.post(f"/v1/sql-studio/versions/{v1_id}/submit", headers=operator_auth)
    r = it_client.post(
        f"/v1/sql-studio/versions/{v1_id}/reject",
        json={"comment": "missing dedup"},
        headers=admin_auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED"

    # 같은 owner 가 새 draft 추가
    r = it_client.post(
        f"/v1/sql-studio/queries/{qid}/versions",
        json={"sql_text": f"SELECT product, price FROM {DUMMY_TABLE}"},
        headers=operator_auth,
    )
    assert r.status_code == 201, r.text
    assert r.json()["version_no"] == 2
    assert r.json()["status"] == "DRAFT"


def test_create_query_invalid_sql_422(
    it_client: TestClient,
    admin_auth: dict[str, str],
    rand_suffix: str,
    cleanup_sql_queries: list[str],
) -> None:
    """sqlglot 차단 SQL 로 create 시 422 — 이름 충돌 cleanup 회피."""
    name = f"it_studio_bad_{rand_suffix}"
    # Name should never reach DB (transaction rollback) — so don't add to cleanup.

    r = it_client.post(
        "/v1/sql-studio/queries",
        json={"name": name, "sql_text": "DROP TABLE stg.daily_prices"},
        headers=admin_auth,
    )
    assert r.status_code == 422, r.text


def test_audit_log_records_validate(
    it_client: TestClient,
    admin_auth: dict[str, str],
    integration_settings: Settings,
    _dummy_table: None,
) -> None:
    """validate 호출이 audit.sql_execution_log 에 SUCCESS row 1개 적재."""
    sql = f"SELECT product FROM {DUMMY_TABLE}"
    r = it_client.post("/v1/sql-studio/validate", json={"sql": sql}, headers=admin_auth)
    assert r.status_code == 200

    # hash 로 해당 row 직접 조회 (다른 테스트와 격리).
    import hashlib

    sql_hash = hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()
    with (
        psycopg.connect(_sync_url(integration_settings.database_url)) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT execution_kind, status FROM audit.sql_execution_log "
            "WHERE sql_hash = %s ORDER BY started_at DESC LIMIT 1",
            (sql_hash,),
        )
        row = cur.fetchone()
    assert row == ("VALIDATE", "SUCCESS")
