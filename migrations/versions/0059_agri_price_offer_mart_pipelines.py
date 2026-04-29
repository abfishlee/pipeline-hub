"""Create agri price offer mart and demo Canvas workflows.

Revision ID: 0059
Revises: 0058
Create Date: 2026-04-29 00:20:00+09:00
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TARGET_TABLE = "agri_price_mart.retail_price_offers"


ASSETS: dict[str, str] = {
    "normalize_martking_offer": """
SELECT
  dq.to_date(payload ->> 'collection_date') AS collection_date,
  payload ->> 'business_type' AS business_type,
  payload ->> 'company_name' AS vendor_name,
  payload ->> 'region' AS region_name,
  payload ->> 'store_name' AS store_name,
  payload ->> 'category' AS agri_category,
  payload ->> 'item' AS item_name,
  payload ->> 'variety' AS variety,
  payload ->> 'quality_grade' AS quality_grade,
  payload ->> 'product_name' AS product_name,
  payload ->> 'product_code' AS product_code,
  payload ->> 'grade_spec' AS grade_spec,
  payload ->> 'sales_unit' AS sale_unit,
  payload ->> 'content_volume' AS package_size,
  dq.to_numeric(payload ->> 'regular_price') AS regular_price,
  dq.to_numeric(payload ->> 'sale_price') AS sale_price,
  dq.to_numeric(payload ->> 'event_price') AS promotional_price,
  payload ->> 'sales_status' AS sale_status,
  dq.to_bool_yn(payload ->> 'is_event') AS promotion_yn,
  payload ->> 'event_type' AS promotion_type,
  payload ->> 'purchase_limit' AS purchase_limit,
  payload ->> 'origin' AS origin,
  payload ->> 'eco_certification' AS eco_certification,
  dq.to_bool_yn(payload ->> 'online_sales') AS online_sales_yn,
  dq.to_bool_yn(payload ->> 'delivery_available') AS delivery_available_yn,
  dq.to_numeric(payload ->> 'stock') AS stock_quantity,
  dq.to_numeric(payload ->> 'initial_stock') AS base_stock,
  'martking_products' AS source_code,
  payload ->> 'product_key' AS vendor_product_id
FROM {{input_table}}
WHERE dq.is_not_blank(payload ->> 'store_name') = 1
  AND dq.is_not_blank(payload ->> 'item') = 1
  AND dq.is_not_blank(payload ->> 'sales_unit') = 1
  AND dq.to_numeric(payload ->> 'regular_price') IS NOT NULL
""",
    "normalize_superfresh_offer": """
SELECT
  dq.to_date(payload ->> 'collectionDate') AS collection_date,
  payload ->> 'businessType' AS business_type,
  payload ->> 'companyName' AS vendor_name,
  payload ->> 'region' AS region_name,
  payload ->> 'storeName' AS store_name,
  payload ->> 'category' AS agri_category,
  payload ->> 'itemName' AS item_name,
  payload ->> 'variety' AS variety,
  payload ->> 'qualityGrade' AS quality_grade,
  payload ->> 'productName' AS product_name,
  payload ->> 'productCode' AS product_code,
  payload ->> 'gradeSpec' AS grade_spec,
  payload ->> 'salesUnit' AS sale_unit,
  payload ->> 'contentVolume' AS package_size,
  dq.to_numeric(payload ->> 'regularPrice') AS regular_price,
  dq.to_numeric(payload ->> 'salePrice') AS sale_price,
  dq.to_numeric(payload ->> 'eventPrice') AS promotional_price,
  payload ->> 'salesStatus' AS sale_status,
  dq.to_bool_yn(payload ->> 'isEvent') AS promotion_yn,
  payload ->> 'eventType' AS promotion_type,
  payload ->> 'purchaseLimit' AS purchase_limit,
  payload ->> 'origin' AS origin,
  payload ->> 'ecoCertification' AS eco_certification,
  dq.to_bool_yn(payload ->> 'onlineSales') AS online_sales_yn,
  dq.to_bool_yn(payload ->> 'deliveryAvailable') AS delivery_available_yn,
  dq.to_numeric(payload ->> 'stock') AS stock_quantity,
  dq.to_numeric(payload ->> 'initialStock') AS base_stock,
  'superfresh_products' AS source_code,
  payload ->> 'productKey' AS vendor_product_id
FROM {{input_table}}
WHERE dq.is_not_blank(payload ->> 'storeName') = 1
  AND dq.is_not_blank(payload ->> 'itemName') = 1
  AND dq.is_not_blank(payload ->> 'salesUnit') = 1
  AND dq.to_numeric(payload ->> 'regularPrice') IS NOT NULL
""",
    "normalize_nongsusan_offer": """
SELECT
  dq.to_date(payload ->> '수집일자') AS collection_date,
  payload ->> '업태' AS business_type,
  payload ->> '업체명' AS vendor_name,
  payload ->> '지역명' AS region_name,
  payload ->> '점포명' AS store_name,
  payload ->> '농산물부류' AS agri_category,
  payload ->> '품목' AS item_name,
  payload ->> '품종' AS variety,
  payload ->> '품질등급' AS quality_grade,
  payload ->> '상품명' AS product_name,
  payload ->> '상품코드' AS product_code,
  payload ->> '등급규격' AS grade_spec,
  payload ->> '판매단위' AS sale_unit,
  payload ->> '내용량' AS package_size,
  dq.to_numeric(payload ->> '정상가') AS regular_price,
  dq.to_numeric(payload ->> '판매가') AS sale_price,
  dq.to_numeric(payload ->> '행사가') AS promotional_price,
  payload ->> '판매상태' AS sale_status,
  dq.to_bool_yn(payload ->> '행사여부') AS promotion_yn,
  payload ->> '행사유형' AS promotion_type,
  payload ->> '구매제한' AS purchase_limit,
  payload ->> '원산지' AS origin,
  payload ->> '친환경인증' AS eco_certification,
  dq.to_bool_yn(payload ->> '온라인판매') AS online_sales_yn,
  dq.to_bool_yn(payload ->> '배달가능') AS delivery_available_yn,
  dq.to_numeric(payload ->> '재고') AS stock_quantity,
  dq.to_numeric(payload ->> '기준재고') AS base_stock,
  'nongsusan_products' AS source_code,
  payload ->> '상품번호' AS vendor_product_id
FROM {{input_table}}
WHERE dq.is_not_blank(payload ->> '점포명') = 1
  AND dq.is_not_blank(payload ->> '품목') = 1
  AND dq.is_not_blank(payload ->> '판매단위') = 1
  AND dq.to_numeric(payload ->> '정상가') IS NOT NULL
""",
    "normalize_thefresh_offer": """
SELECT
  dq.to_date(payload ->> 'COL_DT') AS collection_date,
  payload ->> 'BIZ_TYPE' AS business_type,
  payload ->> 'CMP_NM' AS vendor_name,
  payload ->> 'REG_NM' AS region_name,
  payload ->> 'STR_NM' AS store_name,
  payload ->> 'CAT_NM' AS agri_category,
  payload ->> 'ITM_NM' AS item_name,
  payload ->> 'VAR_NM' AS variety,
  payload ->> 'QLT_GRD' AS quality_grade,
  payload ->> 'PRD_NM' AS product_name,
  payload ->> 'PRD_CD' AS product_code,
  payload ->> 'GRD_SPEC' AS grade_spec,
  payload ->> 'SAL_UNT' AS sale_unit,
  payload ->> 'CNT_VOL' AS package_size,
  dq.to_numeric(payload ->> 'REG_PRC') AS regular_price,
  dq.to_numeric(payload ->> 'SAL_PRC') AS sale_price,
  dq.to_numeric(payload ->> 'EVT_PRC') AS promotional_price,
  payload ->> 'SAL_STS' AS sale_status,
  dq.to_bool_yn(payload ->> 'EVT_YN') AS promotion_yn,
  payload ->> 'EVT_TYPE' AS promotion_type,
  payload ->> 'BUY_LMT' AS purchase_limit,
  payload ->> 'ORG_NM' AS origin,
  payload ->> 'ECO_CERT' AS eco_certification,
  dq.to_bool_yn(payload ->> 'ONL_SAL_YN') AS online_sales_yn,
  dq.to_bool_yn(payload ->> 'DLV_YN') AS delivery_available_yn,
  dq.to_numeric(payload ->> 'STK_QTY') AS stock_quantity,
  dq.to_numeric(payload ->> 'BASE_STK') AS base_stock,
  'thefresh_products' AS source_code,
  payload ->> 'PRD_NO' AS vendor_product_id
FROM {{input_table}}
WHERE dq.is_not_blank(payload ->> 'STR_NM') = 1
  AND dq.is_not_blank(payload ->> 'ITM_NM') = 1
  AND dq.is_not_blank(payload ->> 'SAL_UNT') = 1
  AND dq.to_numeric(payload ->> 'REG_PRC') IS NOT NULL
""",
    "normalize_hanarum_offer": """
SELECT
  dq.to_date(payload ->> '수집일자') AS collection_date,
  payload ->> '업태' AS business_type,
  payload ->> '업체명' AS vendor_name,
  payload ->> '지역명' AS region_name,
  payload ->> '점포명' AS store_name,
  payload ->> '농산물부류' AS agri_category,
  payload ->> '품목' AS item_name,
  payload ->> '품종' AS variety,
  payload ->> '품질등급' AS quality_grade,
  payload ->> '상품명' AS product_name,
  payload ->> '상품코드' AS product_code,
  payload ->> '등급규격' AS grade_spec,
  payload ->> '판매단위' AS sale_unit,
  payload ->> '내용량' AS package_size,
  dq.to_numeric(payload ->> '정상가') AS regular_price,
  dq.to_numeric(payload ->> '판매가') AS sale_price,
  dq.to_numeric(payload ->> '행사가') AS promotional_price,
  payload ->> '판매상태' AS sale_status,
  dq.to_bool_yn(payload ->> '행사여부') AS promotion_yn,
  payload ->> '행사유형' AS promotion_type,
  payload ->> '구매제한' AS purchase_limit,
  payload ->> '원산지' AS origin,
  payload ->> '친환경인증' AS eco_certification,
  dq.to_bool_yn(payload ->> '온라인판매여부') AS online_sales_yn,
  dq.to_bool_yn(payload ->> '배달가능여부') AS delivery_available_yn,
  dq.to_numeric(payload ->> '재고수량') AS stock_quantity,
  dq.to_numeric(payload ->> '기준재고') AS base_stock,
  'hanarum_products' AS source_code,
  payload ->> '상품번호' AS vendor_product_id
FROM {{input_table}}
WHERE dq.is_not_blank(payload ->> '점포명') = 1
  AND dq.is_not_blank(payload ->> '품목') = 1
  AND dq.is_not_blank(payload ->> '판매단위') = 1
  AND dq.to_numeric(payload ->> '정상가') IS NOT NULL
""",
}


RETAILERS = [
    ("martking_products", 16, "normalize_martking_offer", "agri_price_martking_to_offer_mart"),
    ("superfresh_products", 17, "normalize_superfresh_offer", "agri_price_superfresh_to_offer_mart"),
    ("nongsusan_products", 18, "normalize_nongsusan_offer", "agri_price_nongsusan_to_offer_mart"),
    ("thefresh_products", 19, "normalize_thefresh_offer", "agri_price_thefresh_to_offer_mart"),
    ("hanarum_products", 20, "normalize_hanarum_offer", "agri_price_hanarum_to_offer_mart"),
]


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE SCHEMA IF NOT EXISTS agri_price_mart;")
    op.execute("CREATE SCHEMA IF NOT EXISTS agri_price_stg;")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
            offer_id BIGSERIAL PRIMARY KEY,
            collection_date DATE,
            business_type TEXT,
            vendor_name TEXT,
            region_name TEXT,
            store_name TEXT NOT NULL,
            agri_category TEXT NOT NULL,
            item_name TEXT NOT NULL,
            variety TEXT,
            quality_grade TEXT,
            product_name TEXT,
            product_code TEXT,
            grade_spec TEXT,
            sale_unit TEXT NOT NULL,
            package_size TEXT,
            regular_price NUMERIC NOT NULL,
            sale_price NUMERIC,
            promotional_price NUMERIC,
            sale_status TEXT,
            promotion_yn BOOLEAN,
            promotion_type TEXT,
            purchase_limit TEXT,
            origin TEXT,
            eco_certification TEXT,
            online_sales_yn BOOLEAN,
            delivery_available_yn BOOLEAN,
            stock_quantity NUMERIC,
            base_stock NUMERIC,
            source_code TEXT NOT NULL,
            vendor_product_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_retail_price_offer_source UNIQUE
              (source_code, vendor_product_id, store_name, collection_date)
        );
        """
    )

    bind.execute(
        text(
            """
            INSERT INTO domain.resource_definition (
              domain_code, resource_code, canonical_table, fact_table,
              standard_code_namespace, status, version
            )
            VALUES (
              'agri_price', 'retail_price_offers',
              'agri_price_stg.retail_price_offers',
              'agri_price_mart.retail_price_offers',
              NULL, 'PUBLISHED', 1
            )
            ON CONFLICT (domain_code, resource_code, version) DO UPDATE
            SET canonical_table = EXCLUDED.canonical_table,
                fact_table = EXCLUDED.fact_table,
                status = EXCLUDED.status,
                updated_at = now()
            """
        )
    )
    resource_id = bind.execute(
        text(
            """
            SELECT resource_id
            FROM domain.resource_definition
            WHERE domain_code='agri_price' AND resource_code='retail_price_offers'
            ORDER BY version DESC
            LIMIT 1
            """
        )
    ).scalar_one()
    bind.execute(
        text(
            """
            INSERT INTO domain.load_policy (
              resource_id, mode, key_columns, partition_expr, scd_options_json,
              chunk_size, statement_timeout_ms, status, version
            )
            VALUES (
              :resource_id, 'upsert',
              ARRAY['source_code','vendor_product_id','store_name','collection_date']::text[],
              NULL, '{}'::jsonb, 10000, 60000, 'PUBLISHED', 1
            )
            ON CONFLICT (resource_id, version) DO UPDATE
            SET mode = EXCLUDED.mode,
                key_columns = EXCLUDED.key_columns,
                status = EXCLUDED.status,
                updated_at = now()
            """
        ),
        {"resource_id": resource_id},
    )
    policy_id = bind.execute(
        text(
            """
            SELECT policy_id
            FROM domain.load_policy
            WHERE resource_id=:resource_id
            ORDER BY version DESC
            LIMIT 1
            """
        ),
        {"resource_id": resource_id},
    ).scalar_one()

    for code, sql in ASSETS.items():
        bind.execute(
            text(
                """
                INSERT INTO domain.sql_asset (
                  asset_code, domain_code, version, asset_type, sql_text, checksum,
                  output_table, description, status
                )
                VALUES (
                  :code, 'agri_price', 1, 'TRANSFORM_SQL', :sql, :checksum,
                  :output_table, 'Normalize retailer API payload into retail_price_offers mart shape.',
                  'PUBLISHED'
                )
                ON CONFLICT (asset_code, version) DO UPDATE
                SET asset_type = EXCLUDED.asset_type,
                    sql_text = EXCLUDED.sql_text,
                    checksum = EXCLUDED.checksum,
                    output_table = EXCLUDED.output_table,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    updated_at = now()
                """
            ),
            {
                "code": code,
                "sql": sql.strip(),
                "checksum": _checksum(sql.strip()),
                "output_table": f"agri_price_stg.{code.replace('normalize_', '').replace('_offer', '')}_offers_clean",
            },
        )

    for resource_code, connector_id, asset_code, workflow_name in RETAILERS:
        bind.execute(
            text("DELETE FROM wf.workflow_definition WHERE name=:name AND version=1"),
            {"name": workflow_name},
        )
        workflow_id = bind.execute(
            text(
                """
                INSERT INTO wf.workflow_definition (
                  name, version, description, status, created_by, published_at
                )
                VALUES (:name, 1, :description, 'PUBLISHED', 1, now())
                RETURNING workflow_id
                """
            ),
            {
                "name": workflow_name,
                "description": f"API Pull -> SQL Studio -> Mart Load for {resource_code}",
            },
        ).scalar_one()
        fetch_id = bind.execute(
            text(
                """
                INSERT INTO wf.node_definition (
                  workflow_id, node_key, node_type, config_json, position_x, position_y
                )
                VALUES (
                  :workflow_id, 'fetch_api', 'PUBLIC_API_FETCH',
                  CAST(:config AS jsonb), 120, 120
                )
                RETURNING node_id
                """
            ),
            {
                "workflow_id": workflow_id,
                "config": json.dumps(
                    {"domain_code": "agri_price", "connector_id": connector_id, "max_pages": 1},
                    ensure_ascii=False,
                ),
            },
        ).scalar_one()
        sql_id = bind.execute(
            text(
                """
                INSERT INTO wf.node_definition (
                  workflow_id, node_key, node_type, config_json, position_x, position_y
                )
                VALUES (
                  :workflow_id, 'normalize_offer', 'SQL_ASSET_TRANSFORM',
                  CAST(:config AS jsonb), 420, 120
                )
                RETURNING node_id
                """
            ),
            {
                "workflow_id": workflow_id,
                "config": json.dumps(
                    {
                        "domain_code": "agri_price",
                        "asset_code": asset_code,
                        "input_from": "fetch_api",
                    },
                    ensure_ascii=False,
                ),
            },
        ).scalar_one()
        load_id = bind.execute(
            text(
                """
                INSERT INTO wf.node_definition (
                  workflow_id, node_key, node_type, config_json, position_x, position_y
                )
                VALUES (
                  :workflow_id, 'load_mart', 'LOAD_TARGET',
                  CAST(:config AS jsonb), 720, 120
                )
                RETURNING node_id
                """
            ),
            {
                "workflow_id": workflow_id,
                "config": json.dumps(
                    {
                        "domain_code": "agri_price",
                        "policy_id": int(policy_id),
                        "input_from": "normalize_offer",
                    },
                    ensure_ascii=False,
                ),
            },
        ).scalar_one()
        bind.execute(
            text(
                """
                INSERT INTO wf.edge_definition (workflow_id, from_node_id, to_node_id)
                VALUES (:workflow_id, :fetch_id, :sql_id), (:workflow_id, :sql_id, :load_id)
                """
            ),
            {
                "workflow_id": workflow_id,
                "fetch_id": fetch_id,
                "sql_id": sql_id,
                "load_id": load_id,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for _, _, _, workflow_name in RETAILERS:
        bind.execute(
            text("DELETE FROM wf.workflow_definition WHERE name=:name AND version=1"),
            {"name": workflow_name},
        )
    bind.execute(
        text(
            "DELETE FROM domain.sql_asset WHERE asset_code = ANY(:codes)"
        ),
        {"codes": list(ASSETS.keys())},
    )
    bind.execute(
        text(
            """
            DELETE FROM domain.load_policy
            WHERE resource_id IN (
              SELECT resource_id FROM domain.resource_definition
              WHERE domain_code='agri_price' AND resource_code='retail_price_offers'
            )
            """
        )
    )
    bind.execute(
        text(
            """
            DELETE FROM domain.resource_definition
            WHERE domain_code='agri_price' AND resource_code='retail_price_offers'
            """
        )
    )
    op.execute(f"DROP TABLE IF EXISTS {TARGET_TABLE};")
