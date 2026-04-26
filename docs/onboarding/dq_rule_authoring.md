# DQ Rule 작성 가이드

## 6 종 rule_kind

| kind | 설명 | rule_json 예시 |
|---|---|---|
| `row_count_min` | 최소 row 수 | `{"min": 100}` |
| `null_pct_max` | 컬럼 null 비율 상한 | `{"column": "price", "max_pct": 5.0}` |
| `unique_columns` | 컬럼 조합 unique 보장 | `{"columns": ["ymd", "item_code"]}` |
| `reference` | FK 참조 무결성 | `{"column": "item_code", "ref_table": "mart.item_master", "ref_column": "code"}` |
| `range` | 값 범위 | `{"column": "price", "min": 0, "max": 10000000}` |
| `custom_sql` | 임의 SELECT (SQL Studio sandbox 와 동일 가드) | `{"sql": "SELECT COUNT(*) FROM ... WHERE ..."}` |

## severity 4 단계

| severity | 동작 |
|---|---|
| INFO | 통과 여부만 기록. 파이프라인은 진행. |
| WARN | 알림. 파이프라인 진행. |
| ERROR | 노드 FAILED. downstream SKIPPED. |
| BLOCK | publish 거부 (PUBLISHED 전이 차단). |

## 작성 흐름 (custom_sql 예)

```bash
# 1. preview (sandbox 검증).
curl -X POST /v2/dq-rules/preview -d '{
  "domain_code": "agri",
  "sql": "SELECT COUNT(*) FROM mart.price_fact WHERE unit_price < 0"
}'
# → is_valid: true, row_count: 0, duration_ms: 12

# 2. DRAFT 등록.
curl -X POST /v2/dq-rules -d '{
  "domain_code": "agri",
  "target_table": "mart.price_fact",
  "rule_kind": "custom_sql",
  "rule_json": {"sql": "SELECT COUNT(*) FROM mart.price_fact WHERE unit_price < 0"},
  "severity": "ERROR",
  "timeout_ms": 5000,
  "sample_limit": 10,
  "max_scan_rows": 1000000,
  "incremental_only": true
}'

# 3. APPROVED 결재 후 PUBLISHED → DQ_CHECK 노드가 자동 실행.
```

## 가드레일 (Phase 5.2.0)

- **차단 키워드**: DROP / DELETE / TRUNCATE / ALTER / GRANT / REVOKE / COPY...PROGRAM
- **timeout_ms**: 100~600_000 (default 30_000).
- **sample_limit**: 1~10_000 (default 10) — 실패 row 보고용.
- **max_scan_rows**: 옵션 — 초과 시 SKIP (대형 테이블 보호).
- **incremental_only**: TRUE 면 마지막 watermark 이후만 검사.

## custom_sql 모범 사례

```sql
-- ❌ 나쁨: 전체 스캔
SELECT * FROM mart.price_fact WHERE unit_price IS NULL

-- ✅ 좋음: COUNT + 인덱스 컬럼 활용
SELECT COUNT(*) FROM mart.price_fact
 WHERE ymd >= current_date - interval '7 days'
   AND unit_price IS NULL

-- ✅ 좋음: EXPLAIN COST 낮음 (Performance Coach 통과)
SELECT COUNT(*) FROM mart.daily_avg_price
 WHERE avg_price < 0
```

Performance Coach (`/v2/perf/coach/analyze`) 로 작성 SQL 의 verdict 확인 권장.
