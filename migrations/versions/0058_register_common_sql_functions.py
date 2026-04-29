"""Register common SQL functions for Canvas SQL Studio.

Revision ID: 0058
Revises: 0057
Create Date: 2026-04-29 00:00:00+09:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FUNCTION_ASSETS: dict[str, str] = {
    "fn_dq_null_if_blank": """
CREATE OR REPLACE FUNCTION dq.null_if_blank(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT NULLIF(btrim(value), '')
$$;
""",
    "fn_dq_normalize_text": """
CREATE OR REPLACE FUNCTION dq.normalize_text(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN value IS NULL THEN NULL
    ELSE lower(regexp_replace(btrim(value), '\\s+', ' ', 'g'))
  END
$$;
""",
    "fn_dq_digits_only": """
CREATE OR REPLACE FUNCTION dq.digits_only(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT NULLIF(regexp_replace(coalesce(value, ''), '[^0-9]', '', 'g'), '')
$$;
""",
    "fn_dq_to_numeric": """
CREATE OR REPLACE FUNCTION dq.to_numeric(value text)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  cleaned text;
BEGIN
  cleaned := NULLIF(regexp_replace(coalesce(value, ''), '[^0-9.\\-]', '', 'g'), '');
  IF cleaned IS NULL THEN
    RETURN NULL;
  END IF;
  RETURN cleaned::numeric;
EXCEPTION WHEN others THEN
  RETURN NULL;
END;
$$;
""",
    "fn_dq_to_date": """
CREATE OR REPLACE FUNCTION dq.to_date(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v text;
BEGIN
  v := btrim(coalesce(value, ''));
  IF v = '' THEN
    RETURN NULL;
  END IF;
  BEGIN
    RETURN v::date;
  EXCEPTION WHEN others THEN
    NULL;
  END;
  BEGIN
    RETURN to_date(v, 'YYYYMMDD');
  EXCEPTION WHEN others THEN
    RETURN NULL;
  END;
END;
$$;
""",
    "fn_dq_to_bool_yn": """
CREATE OR REPLACE FUNCTION dq.to_bool_yn(value text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN value IS NULL THEN NULL
    WHEN upper(btrim(value)) IN ('Y', 'YES', 'TRUE', 'T', '1') THEN true
    WHEN upper(btrim(value)) IN ('N', 'NO', 'FALSE', 'F', '0') THEN false
    ELSE NULL
  END
$$;
""",
    "fn_dq_is_not_blank": """
CREATE OR REPLACE FUNCTION dq.is_not_blank(value text)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE WHEN dq.null_if_blank(value) IS NULL THEN 0 ELSE 1 END
$$;
""",
    "fn_dq_is_positive": """
CREATE OR REPLACE FUNCTION dq.is_positive(value numeric)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE WHEN value IS NOT NULL AND value > 0 THEN 1 ELSE 0 END
$$;
""",
    "fn_dq_is_between": """
CREATE OR REPLACE FUNCTION dq.is_between(value numeric, min_value numeric, max_value numeric)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN value IS NOT NULL AND value >= min_value AND value <= max_value THEN 1
    ELSE 0
  END
$$;
""",
    "fn_dq_safe_divide": """
CREATE OR REPLACE FUNCTION dq.safe_divide(numerator numeric, denominator numeric)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN denominator IS NULL OR denominator = 0 THEN NULL
    ELSE numerator / denominator
  END
$$;
""",
    "fn_dq_change_rate": """
CREATE OR REPLACE FUNCTION dq.change_rate(current_value numeric, previous_value numeric)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT dq.safe_divide(current_value - previous_value, previous_value)
$$;
""",
}


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dq;")
    for sql in FUNCTION_ASSETS.values():
        op.execute(sql)

    values_sql = ",\n".join(
        f"""('{code}', 'agri_price', 1, 'FUNCTION', $asset${sql.strip()}$asset$,
            md5($asset${sql.strip()}$asset$),
            NULL, 'Common SQL function registered for Canvas SQL Studio.', 'PUBLISHED')"""
        for code, sql in FUNCTION_ASSETS.items()
    )
    op.execute(
        f"""
        INSERT INTO domain.sql_asset (
            asset_code, domain_code, version, asset_type, sql_text, checksum,
            output_table, description, status
        )
        VALUES
        {values_sql}
        ON CONFLICT (asset_code, version) DO UPDATE
        SET asset_type = EXCLUDED.asset_type,
            sql_text = EXCLUDED.sql_text,
            checksum = EXCLUDED.checksum,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            updated_at = now();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM domain.sql_asset
        WHERE asset_code IN (
          'fn_dq_null_if_blank',
          'fn_dq_normalize_text',
          'fn_dq_digits_only',
          'fn_dq_to_numeric',
          'fn_dq_to_date',
          'fn_dq_to_bool_yn',
          'fn_dq_is_not_blank',
          'fn_dq_is_positive',
          'fn_dq_is_between',
          'fn_dq_safe_divide',
          'fn_dq_change_rate'
        );
        """
    )
    for name in (
        "change_rate(numeric,numeric)",
        "safe_divide(numeric,numeric)",
        "is_between(numeric,numeric,numeric)",
        "is_positive(numeric)",
        "is_not_blank(text)",
        "to_bool_yn(text)",
        "to_date(text)",
        "to_numeric(text)",
        "digits_only(text)",
        "normalize_text(text)",
        "null_if_blank(text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS dq.{name};")
