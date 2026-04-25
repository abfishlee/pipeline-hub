"""SQL Studio API 통합 테스트 (Phase 3.2.4).

POST /v1/sql-studio/validate — sqlglot AST dry-run.

검증 정책 (app.integrations.sqlglot_validator):
- 허용 statement: SELECT / UNION / CTE 만.
- 허용 schema: mart / stg / wf.
- 차단 키워드: DROP / DELETE / INSERT / UPDATE / COPY / TRUNCATE / ALTER / GRANT / VACUUM …
- 차단 함수: pg_read_*, pg_ls_*, lo_*, dblink, COPY 류 …
- 차단 schema: pg_catalog, information_schema.

실 PG 의존성 없음 — 정적 분석만이라 conftest 의 _require_db_reachable 제약은
받지만 별도 DB 쓰기는 없다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _post(client: TestClient, sql: str, auth: dict[str, str]) -> dict[str, object]:
    r = client.post("/v1/sql-studio/validate", json={"sql": sql}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_validate_happy_path(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    """평범한 SELECT 는 valid=true + referenced_tables 회수."""
    body = _post(
        it_client,
        "SELECT product_id, price FROM stg.daily_prices WHERE captured_at >= now() - interval '1 day'",
        admin_auth,
    )
    assert body["valid"] is True, body
    assert body["error"] is None
    refs = body["referenced_tables"]
    assert any("stg.daily_prices" in t or t.endswith("daily_prices") for t in refs), refs


def test_validate_drop_rejected(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    """DDL — DROP 거부."""
    body = _post(it_client, "DROP TABLE stg.daily_prices", admin_auth)
    assert body["valid"] is False
    assert body["error"]


def test_validate_pg_read_function_rejected(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """파일시스템 누출 함수 — pg_read_file 거부.

    validator 가 FROM 절도 요구하므로 합법 schema 의 더미 테이블을 묶어 SELECT 자체는
    문법적으로 통과시키고, 함수 차단 정책에 막히는지 검증.
    """
    body = _post(
        it_client,
        "SELECT pg_read_file('/etc/passwd') AS leaked FROM stg.daily_prices LIMIT 1",
        admin_auth,
    )
    assert body["valid"] is False
    assert body["error"]


def test_validate_pg_catalog_rejected(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    """차단 schema — pg_catalog 직접 조회 거부."""
    body = _post(
        it_client,
        "SELECT relname FROM pg_catalog.pg_class",
        admin_auth,
    )
    assert body["valid"] is False
    assert body["error"]


def test_validate_delete_rejected(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    """DML — DELETE 거부."""
    body = _post(
        it_client,
        "DELETE FROM stg.daily_prices WHERE 1=1",
        admin_auth,
    )
    assert body["valid"] is False
    assert body["error"]


def test_validate_copy_rejected(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    """COPY 류 — exfiltration 위험으로 거부."""
    body = _post(
        it_client,
        "COPY stg.daily_prices TO '/tmp/exfil.csv'",
        admin_auth,
    )
    assert body["valid"] is False
    assert body["error"]


def test_validate_disallowed_schema_rejected(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """허용 schema 외 (예: ctl) 거부 — Phase 3.2.4 한정 mart/stg/wf 만."""
    body = _post(
        it_client,
        "SELECT login_id FROM ctl.app_user",
        admin_auth,
    )
    assert body["valid"] is False
    assert body["error"]


def test_validate_requires_auth(it_client: TestClient) -> None:
    """미인증 요청은 401."""
    r = it_client.post("/v1/sql-studio/validate", json={"sql": "SELECT 1 FROM mart.product"})
    assert r.status_code == 401, r.text


def test_validate_viewer_forbidden(it_client: TestClient, viewer_auth: dict[str, str]) -> None:
    """VIEWER 는 403 — ADMIN/APPROVER/OPERATOR 만 허용."""
    r = it_client.post(
        "/v1/sql-studio/validate",
        json={"sql": "SELECT 1 FROM mart.product"},
        headers=viewer_auth,
    )
    assert r.status_code == 403, r.text


def test_validate_operator_allowed(it_client: TestClient, operator_auth: dict[str, str]) -> None:
    """OPERATOR 는 허용 — 광범위 SELECT 검증 권한."""
    r = it_client.post(
        "/v1/sql-studio/validate",
        json={"sql": "SELECT 1 FROM mart.product"},
        headers=operator_auth,
    )
    assert r.status_code == 200, r.text


def test_validate_empty_string_422(it_client: TestClient, admin_auth: dict[str, str]) -> None:
    """완전 공백 입력은 pydantic min_length=1 로 422."""
    r = it_client.post("/v1/sql-studio/validate", json={"sql": ""}, headers=admin_auth)
    assert r.status_code == 422, r.text


def test_validate_whitespace_only_returns_invalid(
    it_client: TestClient, admin_auth: dict[str, str]
) -> None:
    """공백만 있는 SQL — pydantic 은 통과(min_length=1)하지만 validator 가 'empty SQL' 반환."""
    body = _post(it_client, "   ", admin_auth)
    assert body["valid"] is False
    assert body["error"]
