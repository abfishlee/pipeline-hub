# 3. 새 도메인 추가 Playbook ★

> **목적**: yaml + migration + seed 만으로 새 도메인 1개를 *코드 수정 0* 으로 추가.
> Phase 5.2.6 STEP 9 의 POS 도메인을 *답습* 모델로 사용 (참조: `domains/pos.yaml`,
> `migrations/versions/0043_pos_mart.py`).
> 4주 초과 시 → 5.2.5 까지의 generic 화 재검토 (PHASE_5_PROMPTS.md 부록 B).

---

## 12 단계 체크리스트

- [ ] **1. domain_code 결정** — 소문자 영문 + 숫자 + 언더스코어, 길이 2~30. (`domain_definition.ck_domain_code_format`)
- [ ] **2. source contract 작성** — `/v2/contracts` 또는 `domain.source_contract` 직접 INSERT
- [ ] **3. sample payload 등록** — `resource_selector_json` 검증용
- [ ] **4. field mapping 작성** — `/v2/mappings` + transform_expr (allowlist 함수만)
- [ ] **5. mart schema/load_policy 설계** — Mart Designer dry-run + load_policy mode
- [ ] **6. DQ rule 작성** — null/range/unique/reference + custom_sql preview
- [ ] **7. provider binding 선택** — OCR/CRAWLER/HTTP_TRANSFORM 도메인별 binding
- [ ] **8. dry-run** — `/v2/dryrun/load-target` + `/v2/dryrun/field-mapping`
- [ ] **9. publish approval** — Mini Publish Checklist (`/v2/checklist/run`) + ADMIN APPROVE
- [ ] **10. backfill** — `/v2/backfill` (1년치라도 chunk + checkpoint)
- [ ] **11. public API scope 등록** — `domain_resource_allowlist` JSONB 에 `{domain}.{resource}` 추가
- [ ] **12. monitoring 확인** — `/v2/perf/slo/summary` + Grafana 대시보드 + alert 채널

---

## 단계별 상세

### 1. domain_code 결정

```sql
-- domain_code 후보 검증.
SELECT domain_code FROM domain.domain_definition
 WHERE domain_code = 'pharma';   -- 비어 있으면 사용 가능.
```

**정책**:
- 사업측 요청 도메인이 우선. 없으면 *기술 검증용 도메인* (POS / IoT / 부동산 등).
- POS = 거래 이벤트 / IoT = 시계열 / 부동산 = 매물. 데이터 모양이 다를수록 추상화
  검증에 유용.

### 2. source contract 작성

```bash
curl -X POST http://localhost:8000/v2/contracts \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": 12,
    "domain_code": "pharma",
    "resource_code": "DRUG_PRICE",
    "schema_version": 1,
    "schema_json": {
      "type": "object",
      "required": ["atc_code", "price_won"],
      "properties": {
        "atc_code": {"type": "string"},
        "price_won": {"type": "number"}
      }
    },
    "compatibility_mode": "backward",
    "resource_selector_json": {
      "endpoint": "/api/drugs/price",
      "payload_type": "drug_price"
    }
  }'
```

`resource_selector_json` 우선순위 = `endpoint` > `payload_type` > `jsonpath`.

### 3. sample payload 등록 + 검증

```bash
curl -X POST http://localhost:8000/v2/contracts/evaluate-selector \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{
    "source_id": 12,
    "payload": {"type":"drug_price","atc_code":"N02BE01","price_won":500},
    "request_endpoint": "/api/drugs/price"
  }'
# 200 → matched=true, contract_id=42, matched_by="endpoint"
```

### 4. field mapping 작성

```bash
curl -X POST http://localhost:8000/v2/mappings \
  -d '{
    "contract_id": 42,
    "source_path": "atc_code",
    "target_table": "pharma_mart.drug_price_fact",
    "target_column": "atc_code",
    "transform_expr": "text.upper(text.trim($atc_code))",
    "is_required": true,
    "order_no": 1
  }'
```

허용 함수 25+종 (POS = `payment_method`):
- text.trim / upper / normalize_unicode_nfc / replace / regex_extract
- number.parse_decimal / round_n / clamp
- date.parse / to_kst
- phone.normalize_kr / address.extract_sido
- json.get_path / hash.sha256 / id.make_content_hash

전체 목록: `app/domain/functions/registry.py` 의 `FUNCTION_REGISTRY`.

### 5. Mart Designer 로 schema 설계

```bash
curl -X POST http://localhost:8000/v2/dryrun/mart-designer \
  -d '{
    "domain_code": "pharma",
    "target_table": "pharma_mart.drug_price_fact",
    "columns": [
      {"name": "atc_code", "type": "TEXT", "nullable": false},
      {"name": "price_won", "type": "NUMERIC"},
      {"name": "ymd", "type": "TEXT", "nullable": false}
    ],
    "primary_key": ["atc_code", "ymd"],
    "save_as_draft": true
  }'
# → DDL 생성 + domain.mart_design_draft DRAFT row.
```

ADMIN 승인 후 alembic migration 으로 변환 (수동 — Phase 6 자동화 backlog).

### 6. DQ rule 작성

```bash
# row_count_min
curl -X POST http://localhost:8000/v2/dq-rules \
  -d '{
    "domain_code": "pharma",
    "target_table": "pharma_mart.drug_price_fact",
    "rule_kind": "row_count_min",
    "rule_json": {"min": 1},
    "severity": "ERROR"
  }'

# custom_sql preview (sandbox 검증).
curl -X POST http://localhost:8000/v2/dq-rules/preview \
  -d '{
    "domain_code": "pharma",
    "sql": "SELECT COUNT(*) FROM pharma_mart.drug_price_fact WHERE price_won < 0"
  }'
# → is_valid: true, row_count: 0
```

### 7. Provider binding 선택

```bash
# 외부 정제 API (HTTP_TRANSFORM) 바인딩.
curl -X POST http://localhost:8000/v2/providers/bindings \
  -d '{
    "source_id": 12,
    "provider_code": "generic_http",
    "priority": 1,
    "config_json": {
      "endpoint": "https://api.pharma-cleansing.example/v1/normalize"
    }
  }'
```

`secret_ref` 는 provider_definition 에 등록 (env 또는 NCP Secret Manager).
circuit breaker default — 5회 연속 5xx → OPEN 60초.

### 8. dry-run

```bash
# field mapping dry-run.
curl -X POST http://localhost:8000/v2/dryrun/field-mapping \
  -d '{
    "domain_code": "pharma",
    "contract_id": 42,
    "source_table": "stg.drug_price_2026_04",
    "apply_only_published": false
  }'

# load-target dry-run.
curl -X POST http://localhost:8000/v2/dryrun/load-target \
  -d '{
    "domain_code": "pharma",
    "source_table": "wf.tmp_run_999_pharma",
    "policy_id": 7
  }'
```

dry-run 은 *항상 transaction rollback*. mart 의 row 0 변경 보장.

### 9. publish approval (Mini Publish Checklist)

```bash
# 1) 작성자: REVIEW 요청.
curl -X POST http://localhost:8000/v2/contracts/42/transition \
  -d '{"to_status":"REVIEW"}'

# 2) ADMIN: checklist 자동 실행.
curl -X POST http://localhost:8000/v2/checklist/run \
  -d '{
    "entity_type": "source_contract",
    "entity_id": 42,
    "current_status": "APPROVED",
    "domain_code": "pharma",
    "target_table": "pharma_mart.drug_price_fact",
    "contract_id": 42
  }'
# → all_passed=true 이어야 publish 버튼 enable.

# 3) ADMIN: APPROVE 결재.
# 4) PUBLISHED 전이.
```

체크리스트 항목: status_chain_valid / approver_signed / dry_run_passed /
dq_rules_present / mapping_complete.

### 10. backfill (1년치)

```bash
curl -X POST http://localhost:8000/v2/backfill \
  -d '{
    "domain_code": "pharma",
    "resource_code": "DRUG_PRICE",
    "target_table": "pharma_mart.drug_price_fact",
    "start_at": "2025-01-01T00:00:00+00:00",
    "end_at":   "2026-01-01T00:00:00+00:00",
    "chunk_unit": "day",
    "chunk_size": 1,
    "max_parallel_runs": 2,
    "batch_size": 5000
  }'
# → total_chunks=365, status=PENDING.

curl -X POST http://localhost:8000/v2/backfill/{job_id}/start
# 진행 상황: GET /v2/backfill/{job_id}/chunks
# 실패 시 chunk 단위 resume 가능.
```

### 11. public API scope 등록

```bash
# api_key 발급 (멀티 도메인).
curl -X POST http://localhost:8000/v1/api-keys \
  -d '{
    "client_name": "pharma-portal",
    "scope": ["products.read", "prices.read"],
    "rate_limit_per_min": 120,
    "domain_resource_allowlist": {
      "pharma": {
        "resources": {
          "DRUG_PRICE": {"atc_codes": ["N02BE01", "M01AE01"]}
        }
      }
    }
  }'

# 외부에서 호출.
curl https://api.example.com/public/v2/pharma/DRUG_PRICE/latest \
  -H "X-API-Key: $RAW_KEY"
```

### 12. monitoring

```bash
# SLO 요약.
curl http://localhost:8000/v2/perf/slo/summary?window_minutes=60

# baseline 측정 트리거.
curl -X POST http://localhost:8000/v2/perf/baseline/measure

# Performance Coach (사용자가 짠 SQL 검사).
curl -X POST http://localhost:8000/v2/perf/coach/analyze \
  -d '{"sql": "SELECT * FROM pharma_mart.drug_price_fact WHERE atc_code = 'N02BE01' LIMIT 100"}'
# → verdict: OK / WARN / BLOCK
```

Grafana 대시보드: `pharma` 도메인 label 자동 추가 (Phase 5.2.8).

---

## 추상화 KPI 측정 (ADR-0019 패턴)

새 도메인 추가가 끝나면 ADR 1건 작성:

```markdown
# ADR-00XX — Phase 5/6 추상화 검증 결과 (<도메인>)

| 지표 | 값 |
|---|---|
| 시작 commit | <hash> |
| 완료 commit | <hash> |
| Calendar 일수 | < N >일 |
| Engineering 시간 | < N >시간 |
| 신규 코드 라인 (app/) | < N > |
| 신규 yaml 라인 | < N > |
| **app/ 코드 수정 라인** | **< 0 이 목표 >** |

평가: ✅ 1~2주 / ⚠ 3주 / ❌ 4주+ (회수 트리거)
```

---

## 자주 막히는 곳

| 증상 | 원인 | 해결 |
|---|---|---|
| `selector` 가 안 매치됨 | endpoint 가 `/`로 끝남 | rstrip("/") 후 비교 — 양쪽 trim |
| `transform_expr` 가 거부됨 | allowlist 외 함수 | `app.domain.functions.registry` 확인 |
| `LOAD_TARGET` 가 schema 거부 | mart 스키마 미존재 | `<domain>_mart` 스키마 migration 먼저 |
| Mini Checklist 의 `mapping_complete` 실패 | required 필드 누락 | source_contract.schema_json.required 확인 |
| backfill 이 1만 chunks 초과 | chunk_size 너무 작음 | chunk_unit=week 또는 chunk_size 증가 |

→ 막히면 ADR-0019 의 *발견된 일반화 부족* 항목 (Phase 6 backlog) 도 참고.
