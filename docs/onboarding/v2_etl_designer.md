# v2 ETL Designer 사용법

> Phase 5.2.4 STEP 7 backend 완성. Frontend 4 page (Field Mapping / Mart Designer
> / DQ Rule Builder / Dry-run Results) 는 Phase 6 STEP 7 backlog. 본 문서는
> *backend API 직접 호출* 가이드. UI 가 추가되면 본 문서 갱신.

## 4 종 도구

| 도구 | endpoint | 권한 |
|---|---|---|
| Field Mapping | `/v2/mappings` + `/v2/dryrun/field-mapping` | DOMAIN_ADMIN+ |
| Mart Designer | `/v2/dryrun/mart-designer` | DOMAIN_ADMIN+ |
| DQ Rule Builder | `/v2/dq-rules` + `/v2/dq-rules/preview` | OPERATOR+ |
| Dry-run Results | `/v2/dryrun/sql` 등 4종 | OPERATOR+ |

## 흐름 (예: agri PRICE_FACT 새 mapping 추가)

```bash
# 1. Field Mapping 등록 (DRAFT).
curl -X POST /v2/mappings -d '{
  "contract_id": 12,
  "source_path": "items.0.unit_price",
  "target_table": "mart.price_fact",
  "target_column": "unit_price",
  "transform_expr": "number.parse_decimal($items_0_unit_price)",
  "is_required": true
}'
# → mapping_id=99, status=DRAFT.

# 2. Dry-run 으로 sandbox 검증.
curl -X POST /v2/dryrun/field-mapping -d '{
  "domain_code": "agri",
  "contract_id": 12,
  "source_table": "stg.daily_apples",
  "apply_only_published": false
}'
# → row_count + errors.

# 3. APPROVED 결재 후 PUBLISHED.
curl -X POST /v2/checklist/run -d '{...}'
# → all_passed=true 면 publish 가능.
```

## Mart Designer dry-run

```bash
curl -X POST /v2/dryrun/mart-designer -d '{
  "domain_code": "agri",
  "target_table": "agri_mart.daily_avg_price",
  "columns": [
    {"name": "ymd", "type": "TEXT", "nullable": false},
    {"name": "item_code", "type": "TEXT", "nullable": false},
    {"name": "avg_price", "type": "NUMERIC"}
  ],
  "primary_key": ["ymd", "item_code"],
  "save_as_draft": true
}'
# → ddl_text (CREATE TABLE) + draft_id (DRAFT 상태).
```

ALTER 의 경우: 기존 테이블에 *NULL 컬럼 추가* 만 자동. NOT NULL 또는 drop 은 거부.

## DQ Rule preview

```bash
curl -X POST /v2/dq-rules/preview -d '{
  "domain_code": "agri",
  "sql": "SELECT COUNT(*) FROM mart.price_fact WHERE unit_price < 0"
}'
# → is_valid: true, row_count: 0, duration_ms: 12.
```

dangerous keyword (DROP/TRUNCATE) 는 sql_guard 가 즉시 차단.

## 주의

- Mart Designer 가 만든 DRAFT 는 **alembic 자동 적용 X** — ADMIN 이 migration
  파일로 변환 후 `alembic upgrade head`. 자동화는 Phase 6.
- Dry-run 은 *항상 transaction rollback* — mart 의 row 변경 0 보장.
- DQ Rule Builder 의 custom_sql 은 SQL Studio sandbox 와 *같은 sql_guard* 통과.
