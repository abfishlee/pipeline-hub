# Phase 6 — Product UX First (Design 자산 + ETL 캔버스 통합)

> 이 문서는 *사용자가 직접 검토하고 수정할 초안* 이다.
> Phase 6 의 main 문서 (기존 `PHASE_6_FIELD_VALIDATION.md` 는 *실증 데이터 시나리오*
> 의 reference 로 유지).

---

## 0. 한 문장

> **"기능 있는 백엔드"** → **"사용자가 직접 설계하는 공용 ETL 제품"**

Phase 5 까지는 backend registry / API / migration / 일부 실행 엔진을 만들었다.
Phase 6 는 그 위에 *사용자 중심 UX* 를 입혀 **개발자 없이 새 데이터 파이프라인을
설계·실행** 할 수 있게 만든다.

---

## 1. 진단 — 사용자 비전 vs 현재 소스 상태

사용자 분석 (2026-04-27) 을 그대로 반영.

### 1.1 사용자가 원한 흐름 (10 단계)

```
[1] API/Source 설정          ← 화면에서 URL/key/params 입력
[2] DQ / 표준화 설계         ← SQL / API / function / 표준코드 선택
[3] Mart 설계                ← columns / keys / partition
[4] INSERT SQL / load policy ← target + key + append/upsert/SCD2
[5] ETL 캔버스에서 박스 연결 ← 위 1~4 자산을 박스로 끌어와 화살표
[6] Dry-run                  ← 실 적재 없이 결과 미리보기
[7] Publish (승인 + 스케줄)  ← ADMIN 결재 후 활성화
[8] 실 데이터 수집/처리      ← 자동 또는 수동 실행
[9] 운영 모니터              ← run history / DQ pass rate / lineage
[10] 회고 + 개선             ← 실패 sample 보고 mapping/DQ 수정
```

### 1.2 현재 소스 상태 매핑 (사용자 분석 표)

| # | 사용자가 원한 것 | 현재 backend | 현재 frontend |
|---|---|---|---|
| 1 | API URL / 인증 / params / response schema | `ctl.data_source` / `domain.source_contract` / `domain.provider_definition` / `domain.source_provider_binding` / `/v2/contracts` / `/v2/providers` | ❌ wizard 부재. 폼만으로 등록 불가 |
| 2 | DQ 직접 설계 / SQL / 외부 API / 표준화 함수 | `domain.dq_rule` / `/v2/dq-rules` / `SQL_ASSET_TRANSFORM` / `HTTP_TRANSFORM` / `FUNCTION_TRANSFORM` / `sql_guard.py` | ❌ DqRuleBuilder 화면 부재 |
| 3 | Mart 컬럼 / 타입 / key / partition | `domain.resource_definition` / `domain.load_policy` / `domain.mart_design_draft` / `/v2/dryrun/mart-designer` / `mart_designer.py` | ❌ MartDesigner 화면 부재 |
| 4 | INSERT SQL or load policy | `domain.load_policy` / `LOAD_TARGET` / `SQL_ASSET_TRANSFORM` / `SQL_INLINE_TRANSFORM` | ❌ LoadPolicyDesigner 화면 부재. SqlAsset Editor 도 v1 SQL Studio 만 있음 |
| 5 | ETL 캔버스 박스 조립 | `wf.workflow_definition` / `nodes_v2/__init__.py` (13종 dispatcher) | 🟡 v1 노드 7종 캔버스만 있음. v2 13종 palette 통합 안 됨 |
| 6 | Dry-run | `/v2/dryrun/sql` / `/load-target` / `/field-mapping` / `/mart-designer` | ❌ DryRunResults 화면 부재 |
| 7 | Publish (승인 + 스케줄) | `ctl.approval_request` / `state_machine.py` / `mini_publish_checklist.py` / `/v2/checklist/run` / `wf.workflow_definition.schedule_cron` | 🟡 v1 SQL Studio approval 만 있음 |
| 8 | 실행 | `pipeline_node_v2_worker.py` / `pipeline_runtime.py` / Dramatiq | ✅ 실행 엔진 OK |
| 9 | 모니터 | `/v2/perf/slo/summary` / `audit.shadow_diff` / `audit.public_api_usage` | 🟡 일부 페이지 있음 (PipelineRunDetail) |
| 10 | 회고 / 실패 sample | `dq.quality_result.failed_sample_json` | ❌ Error Sample Viewer 부재 |

### 1.3 v2 노드 dispatcher 정합성

| 노드 | backend dispatcher | 캔버스 palette | 상태 |
|---|---|---|---|
| MAP_FIELDS | ✅ | ❌ | backend 만 |
| SQL_INLINE_TRANSFORM | ✅ | ❌ | backend 만 |
| SQL_ASSET_TRANSFORM | ✅ | ❌ | backend 만 |
| HTTP_TRANSFORM | ✅ | ❌ | backend 만 |
| FUNCTION_TRANSFORM | ✅ | ❌ | backend 만 |
| LOAD_TARGET | ✅ | ❌ | backend 만 |
| OCR_TRANSFORM | ✅ (Phase 5.1 wave 2) | ❌ | backend 만 |
| CRAWL_FETCH | ✅ (Phase 5.1 wave 2) | ❌ | backend 만 |
| STANDARDIZE | ✅ (Phase 5.1 wave 3 — alias_only/embedding) | ❌ | backend 만 + 일부 보완 필요 |
| SOURCE_DATA | ✅ (v1 wrapper) | ❌ | wrapper. 진정한 *generic source 박스* 는 별도 spec 필요 |
| DEDUP | ✅ (v1 wrapper) | ❌ | OK |
| DQ_CHECK | ✅ (v1 wrapper) | ❌ | OK. 단, dq_rule registry 와 *직접 연결* 은 보완 |
| NOTIFY | ✅ (v1 wrapper) | ❌ | OK |

→ **dispatcher 13/13 OK. 캔버스 palette 0/13** = 사용자 시각에선 *영원히 박스로
끌어올 수 없음*. 이게 핵심 GAP.

### 1.4 GAP 한 줄 요약

> **"backend 13 노드 + 5 자산 모델은 다 있는데, 화면에서 만지고 캔버스로 끌어올
> 도구가 없다."**

---

## 2. 목표 — 제품 UX 우선

### 2.1 비전

```
사용자 시나리오 (3분 내 완료)
─────────────────────────────
1. 운영자 로그인 → "새 파이프라인" 버튼
2. Wizard:
   - "어디서 데이터 받나?" → API URL/key 폼
   - "어떤 검증?"          → DQ rule 추가
   - "어디에 적재?"        → Mart 선택 + load policy
3. 자동 생성된 파이프라인 → 캔버스에서 박스 보임
4. "Dry-run" → 실 적재 없이 미리보기
5. "Publish" → ADMIN 결재 → 활성
6. 매일 자동 실행 + 실패 시 alert
```

→ **개발자 손 X. 사용자 자체 완결.**

### 2.2 9 개 핵심 화면 (사용자 정의)

| # | 화면 | 위치 | 역할 |
|---|---|---|---|
| 1 | **Source/API Designer** | `/sources/designer` | API URL / 인증 / params / sample fetch / response schema 자동 추론 |
| 2 | **Field Mapping Designer** | `/mappings/designer` | raw JSON path → mart column drag&drop + transform 함수 |
| 3 | **Transform Designer** | `/transforms/designer` | SQL Asset / HTTP / Function / OCR / Crawler provider 중 선택 |
| 4 | **DQ Rule Builder** | `/dq-rules/builder` | null/range/unique/reference/custom_sql + severity + 실패 정책 |
| 5 | **Standardization Designer** | `/standardization/designer` | namespace 선택 + alias/trigram/embedding/외부API 방식 |
| 6 | **Mart Designer** | `/marts/designer` | target table / columns / keys / partition / indexes |
| 7 | **Load Policy Designer** | `/load-policies/designer` | append / upsert / SCD2 / snapshot + key columns + conflict |
| 8 | **ETL Canvas (v2)** | `/pipelines/{id}/designer` | 위 1~7 자산을 박스로 끌어와 화살표 연결 |
| 9 | **Dry-run + Publish** | `/runs/{id}/dryrun` `/publish/{entity_id}` | 미리보기 + 승인 + 스케줄 |

### 2.3 acceptance — 화면 별 *최소* 시연 기준

| 화면 | 시연 가능 기준 |
|---|---|
| Source/API Designer | KAMIS 같은 실 API 1건 등록 → "테스트 호출" → 응답 미리보기 |
| Field Mapping Designer | 위 응답에서 1+ 필드 선택 → mart 컬럼 매핑 → preview |
| Transform Designer | SQL Asset 1개 등록 → 자산 카탈로그에서 보임 |
| DQ Rule Builder | row_count_min + 1 custom_sql preview |
| Standardization Designer | pos `payment_method` namespace 선택 + alias 매핑 결과 보임 |
| Mart Designer | 새 컬럼 1개 추가 → DDL 생성 → DRAFT 저장 |
| Load Policy Designer | upsert + key columns 선택 → DRAFT |
| ETL Canvas v2 | SOURCE → MAP → DQ → LOAD 4 박스 + 연결 + 저장 |
| Dry-run + Publish | dry-run row_count 표시 + ADMIN 승인 → PUBLISHED |

### 2.4 backend 보완 (소량)

화면 만들면서 *동시에* 보완:
- `SOURCE_DATA` 노드 — 진정한 generic spec 정의 (`source_contract` 의 endpoint 또는 upload 또는 cron 분기)
- `STANDARDIZE` 노드 — `embedding` 전략 *외부 provider* 호출 정합성 (현재 trigram only)
- `domain.public_api_connector` — Phase 6.0 에서 만든 모델. wizard 와 1:1
- 노드 ↔ 자산 *직접 참조* — 노드 config 에 `dq_rule_id` / `mapping_id` 등 명시

---

## 3. 화면 별 상세 spec

### 3.1 Source/API Designer (`/sources/designer`)

**사용자 시나리오**:
> "KAMIS 도매시장 가격 API 등록하려고 한다. URL / 인증키 파라미터 이름 / params 입력
> → 테스트 버튼 → 응답이 화면에 미리보기 → 저장."

**폼 필드**:

| 필드 | 타입 | 예시 |
|---|---|---|
| API 이름 | text | "KAMIS 도매시장 가격" |
| 도메인 | dropdown (`domain.domain_definition`) | agri |
| 리소스 코드 | text | WHOLESALE_PRICE |
| Endpoint URL | text | `http://www.kamis.or.kr/service/price/xml.do` |
| HTTP method | radio | GET / POST |
| Auth 방식 | dropdown | none / query_param / header / basic / bearer |
| Auth 파라미터 이름 | text (auth=query_param/header 일 때) | `cert_key` |
| Secret 참조 | text (env 이름) | `KAMIS_CERT_KEY` |
| Request headers | JSONB editor | `{"Accept":"application/xml"}` |
| Query 템플릿 | JSONB editor + 템플릿 변수 도움말 | `{"p_action":"daily","p_regday":"{ymd}"}` |
| Body 템플릿 (POST 만) | JSONB editor | `null` |
| Pagination | dropdown + 추가 폼 | none / page_number / offset_limit / cursor |
| Response 형식 | radio | JSON / XML |
| Response 추출 경로 | text | `$.response.body.items.item` |
| Timeout (sec) | number | 15 |
| Retry max | number | 2 |
| Rate limit (per min) | number | 60 |
| 수집 주기 (cron) | text | `0 9 * * *` |

**버튼**:
- **"테스트 호출"** — 1회 호출 → 응답 raw + 추출된 rows preview (3 columns table)
- **"DRAFT 저장"** — 검증만 (호출 X)
- **"검토 요청"** (REVIEW)
- **"발행"** (ADMIN, APPROVED → PUBLISHED)

**의존**:
- backend: `domain.public_api_connector` (이미 0046 migration 으로 만들어짐)
- backend API: `/v2/connectors/public-api` *신설 필요*
- engine: `app/domain/public_api/engine.py` *신설 필요* (방금 작성하다 중단)

**acceptance**:
- [ ] KAMIS sample API 1건 등록 + 테스트 호출 200
- [ ] 응답 XML → JSON 자동 변환 + preview 3건
- [ ] DRAFT 저장 → DB row 1건
- [ ] 같은 도메인의 connector 목록 조회

---

### 3.2 Field Mapping Designer (`/mappings/designer`)

**사용자 시나리오**:
> "방금 등록한 KAMIS connector 의 응답 sample 을 좌측에서 보고, 우측의 mart
> 컬럼들과 drag&drop 으로 연결한다. 필요하면 transform 함수 (text.trim / number.parse_decimal) 적용."

**화면 레이아웃**:

```
┌────────────────────────────────┬────────────────────────────────┐
│ Source 응답 sample (JSONPath)   │ Target columns (mart 또는 stg) │
├────────────────────────────────┼────────────────────────────────┤
│ $.itemname                     │ → item_name_ko (TEXT)          │
│ $.price (string)               │ → unit_price (NUMERIC) 🔧      │
│ $.regday                       │ → observed_date (DATE) 🔧      │
│ $.kindname                     │ (unmapped)                     │
└────────────────────────────────┴────────────────────────────────┘
🔧 = 변환 함수 클릭 → drawer 열림 → text.trim / number.parse_decimal / date.parse 등
```

**의존**:
- backend: `domain.field_mapping` (Phase 5)
- backend: `app.domain.functions.registry` 의 26 함수 (Phase 5.2.2)
- backend API: `/v2/mappings` (Phase 5)
- backend API: `/v2/dryrun/field-mapping` (Phase 5)

**acceptance**:
- [ ] connector 의 sample 응답 (Source/API Designer 의 "테스트 호출" 결과 cache) 좌측 표시
- [ ] target table 컬럼 (Mart Designer 또는 기존 mart) 우측 표시
- [ ] drag&drop 매핑 + transform 함수 선택
- [ ] dry-run 1회 → row_count + 첫 5 rows 표시

---

### 3.3 Transform Designer (`/transforms/designer`)

**사용자 시나리오**:
> "변환 단계에서 어떤 노드를 쓸지 선택. SQL Asset 작성, HTTP API 호출, Function
> registry 함수, OCR/Crawler/AI provider 등 4 가지 중 하나."

**4개 탭**:

1. **SQL Asset** — 좌측 SQL 편집기 + 우측 dry-run preview. `domain.sql_asset` 등록.
2. **HTTP Transform** — 외부 API 호출 (`HTTP_TRANSFORM` 노드). secret_ref + endpoint + request template.
3. **Function** — 26 종 allowlist 함수 골라 *식 만들기* (예: `text.upper(text.trim($name))`). Phase 5 엔 지원 미완 (chain). MVP 는 *단일 호출* 만.
4. **OCR / Crawler / AI Provider** — `domain.provider_definition` 의 등록된 provider 선택.

**의존**:
- `domain.sql_asset` (Phase 5.2.2)
- `app.domain.functions.registry` (Phase 5.2.2)
- `domain.provider_definition` + `source_provider_binding` (Phase 5.2.1.1)

**acceptance**:
- [ ] SQL Asset 1개 등록 + DRAFT
- [ ] HTTP transform connector 1개 등록 (Source/API Designer 와 *공유*)
- [ ] Function 식 dry-run

---

### 3.4 DQ Rule Builder (`/dq-rules/builder`)

**사용자 시나리오**:
> "이 mart 의 검증 규칙을 추가. row_count_min, null_pct_max, unique, reference,
> range, custom_sql 중 하나 선택 → 폼 → preview → 저장."

**폼 (rule_kind 별 다른 sub-form)**:

```
[+ 새 rule]
대상 mart  : agri_mart.kamis_price ▼
종류       : ○ row_count_min  ○ null_pct_max  ○ unique  ○ reference  ○ range  ○ custom_sql
severity   : INFO / WARN / ERROR / BLOCK
timeout_ms : 30000
sample_limit : 10

[종류별 sub-form 동적 표시]
row_count_min:    min = 100
null_pct_max:     column = unit_price, max_pct = 5.0
unique:           columns = [observed_date, item_name_ko]
reference:        column = item_code, ref = mart.item_master.code
range:            column = unit_price, min = 0, max = 10000000
custom_sql:       SQL 편집기 + "preview" 버튼

[저장] [DRAFT 검토 요청]
```

**의존**:
- `domain.dq_rule` (Phase 5)
- `/v2/dq-rules` + `/preview` (Phase 5)

**acceptance**:
- [ ] 6 종 rule 모두 폼 표시 + 저장
- [ ] custom_sql preview (sandbox + sql_guard 통과)
- [ ] mart 별 rule 목록 조회

---

### 3.5 Standardization Designer (`/standardization/designer`)

**사용자 시나리오**:
> "이 컬럼 (예: payment_method) 을 표준코드로 변환. 어떤 namespace 사용? 어떤 방식
> (alias / trigram / embedding / 외부 API)?"

**폼**:

```
대상 namespace : pos / PAYMENT_METHOD ▼
방식           : ○ alias_only  ○ embedding_3stage  ○ external_api  ○ noop
                 (방식별 추가 폼)

alias_only:           [Alias 사전 편집기 — std_code ↔ alias 표]
embedding_3stage:     trigram_threshold = 0.7, embedding_threshold = 0.85
external_api:         provider 선택 (`domain.provider_definition` 중 AI_TRANSFORM)
noop:                 (raw 그대로 보존)

[테스트] — 입력값 1개 → 결과 std_code 표시
[저장]
```

**의존**:
- `domain.standard_code_namespace` (Phase 5.2.1)
- `app.domain.standardization_registry` (Phase 5.1 wave 3)
- `app.domain.std_alias` (Phase 5.2.6 STEP 9)

**acceptance**:
- [ ] pos / PAYMENT_METHOD 선택 → alias_only 강제 표시 + 사전 보임
- [ ] 테스트 입력 "카드" → "CARD" 반환
- [ ] embedding_3stage 선택 시 임계 폼 표시 (실 embedding 호출은 외부 API 키 있어야)

---

### 3.6 Mart Designer (`/marts/designer`)

**사용자 시나리오**:
> "최종 mart 테이블 설계. 컬럼 / 타입 / primary key / partition / index → DDL
> 자동 생성 → diff 미리보기 → DRAFT."

**폼**:

```
도메인        : agri ▼
target table  : agri_mart.kamis_price
설명          : KAMIS 도매시장 가격 fact

컬럼:
+ ymd            TEXT      NOT NULL
+ item_code      TEXT      NOT NULL
+ market_code    TEXT      NOT NULL
+ unit_price     NUMERIC
+ observed_at    TIMESTAMPTZ
+ raw_response   JSONB

PRIMARY KEY: [ymd, item_code, market_code]
PARTITION BY: ymd

인덱스:
+ idx_kamis_market_date (market_code, ymd)

[DDL 생성] → 텍스트 미리보기 + diff
[DRAFT 저장]
```

**의존**:
- `domain.mart_design_draft` (Phase 5.2.4)
- `mart_designer.py` (Phase 5.2.4)
- `/v2/dryrun/mart-designer` (Phase 5)

**acceptance**:
- [ ] CREATE 케이스 — 새 테이블 DDL
- [ ] ALTER 케이스 — 기존 테이블에 NULL 컬럼 추가 DDL
- [ ] DRAFT 저장 → `domain.mart_design_draft` row 1건

---

### 3.7 Load Policy Designer (`/load-policies/designer`)

**사용자 시나리오**:
> "방금 만든 mart 에 어떻게 적재할지 정책 설정. append-only / upsert / SCD2 /
> snapshot 중 선택 + key columns."

**폼**:

```
resource     : agri / WHOLESALE_PRICE ▼
target table : agri_mart.kamis_price (resource_definition.fact_table 자동)

mode: ○ append_only  ○ upsert  ○ scd_type_2 (Phase 7+)  ○ current_snapshot (Phase 7+)

key_columns (mode != append_only): [ymd, item_code, market_code]
update_columns (upsert): [unit_price, observed_at] (또는 자동 = 공통 - key)
partition_expr: ymd
chunk_size: 1000
statement_timeout_ms: 60000

[저장 — DRAFT]
```

**의존**:
- `domain.load_policy` (Phase 5)
- `LOAD_TARGET` 노드 (Phase 5.2.2)

**acceptance**:
- [ ] append_only / upsert 2 mode 폼 + 저장
- [ ] SCD2 / snapshot 선택 시 *"Phase 7 예정"* 안내 표시
- [ ] dry-run (rows_affected 추정)

---

### 3.8 ETL Canvas v2 (`/pipelines/{id}/designer` — 기존 페이지 갱신)

**사용자 시나리오**:
> "위에서 등록한 자산들을 박스로 끌어와 연결. 캔버스 좌측에 v2 노드 13종 palette,
> 박스 클릭하면 우측 drawer 에 *어떤 자산을 사용할지* 선택."

**좌측 palette (v2 노드 13종)**:

```
DATA SOURCES
  📦 SOURCE_DATA          (raw 또는 polling source)
  📦 PUBLIC_API_FETCH     (등록된 connector 1건 호출)
  📦 OCR_TRANSFORM
  📦 CRAWL_FETCH

TRANSFORM
  📦 MAP_FIELDS           (field_mapping 사용)
  📦 SQL_INLINE_TRANSFORM (즉석 SQL)
  📦 SQL_ASSET_TRANSFORM  (등록된 sql_asset 사용)
  📦 HTTP_TRANSFORM       (외부 API 호출)
  📦 FUNCTION_TRANSFORM   (allowlist 함수 적용)
  📦 STANDARDIZE          (namespace 표준화)

VALIDATE
  📦 DEDUP
  📦 DQ_CHECK             (등록된 dq_rule 사용)

LOAD / OUTPUT
  📦 LOAD_TARGET          (load_policy 사용)
  📦 NOTIFY
```

**박스 클릭 → 우측 drawer**:

```
박스 종류 : MAP_FIELDS

이 박스가 사용할 자산:
  field_mapping : [ ... 등록된 mapping 중 dropdown ... ▼]
                  (없으면 "+ 새 mapping 만들기" 버튼 → /mappings/designer 로 이동)

입력 (upstream 박스의 출력) :
  source_table : (자동 — 이전 박스의 output_table 변수)

출력 :
  target_table : (자동 — wf.tmp_run_<run_id>_<node_key>)

[저장]
```

**의존**:
- `wf.workflow_definition` / `wf.node_definition` / `wf.edge_definition` (Phase 3)
- `nodes_v2/__init__.py` 의 13종 dispatcher (Phase 5)
- 모든 자산 모델 (mapping / dq_rule / load_policy / sql_asset / connector)

**acceptance**:
- [ ] 13 종 palette 표시 + 카테고리 분류
- [ ] 박스 drag → 캔버스 추가
- [ ] 화살표 연결 + 사이클 검증
- [ ] 박스 클릭 → drawer + 자산 dropdown
- [ ] 저장 → `wf.node_definition.config_json` 에 자산 ID 저장
- [ ] *최소 1 종* (예: SOURCE_DATA → MAP_FIELDS → DQ_CHECK → LOAD_TARGET) 4 박스 e2e 실행

---

### 3.9 Dry-run Results (`/runs/{run_id}/dryrun`)

**사용자 시나리오**:
> "캔버스에서 'Dry-run' 클릭 → 각 박스가 *실 mart 변경 없이* 실행 → 결과 페이지에서
> 박스별 row_count, DQ pass/fail, 적재 예상 rows, 실패 sample 확인."

**구성**:
- 박스 트리 + 각 박스의 status (success/failed/skipped)
- 박스 클릭 시 우측 panel:
  - 입력 sample 5 rows
  - 출력 sample 5 rows
  - row_count
  - duration_ms
  - 실패 시 error_message + DQ failed_sample_json

**의존**:
- `/v2/dryrun/*` (Phase 5)
- `dq.quality_result.failed_sample_json` (Phase 4)

**acceptance**:
- [ ] 4 박스 e2e dry-run → 모든 박스 success 표시
- [ ] DQ 실패 시 sample 5건 노출
- [ ] mart row_count 변화 0 검증

---

### 3.10 Publish Approval (`/publish/{entity_id}`)

**사용자 시나리오**:
> "Publish 버튼 → Mini Checklist 자동 실행 → all_passed 일 때 ADMIN 승인 →
> PUBLISHED → 스케줄 자동 실행 시작."

**구성**:
- 7 항목 checklist 결과 (PASS/FAIL)
- ADMIN 승인 버튼 (all_passed 일 때만 enable)
- 스케줄 cron 표시
- 발행 후 첫 실행 시각 표시

**의존**:
- `/v2/checklist/run` (Phase 5)
- `ctl.approval_request` (Phase 5)
- `wf.pipeline_release` (Phase 3)

**acceptance**:
- [ ] checklist 7 항목 표시
- [ ] ADMIN 승인 → PUBLISHED 전이
- [ ] schedule_cron 입력 → 다음 실행 시각 미리보기

---

## 4. v2 노드 dispatcher ↔ canvas palette 매트릭스

| 노드 | dispatcher | palette 카테고리 | 자산 dropdown 의 source | acceptance 시연 시나리오 |
|---|---|---|---|---|
| SOURCE_DATA | ✅ (v1 wrap) | DATA SOURCES | `ctl.data_source` 또는 `domain.source_contract` | raw 행 가져오기 |
| **PUBLIC_API_FETCH** ★ | 🟡 신설 필요 (Phase 6.0 backend 일부 됨) | DATA SOURCES | `domain.public_api_connector` | KAMIS 1회 호출 |
| OCR_TRANSFORM | ✅ | DATA SOURCES | `domain.source_provider_binding` (kind=OCR) | OCR provider 선택 |
| CRAWL_FETCH | ✅ | DATA SOURCES | `domain.source_provider_binding` (kind=CRAWLER) | crawler 선택 |
| MAP_FIELDS | ✅ | TRANSFORM | `domain.field_mapping` | mapping 적용 |
| SQL_INLINE_TRANSFORM | ✅ | TRANSFORM | inline SQL 입력 | sandbox SQL |
| SQL_ASSET_TRANSFORM | ✅ | TRANSFORM | `domain.sql_asset` (PUBLISHED) | 등록 SQL 실행 |
| HTTP_TRANSFORM | ✅ | TRANSFORM | `domain.public_api_connector` 또는 inline | 외부 정제 API |
| FUNCTION_TRANSFORM | ✅ | TRANSFORM | `expressions` dict (function registry) | row 단위 함수 |
| STANDARDIZE | ✅ | TRANSFORM | `domain.standard_code_namespace` | 표준코드 매칭 |
| DEDUP | ✅ | VALIDATE | `key_columns` config | 중복 제거 |
| DQ_CHECK | ✅ | VALIDATE | `domain.dq_rule` | rule 적용 |
| LOAD_TARGET | ✅ | LOAD | `domain.load_policy` | mart 적재 |
| NOTIFY | ✅ | LOAD | inline (channel/target/body) | Slack/Email |

→ **PUBLIC_API_FETCH 신설** 이 유일한 backend 추가. 나머지는 frontend palette + drawer + 자산 dropdown 통합만.

---

## 5. Wave 별 작업 순서 (8 weeks)

### Wave 1 — Source/API Designer + Field Mapping (W1~W2)
- [ ] backend: `app/domain/public_api/engine.py` 마무리 (방금 작성하다 중단)
- [ ] backend: `app/api/v2/connectors.py` (CRUD + test + dry-run)
- [ ] backend: `PUBLIC_API_FETCH` 노드 (`nodes_v2/public_api_fetch.py`) + dispatcher 등록
- [ ] frontend: `pages/v2/SourceApiDesigner.tsx` + `api/v2/connectors.ts`
- [ ] frontend: `pages/v2/FieldMappingDesigner.tsx` + `api/v2/mappings.ts`
- [ ] tests: backend engine + frontend basic render
- [ ] **시연**: KAMIS API 1건 등록 → 테스트 호출 200 → mapping drag&drop

### Wave 2 — DQ + Standardization + Transform (W2~W3)
- [ ] frontend: `pages/v2/DqRuleBuilder.tsx` (6 종 rule_kind sub-form)
- [ ] frontend: `pages/v2/StandardizationDesigner.tsx`
- [ ] frontend: `pages/v2/TransformDesigner.tsx` (SQL/HTTP/Function/Provider 4 탭)
- [ ] backend 보완: STANDARDIZE 노드의 external_api strategy
- [ ] **시연**: pos PAYMENT_METHOD alias 등록 → "카드" 입력 → "CARD" 표시

### Wave 3 — Mart + Load Policy (W3~W4)
- [ ] frontend: `pages/v2/MartDesigner.tsx`
- [ ] frontend: `pages/v2/LoadPolicyDesigner.tsx`
- [ ] backend: load_policy 의 conflict_policy 컬럼 (아직 미존재)
- [ ] **시연**: KAMIS mart 신설 → upsert policy → DDL 생성 + DRAFT

### Wave 4 — ETL Canvas v2 통합 (W4~W5) ★ 가장 큰 PR
- [ ] frontend: `PipelineDesigner.tsx` 의 좌측 palette 갱신 — 13 종 카테고리 분류
- [ ] frontend: 박스 클릭 → 우측 drawer + 자산 dropdown
- [ ] frontend: 자산 dropdown 의 *"+ 새 자산 만들기"* 버튼 → 각 designer 로 이동
- [ ] backend: `wf.node_definition.config_json` 에 자산 ID 저장 검증 (sql_guard 갱신)
- [ ] **시연**: SOURCE_DATA → MAP_FIELDS → DQ_CHECK → LOAD_TARGET 4 박스 캔버스 + 저장

### Wave 5 — Dry-run + Publish (W5~W6)
- [ ] frontend: `pages/v2/DryRunResults.tsx` (박스 트리 + 좌측 row sample)
- [ ] frontend: `pages/v2/PublishApproval.tsx` (Mini Checklist 결과)
- [ ] frontend: 캔버스의 "Dry-run" + "Publish" 버튼 → 위 페이지 이동
- [ ] **시연**: 4 박스 dry-run → 결과 트리 → 승인 → PUBLISHED

### Wave 6 — 실증 (KAMIS) e2e (W6~W7)
- [ ] domains/agri.yaml 에 KAMIS WHOLESALE_PRICE resource 추가
- [ ] migration: `agri_mart.kamis_price` 테이블 (사용자가 Mart Designer 로 직접 만들면 자동)
- [ ] 캔버스에서 PUBLIC_API_FETCH(KAMIS) → MAP_FIELDS → DQ → LOAD_TARGET 조립
- [ ] PUBLISHED → cron 매일 9시 → 1주일 자동 polling
- [ ] mart 데이터 1주분 적재 검증
- [ ] **시연**: 사장님께 *코딩 0줄로 새 데이터 파이프라인 만든 결과* 시연

### Wave 7 — 운영팀 onboarding + 회고 (W7~W8)
- [ ] docs/onboarding/03_domain_playbook.md 갱신 — 캔버스 박스 시나리오로 재작성
- [ ] 운영팀 합류 (2026-09-01 ± 2주) — 새 운영자가 docs 만 보고 KAMIS 같은 API 1건 추가
- [ ] ADR-0021 — Phase 6 product UX 회고 + Phase 7 backlog
- [ ] PHASE_7_*.md 신설 검토

---

## 6. 사용자 시나리오 — *KAMIS 1건 e2e* (Wave 6 의 acceptance)

운영자가 사용자 매뉴얼 *없이* 다음을 수행:

```
[2분] 1. 로그인 → "+ 새 데이터 소스"
        ─→ Source/API Designer 폼:
           이름: KAMIS 도매시장 가격
           URL: http://www.kamis.or.kr/service/price/xml.do
           Auth: query_param / cert_key / KAMIS_CERT_KEY
           Query: {"p_action":"daily","p_regday":"{ymd}"}
           Response: XML / $.response.body.items.item
           Schedule: 0 9 * * *
        ─→ "테스트 호출" → 응답 미리보기 OK
        ─→ "저장" → DRAFT

[3분] 2. "+ 새 mart" → Mart Designer 폼:
           target: agri_mart.kamis_price
           컬럼: ymd, item_name, market_name, unit_price ...
        ─→ "DDL 생성" → 미리보기 OK → "DRAFT 저장"
        ─→ "+ 새 load policy" → upsert + key=[ymd,item,market]

[2분] 3. "+ 새 mapping" → Field Mapping Designer:
           좌측: KAMIS 응답 sample
           우측: agri_mart.kamis_price 컬럼
           drag&drop:  $.itemname → item_name
                       $.price    → unit_price (number.parse_decimal)
                       $.regday   → ymd

[1분] 4. "+ 새 DQ rule" → DQ Rule Builder:
           대상: agri_mart.kamis_price
           rule: row_count_min, min=1
           rule: range, column=unit_price, min=0

[3분] 5. "+ 새 파이프라인" → ETL Canvas:
           좌측 palette → PUBLIC_API_FETCH 박스 끌기 → KAMIS 선택
           → MAP_FIELDS 박스 끌기 → 위 mapping 선택
           → DQ_CHECK 박스 → 위 rule 선택
           → LOAD_TARGET 박스 → 위 load policy 선택
           화살표 연결 → "Save"

[1분] 6. "Dry-run" → 결과 트리 → 모든 박스 success → row_count 12

[1분] 7. "Publish" → Mini Checklist 7개 → all_passed → ADMIN 승인 → PUBLISHED

총 13분. 코딩 0줄.
```

→ 이게 Phase 6 의 핵심 *acceptance*. 13분 안에 새 운영자가 새 API 파이프라인을
*완성* 할 수 있어야 한다.

---

## 7. 위험 + 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| frontend 8 page 가 너무 큼 | 일정 지연 | wave 별 분할. wave 1 만이라도 시연 가능. |
| 기존 Designer 와 v2 palette 충돌 | 회귀 | v1 palette 는 그대로, *별도 page* `/pipelines/{id}/designer-v2` 로 분기 검토 |
| 자산 dropdown 의 *없으면 만들기* 흐름 복잡 | UX 혼란 | "+" 버튼 → modal 안에 mini designer (전체 page 이동 X) |
| 사용자가 자산 *수정* 하면 기존 파이프라인 영향 | 무결성 | 자산 versioning (Phase 7) 또는 *DRAFT 단계만 수정 허용* |
| Mart Designer DDL 자동 적용 위험 | 데이터 손실 | DRAFT → REVIEW → ADMIN 승인 후 *수동 alembic 생성* (현재 정책) |
| KAMIS 같은 외부 API 변동 | pipeline 실패 | source_contract.compatibility_mode + alert |
| 운영팀 합류 전 시연 필요 | 시점 불일치 | wave 6 까지 사장님/Product Owner 에게 시연 |

---

## 8. 산출물

### 신규 코드
- `backend/app/domain/public_api/engine.py` (Wave 1)
- `backend/app/api/v2/connectors.py` (Wave 1)
- `backend/app/domain/nodes_v2/public_api_fetch.py` (Wave 1)
- `frontend/src/pages/v2/SourceApiDesigner.tsx` (Wave 1)
- `frontend/src/pages/v2/FieldMappingDesigner.tsx` (Wave 1)
- `frontend/src/pages/v2/TransformDesigner.tsx` (Wave 2)
- `frontend/src/pages/v2/DqRuleBuilder.tsx` (Wave 2)
- `frontend/src/pages/v2/StandardizationDesigner.tsx` (Wave 2)
- `frontend/src/pages/v2/MartDesigner.tsx` (Wave 3)
- `frontend/src/pages/v2/LoadPolicyDesigner.tsx` (Wave 3)
- `frontend/src/pages/v2/EtlCanvasV2.tsx` 또는 기존 `PipelineDesigner.tsx` 갱신 (Wave 4)
- `frontend/src/pages/v2/DryRunResults.tsx` (Wave 5)
- `frontend/src/pages/v2/PublishApproval.tsx` (Wave 5)
- `frontend/src/api/v2/*.ts` (각 wave 와 함께)

### 신규 migration (예상)
- (Wave 1 이전) `0046_public_api_connector.py` ✅ 이미 적용됨
- (Wave 3) `0047_load_policy_conflict_policy.py` (선택)

### 신규 ADR
- ADR-0021 — Phase 6 Product UX 회고 (Wave 7)

### 신규 docs
- `docs/onboarding/03_domain_playbook.md` 갱신 (Wave 7)
- `docs/phases/CURRENT.md` Phase 6 진입 + Wave 진행 상황

---

## 9. Phase 7 후보 (이 모든 게 끝난 후)

| 후보 | 내용 |
|---|---|
| **자산 versioning** | mapping/dq_rule/sql_asset 의 N 버전 보존 + 파이프라인이 특정 버전 pinning |
| **Lineage Viewer** | source → contract → mapping → mart row 까지 lineage 시각화 |
| **Backfill Wizard** | STEP 11 backend (chunk + checkpoint) 위에 UI |
| **Performance Coach UI** | EXPLAIN 결과 시각화 + 인덱스 추천 |
| **Multi-tenant** | 조직 별 isolated 자산 + 권한 |
| **AI-assisted Mapping** | sample 응답 보고 LLM 이 mapping 초안 제안 |
| **CDC + Kafka** | ADR-0020 트리거 충족 시 |

---

## 10. 참조 — 기존 ADR + docs

- [ADR-0017](../adr/0017-resource-registry-orm-strategy.md) — Hybrid ORM 전략
- [ADR-0018](../adr/0018-phase5-v2-generic-retrospective.md) — Phase 5 회고
- [ADR-0019](../adr/0019-phase5-abstraction-validation-pos.md) — POS 추상화 검증
- [ADR-0020](../adr/0020-kafka-introduction-triggers.md) — Kafka 트리거
- [PHASE_5_GENERIC_PLATFORM.md](./PHASE_5_GENERIC_PLATFORM.md)
- [PHASE_5_1_HARDENING.md](./PHASE_5_1_HARDENING.md)
- [PHASE_5_1_TEST_REPORT.md](./PHASE_5_1_TEST_REPORT.md)
- [PHASE_6_FIELD_VALIDATION.md](./PHASE_6_FIELD_VALIDATION.md) — *실증 데이터 시나리오 reference*
- [docs/onboarding/03_domain_playbook.md](../onboarding/03_domain_playbook.md)

---

## 11. 검토 포인트 (사용자 ★)

다음 항목을 사용자가 검토 + 결정 필요:

1. **9 화면 모두 필요한가?** — 일부 합칠 수 있는가? (예: Mart + Load Policy 한 화면)
2. **Wave 순서가 맞는가?** — Source/API 부터 vs ETL Canvas 부터?
3. **PUBLIC_API_FETCH 노드를 새로 만들 것인가, SOURCE_DATA 안에서 분기할 것인가?**
4. **자산 *수정* 정책** — DRAFT 만 수정? 아니면 PUBLISHED 도 새 버전 생성?
5. **dropdown vs modal vs 새 페이지** — 자산 만들기 흐름 UX 결정
6. **8 weeks 일정 현실적인가?** — frontend 8 page = 1 page/주 평균. 가능?
7. **Wave 6 의 KAMIS 시연 시점** — 운영팀 합류 전? 후?
8. **ADR-0021 의 핵심 항목** — 어떤 KPI 로 *제품화 성공* 을 평가?

---

## 12. 다음 액션

이 문서를 사용자가 검토하고:
- 위 11 항목 중 *수정 또는 합의* 사항 결정
- Wave 1 부터 진행 동의
- 그 후 *PHASE_6_PRODUCT_UX_PROMPTS.md* 작성 (Phase 5 STEP 프롬프트 패턴)

→ 검토 완료 후 commit + push.
→ Wave 1 부터 STEP 단위 실행.

---

## 13. 검토 결정안 — 제품 실증 MVP 보정

작성일: 2026-04-26

이 문서는 *구현 목록* 은 충분히 구체적이다. 다만 고객 시연 가능한 제품으로 만들려면
9개 화면을 모두 독립 페이지로 만들기보다, 사용자의 실제 작업 순서에 맞춘 **6개
workbench** 로 묶어야 한다. Phase 6 의 목표는 "기능이 많다" 가 아니라, 운영자가
KAMIS OpenAPI 를 등록해서 raw 수집 → 매핑 → 품질검사/표준화 → 마트 적재 → dry-run →
publish 까지 **코드 수정 없이 한 번에 시연** 하는 것이다.

### 13.1 9개 화면 정책 — 기능은 유지, 화면은 6개로 통합

| 기존 기능 | Phase 6 MVP 화면 | 결정 |
|---|---|---|
| Source/API Designer | Source Workbench | 독립 유지. OpenAPI 연결, 테스트 호출, sample 저장의 시작점 |
| Field Mapping Designer | Mapping Workbench | 독립 유지. raw JSONPath → staging/mart field 연결 |
| Transform Designer | Mapping/Quality Workbench 안의 탭 | 별도 페이지로 빼지 말고 SQL/API/FUNCTION 선택 탭으로 통합 |
| DQ Rule Builder | Quality Workbench | 표준화와 함께 배치. "데이터를 믿을 수 있게 만드는 구간" |
| Standardization Designer | Quality Workbench | DQ 와 같은 화면의 Standardization 탭 |
| Mart Designer | Mart Workbench | Load Policy 와 통합 |
| Load Policy Designer | Mart Workbench | mart table, key, partition, upsert 정책을 한 번에 설계 |
| ETL Canvas | ETL Canvas v2 | 독립 유지. 이미 만든 자산을 박스로 연결 |
| Dry-run + Publish | Run & Publish Workbench | dry-run, diff, checklist, 승인 버튼 통합 |

결론: **9개 기능은 모두 필요하지만, 9개 독립 화면은 과하다.** MVP 는 6개
workbench 로 만든다. Lineage, Backfill Wizard, Performance Coach, Template Gallery,
AI-assisted Mapping 은 Phase 6 후반 또는 Phase 7 backlog 로 둔다.

### 13.2 Wave 순서 보정

기존 Wave 순서는 대체로 맞다. 단, Wave 4 의 Canvas 를 만들기 전에 KAMIS 를 실제로
한 번 통과시키는 **Wave 3.5 vertical slice** 를 추가한다.

| Wave | 결정 |
|---|---|
| Wave 1 | Source Workbench + Mapping Workbench 먼저. API 연결과 sample payload 확보가 최우선 |
| Wave 2 | Quality Workbench. DQ/표준화/Transform 을 최소 기능으로 연결 |
| Wave 3 | Mart Workbench. mart schema + load_policy 를 한 화면에서 설계 |
| Wave 3.5 | KAMIS vertical slice. Canvas 없이 backend/dry-run 으로 end-to-end 1회 검증 |
| Wave 4 | ETL Canvas v2. 검증된 자산을 박스로 연결하는 UX 구현 |
| Wave 5 | Run & Publish. dry-run 결과, 영향도, 승인 흐름 구현 |
| Wave 6 | KAMIS 고객 시연용 e2e |
| Wave 7 | 운영팀 onboarding + ADR-0021 회고 |

### 13.3 PUBLIC_API_FETCH 정책

UX 에서는 **PUBLIC_API_FETCH 를 별도 노드로 노출** 한다. 사용자는 SOURCE_DATA 라는
추상 이름보다 "공공 OpenAPI 호출" 박스를 더 쉽게 이해한다.

구현 내부에서는 SOURCE_DATA 계열의 공통 인터페이스를 재사용한다.

```text
Canvas 노드: PUBLIC_API_FETCH
      ↓
내부 source kind: PUBLIC_API
      ↓
공통 출력: raw_object_id / sample_payload / output_table / source_id
      ↓
다음 노드: MAP_FIELDS
```

즉, **화면 언어는 구체적으로, 내부 엔진은 generic 하게** 간다.

### 13.4 자산 수정 정책

| 상태 | 수정 정책 |
|---|---|
| DRAFT | 자유 수정 가능 |
| REVIEW | 수정 시 DRAFT 로 되돌림 |
| APPROVED | 직접 수정 금지. 새 version 생성 |
| PUBLISHED | 직접 수정 금지. 새 version 생성 후 shadow/dry-run/publish |

파이프라인은 항상 `mapping_version_id`, `dq_rule_version_id`, `sql_asset_version_id`,
`load_policy_version_id` 처럼 **특정 버전을 pinning** 한다. 그래야 운영 중인
workflow 가 뒤에서 바뀌지 않는다.

### 13.5 자산 만들기 UX

ETL Canvas 에서는 노드 설정 drawer 안에 dropdown 을 둔다.

- 기존 자산 선택: dropdown
- 간단한 자산 생성: modal
  - simple DQ rule
  - timeout/retry
  - 작은 load option
- 복잡한 자산 생성: 새 workbench 로 이동
  - OpenAPI connector
  - field mapping
  - mart schema
  - SQL asset
  - 표준화 namespace

새 workbench 에서 저장하면 다시 Canvas drawer 로 돌아와 방금 만든 자산이 선택된 상태가
되어야 한다. 이것이 "설계 화면" 과 "조립 화면" 을 자연스럽게 연결한다.

### 13.6 8주 일정 현실성

8주는 **MVP 기준으로만 현실적** 이다.

포함:
- 6개 workbench
- KAMIS OpenAPI 1개 e2e
- PUBLIC_API_FETCH + MAP_FIELDS + DQ + STANDARDIZE + LOAD_TARGET
- dry-run rollback
- publish approval
- 최소 운영 매뉴얼

제외 또는 후순위:
- 9개 화면 완전 독립 고도화
- Lineage Viewer
- Backfill Wizard UI
- SQL Performance Coach UI
- AI-assisted Mapping
- Template Gallery
- SCD2 고급 편집 UI
- Kafka/CDC 실시간 연동

위 제외 항목까지 포함하면 10~12주 이상으로 보는 것이 안전하다.

### 13.7 KAMIS 시연 시점

KAMIS 시연은 두 번으로 나눈다.

| 시점 | 목적 |
|---|---|
| Wave 3.5, 운영팀 합류 전 | 내부 검증. "우리 설계가 실제 OpenAPI 를 끝까지 태울 수 있나" 확인 |
| Wave 6, 운영팀 합류 전/직전 | 고객/사장님 시연. 화면 중심 e2e |
| Wave 7, 운영팀 합류 후 | 운영 인수인계 리허설. 운영자가 문서만 보고 재현 |

따라서 고객 시연은 운영팀 합류를 기다리지 않는다. 운영팀 합류 후에는 "사용법 검증" 을
한다.

### 13.8 ADR-0021 KPI

ADR-0021 은 Phase 6 의 성공을 다음 KPI 로 평가한다.

| KPI | 목표 |
|---|---|
| Zero-code connector | KAMIS 수집 파이프라인 생성 중 backend 코드 수정 0 |
| Time to first dry-run | 새 OpenAPI 등록 후 30분 이내 dry-run 성공 |
| Time to first publish | 새 OpenAPI 등록 후 60분 이내 publish 후보 생성 |
| Demo duration | 고객 시연 flow 15분 이내 |
| KAMIS run success | 1주 scheduled run 성공률 95% 이상 |
| Dry-run accuracy | dry-run 예상 row_count 와 실제 적재 row_count 오차 1% 이하 |
| DQ explainability | 실패 row sample 과 실패 rule 이 화면에서 확인 가능 |
| v1 regression | v1 endpoint / v1 workflow 회귀 0 |
| Operator reproducibility | 운영자가 onboarding 문서만 보고 유사 API 1개 추가 가능 |

### 13.9 Phase 6 완료 판정

Phase 6 은 다음이 모두 충족되면 완료로 본다.

1. KAMIS OpenAPI connector 를 화면에서 등록한다.
2. sample payload 를 받아 field mapping 을 만든다.
3. DQ rule 과 표준화 rule 을 화면에서 붙인다.
4. mart table 과 load policy 를 화면에서 설계한다.
5. ETL Canvas 에서 노드를 연결한다.
6. dry-run 으로 row_count / DQ 결과 / 적재 영향도를 확인한다.
7. publish 승인 후 스케줄 실행한다.
8. mart 에 데이터가 적재되고 public/internal API 에서 조회된다.
9. 같은 과정을 문서만 보고 운영자가 재현한다.
