"""Unit — sqlglot 정책 검증 (Phase 3.2.2 SQL_TRANSFORM / 3.2.4 SQL Studio).

실 DB 미사용. AST 분석만.
"""

from __future__ import annotations

import pytest

from app.integrations.sqlglot_validator import SqlValidationError, validate


def test_select_from_mart_passes() -> None:
    ast, refs = validate("SELECT std_code, item_name_ko FROM mart.standard_code WHERE is_active")
    assert ast is not None
    assert "mart.standard_code" in refs


def test_select_with_join_across_allowed_schemas_passes() -> None:
    ast, refs = validate(
        "SELECT m.std_code, s.product_name_raw "
        "FROM mart.standard_code m JOIN stg.price_observation s ON s.std_code = m.std_code "
        "LIMIT 10"
    )
    assert "mart.standard_code" in refs
    assert "stg.price_observation" in refs


def test_select_from_disallowed_schema_rejected() -> None:
    with pytest.raises(SqlValidationError, match="schema"):
        validate("SELECT * FROM pg_catalog.pg_tables")


def test_unqualified_table_rejected() -> None:
    with pytest.raises(SqlValidationError, match="unqualified"):
        validate("SELECT * FROM standard_code")


def test_insert_statement_rejected() -> None:
    with pytest.raises(SqlValidationError):
        validate("INSERT INTO mart.standard_code (std_code) VALUES ('X')")


def test_update_statement_rejected() -> None:
    with pytest.raises(SqlValidationError):
        validate("UPDATE mart.standard_code SET is_active = false")


def test_delete_statement_rejected() -> None:
    with pytest.raises(SqlValidationError):
        validate("DELETE FROM mart.standard_code WHERE std_code = 'X'")


def test_drop_table_rejected() -> None:
    with pytest.raises(SqlValidationError):
        validate("DROP TABLE mart.standard_code")


def test_pg_read_file_function_rejected() -> None:
    with pytest.raises(SqlValidationError, match="pg_read"):
        validate("SELECT pg_read_file('/etc/passwd') FROM mart.standard_code LIMIT 1")


def test_copy_keyword_rejected() -> None:
    with pytest.raises(SqlValidationError, match="COPY"):
        validate("COPY mart.standard_code TO '/tmp/x.csv'")


def test_multistatement_rejected() -> None:
    with pytest.raises(SqlValidationError, match="multi-statement"):
        validate("SELECT 1 FROM mart.standard_code; DROP TABLE mart.standard_code;")


def test_empty_sql_rejected() -> None:
    with pytest.raises(SqlValidationError, match="empty"):
        validate("   ")


def test_select_without_from_rejected() -> None:
    # FROM 없는 SELECT (e.g. SELECT 1) — 운영 SQL 의 의미가 없으므로 거부.
    with pytest.raises(SqlValidationError):
        validate("SELECT 1")
