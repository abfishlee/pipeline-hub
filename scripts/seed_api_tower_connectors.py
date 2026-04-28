"""Seed Source/API connectors from the local API Tower demo service.

The API Tower at http://localhost:9090 exposes five virtual retailers:
four JSON endpoints and one XML endpoint. This script imports those endpoints
as PUBLISHED Source/API connectors and creates minimal domain/resource/contract
metadata so Field Mapping can start immediately.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.domain.public_api.parsers import parse_response  # noqa: E402

DOMAIN_CODE = "agri_price"
DOMAIN_NAME = "농수산물 가격정보"
BASE_URL = "http://localhost:9090"

RESPONSE_PATHS = {
    "martking": "products",
    "superfresh": "items",
    "nongsusan": "상품목록",
    "thefresh": "DATA_LIST",
    "hanarum": "응답.바디.상품목록.상품",
}


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _resource_code(company: dict[str, Any]) -> str:
    return f"{company['id']}_products"


def _source_code(resource_code: str) -> str:
    raw = f"API_{DOMAIN_CODE}_{resource_code}".upper()
    return re.sub(r"[^A-Z0-9_]+", "_", raw).strip("_")[:64]


def _infer_schema(rows: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, dict[str, str]] = {}
    for row in rows[:20]:
        for key, value in row.items():
            if key in props:
                continue
            if isinstance(value, bool):
                typ = "boolean"
            elif isinstance(value, int):
                typ = "integer"
            elif isinstance(value, float):
                typ = "number"
            elif isinstance(value, list):
                typ = "array"
            elif isinstance(value, dict):
                typ = "object"
            else:
                typ = "string"
            props[str(key)] = {"type": typ}
    return {"type": "object", "properties": props, "sample_rows": rows[:10]}


def _fetch_meta(base_url: str) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{base_url}/api/_meta/companies")
        resp.raise_for_status()
        return resp.json()


def _fetch_sample(base_url: str, company: dict[str, Any], size: int = 5) -> list[dict[str, Any]]:
    params = {
        company["params"]["apiKey"]: company["apiKey"],
        company["params"]["pageSize"]: str(size),
    }
    url = f"{base_url}{company['endpoint']}?{urlencode(params)}"
    with httpx.Client(timeout=15) as client:
        resp = client.get(url, headers={"X-API-KEY": company["apiKey"]})
        resp.raise_for_status()
        return parse_response(
            body=resp.content,
            response_format=company["format"],
            response_path=RESPONSE_PATHS[company["id"]],
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _admin_user_id(cur: psycopg.Cursor[Any]) -> int | None:
    cur.execute(
        "SELECT user_id FROM ctl.app_user WHERE login_id IN ('admin', 'it_admin') "
        "ORDER BY CASE login_id WHEN 'admin' THEN 0 ELSE 1 END LIMIT 1"
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def seed(base_url: str, verify: bool) -> None:
    settings = get_settings()
    meta = _fetch_meta(base_url)
    companies = meta.get("companies") or []
    if not companies:
        raise RuntimeError(f"No companies returned from {base_url}/api/_meta/companies")

    with (
        psycopg.connect(_sync_url(settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
            user_id = _admin_user_id(cur)
            cur.execute(
                """
                INSERT INTO domain.domain_definition
                  (domain_code, name, description, schema_yaml, status)
                VALUES (%s, %s, %s, %s::jsonb, 'PUBLISHED')
                ON CONFLICT (domain_code) DO UPDATE SET
                  name = EXCLUDED.name,
                  description = EXCLUDED.description,
                  schema_yaml = EXCLUDED.schema_yaml,
                  status = 'PUBLISHED',
                  updated_at = now()
                """,
                (
                    DOMAIN_CODE,
                    DOMAIN_NAME,
                    "API Tower 5개 가상 유통사의 농축수산물 가격 API",
                    _json({"source": base_url, "companies": [c["id"] for c in companies]}),
                ),
            )

            for company in companies:
                resource_code = _resource_code(company)
                endpoint_url = f"{base_url}{company['endpoint']}"
                query_template = {company["params"]["apiKey"]: company["apiKey"]}
                pagination_config = {
                    "page_param_name": company["params"]["page"],
                    "size_param_name": company["params"]["pageSize"],
                    "page_size": int(company["defaultLimit"]),
                    "start_page": 1,
                }
                response_path = RESPONSE_PATHS[company["id"]]

                cur.execute(
                    """
                    INSERT INTO domain.resource_definition
                      (domain_code, resource_code, canonical_table, fact_table, status)
                    VALUES (%s, %s, %s, %s, 'PUBLISHED')
                    ON CONFLICT (domain_code, resource_code, version) DO UPDATE SET
                      canonical_table = EXCLUDED.canonical_table,
                      fact_table = EXCLUDED.fact_table,
                      status = 'PUBLISHED',
                      updated_at = now()
                    """,
                    (
                        DOMAIN_CODE,
                        resource_code,
                        f"{DOMAIN_CODE}_stg.{resource_code}",
                        f"{DOMAIN_CODE}_mart.{resource_code}",
                    ),
                )

                cur.execute(
                    """
                    SELECT connector_id
                      FROM domain.public_api_connector
                     WHERE domain_code = %s
                       AND resource_code = %s
                       AND name = %s
                     ORDER BY connector_id
                     LIMIT 1
                    """,
                    (DOMAIN_CODE, resource_code, company["nameKo"]),
                )
                row = cur.fetchone()
                payload = (
                    DOMAIN_CODE,
                    resource_code,
                    company["nameKo"],
                    f"{company['nameKo']} ({company['nameEn']}) API Tower demo endpoint",
                    endpoint_url,
                    "GET",
                    "none",
                    None,
                    None,
                    _json({"X-API-KEY": company["apiKey"]}),
                    _json(query_template),
                    "page_number",
                    _json(pagination_config),
                    company["format"],
                    response_path,
                    15,
                    2,
                    120,
                    "PUBLISHED",
                    True,
                    user_id,
                )
                if row:
                    connector_id = int(row[0])
                    cur.execute(
                        """
                        UPDATE domain.public_api_connector SET
                          domain_code = %s,
                          resource_code = %s,
                          name = %s,
                          description = %s,
                          endpoint_url = %s,
                          http_method = %s,
                          auth_method = %s,
                          auth_param_name = %s,
                          secret_ref = %s,
                          request_headers = %s::jsonb,
                          query_template = %s::jsonb,
                          pagination_kind = %s,
                          pagination_config = %s::jsonb,
                          response_format = %s,
                          response_path = %s,
                          timeout_sec = %s,
                          retry_max = %s,
                          rate_limit_per_min = %s,
                          status = %s,
                          is_active = %s,
                          created_by = COALESCE(created_by, %s),
                          updated_at = now()
                        WHERE connector_id = %s
                        """,
                        (*payload, connector_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO domain.public_api_connector
                          (domain_code, resource_code, name, description, endpoint_url,
                           http_method, auth_method, auth_param_name, secret_ref,
                           request_headers, query_template, pagination_kind,
                           pagination_config, response_format, response_path,
                           timeout_sec, retry_max, rate_limit_per_min,
                           status, is_active, created_by)
                        VALUES
                          (%s, %s, %s, %s, %s,
                           %s, %s, %s, %s,
                           %s::jsonb, %s::jsonb, %s,
                           %s::jsonb, %s, %s,
                           %s, %s, %s,
                           %s, %s, %s)
                        RETURNING connector_id
                        """,
                        payload,
                    )
                    connector_id = int(cur.fetchone()[0])

                sample_rows = _fetch_sample(base_url, company)
                source_code = _source_code(resource_code)
                cur.execute(
                    """
                    INSERT INTO ctl.data_source
                      (source_code, source_name, source_type, is_active, config_json)
                    VALUES (%s, %s, 'API', TRUE, %s::jsonb)
                    ON CONFLICT (source_code) DO UPDATE SET
                      source_name = EXCLUDED.source_name,
                      is_active = TRUE,
                      config_json = EXCLUDED.config_json,
                      updated_at = now()
                    RETURNING source_id
                    """,
                    (
                        source_code,
                        company["nameKo"],
                        _json(
                            {
                                "connector_id": connector_id,
                                "endpoint_url": endpoint_url,
                                "api_tower_company_id": company["id"],
                            }
                        ),
                    ),
                )
                source_id = int(cur.fetchone()[0])
                cur.execute(
                    """
                    INSERT INTO domain.source_contract
                      (source_id, domain_code, resource_code, schema_version,
                       schema_json, compatibility_mode, resource_selector_json,
                       status, description)
                    VALUES (%s, %s, %s, 1, %s::jsonb, 'backward', %s::jsonb,
                            'PUBLISHED', %s)
                    ON CONFLICT (source_id, domain_code, resource_code, schema_version)
                    DO UPDATE SET
                      schema_json = EXCLUDED.schema_json,
                      resource_selector_json = EXCLUDED.resource_selector_json,
                      status = 'PUBLISHED',
                      description = EXCLUDED.description,
                      updated_at = now()
                    """,
                    (
                        source_id,
                        DOMAIN_CODE,
                        resource_code,
                        _json(_infer_schema(sample_rows)),
                        _json({"endpoint": company["endpoint"], "response_path": response_path}),
                        f"API Tower {company['nameKo']} sample contract",
                    ),
                )

                if verify:
                    print(
                        f"OK {company['id']}: connector_id={connector_id}, "
                        f"rows={len(sample_rows)}, path={response_path}"
                    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()
    seed(args.base_url.rstrip("/"), verify=not args.no_verify)


if __name__ == "__main__":
    main()
