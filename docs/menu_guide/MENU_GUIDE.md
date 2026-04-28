# V3 핵심 메뉴 / 업무 절차 가이드

**시스템:** 공용 데이터 수집 파이프라인 플랫폼 (도메인 무관)
**최종 갱신:** 2026-04-28 (V3 Practical Platform)
**대상 독자:** 운영자 / 개발자 / 시연 참관자

---

## 0. V3 메뉴 정리 원칙

V3 는 “가능한 모든 기능을 메뉴에 노출”하는 방식이 아니라, 실제 사용자가 반복하는
공통 데이터수집 업무 절차만 1차 메뉴에 둔다.

핵심 개념은 아래 11개다.

1. **Dashboard** — 오늘 무엇을 해야 하는지 보는 첫 화면
2. **Source/API** — 외부 API pull 수집원 등록
3. **Inbound Channel** — 외부 시스템/OCR/크롤러/업로드 push 수신 채널 등록
4. **Field Mapping** — 원천 응답 필드를 표준/staging/mart 컬럼으로 연결
5. **DQ / Quality** — 필수값, 이상값, 중복, freshness 등 품질 규칙 등록
6. **Transform** — SQL/API/function/AI 기반 정제 자산 등록
7. **Mart Designer** — 최종 적재 테이블과 load policy 설계
8. **ETL Canvas** — 위 자산들을 박스로 연결하여 수집 프로세스 설계/저장/배포
9. **Jobs & Runs** — 저장된 프로세스를 job 으로 확인하고 실행/재실행
10. **Monitoring** — 운영 상태, 실패, 지연, 재처리, freshness, 비용 확인
11. **Users** — 사용자/권한 관리

> Raw Objects, Collection Jobs, Releases, SQL Studio, Review Queue, Runtime Monitor,
> Dead Letters, API Keys, Security Events, Partition Archive 는 기능을 삭제하지
> 않는다. 다만 V3 의 1차 사이드 메뉴에서는 숨기고, 상세 링크/관리자 직접 URL/운영
> 문서에서만 접근하는 보조 화면으로 둔다.

---

## 1. 사용자 작업 흐름 6 단계

| # | 단계 | 메뉴 | 산출물 |
|---|---|---|---|
| 1 | 수집원 정의 | **Source/API** 또는 **Inbound Channel** | pull API connector / push channel |
| 2 | 데이터 구조 연결 | **Field Mapping** | source path → target column + transform function |
| 3 | 품질·정제 자산 설계 | **DQ / Quality** + **Transform** | DQ rule / SQL asset / HTTP transform / function |
| 4 | 적재 대상 설계 | **Mart Designer** | mart schema + key + partition + load policy |
| 5 | 프로세스 조립·배포 | **ETL Canvas** | 저장 가능한 workflow definition |
| 6 | 실행·운영 | **Jobs & Runs** + **Monitoring** | run 이력 / 실패 원인 / 재실행 / SLA |

**원칙**: 모든 자산은 **DRAFT → REVIEW → APPROVED → PUBLISHED** 라이프사이클. PUBLISHED 만 ETL Canvas 노드에서 사용 가능.

---

## 2. V3 1차 사이드 메뉴 순서

| 그룹 | 메뉴 | 경로 | 업무상 의미 |
|---|---|---|---|
| 진입 | Dashboard | `/` | 오늘 상태와 다음 작업 확인 |
| 1. 자산 설계 | Source/API | `/v2/connectors/public-api` | 외부 API pull 수집 설계 |
| 1. 자산 설계 | Inbound Channel | `/v2/inbound-channels/designer` | 외부 push/OCR/크롤러/업로드 수신 설계 |
| 1. 자산 설계 | Field Mapping | `/v2/mappings/designer` | 원천 필드와 대상 컬럼 연결 |
| 1. 자산 설계 | DQ / Quality | `/v2/quality/designer` | 품질 검사 규칙 설계 |
| 1. 자산 설계 | Transform | `/v2/transforms/designer` | SQL/API/function/AI 정제 자산 설계 |
| 1. 자산 설계 | Mart Designer | `/v2/marts/designer` | 최종 mart 테이블과 적재 정책 설계 |
| 2. 프로세스 조립/실행 | ETL Canvas | `/v2/pipelines/designer` | 박스 연결, 저장, publish, 실행 |
| 2. 프로세스 조립/실행 | Jobs & Runs | `/pipelines/runs` | 등록된 프로세스의 실행 이력, 상세, 재실행 |
| 3. 운영 모니터링 | Monitoring | `/v2/operations/dashboard` | 채널 상태, 실패, 지연, freshness, 비용 |
| 4. 시스템 관리 | Users | `/users` | 사용자와 권한 관리 |

---

## 3. 보조 화면 처리 정책

| 보조 화면 | 기존 경로 | V3 처리 |
|---|---|---|
| Service Mart Viewer | `/v2/service-mart` | 시연/검증 링크에서 접근. 핵심 메뉴에서는 제외 |
| Raw Objects | `/raw-objects` | Run Detail/Monitoring 의 원천 링크에서 접근 |
| Collection Jobs | `/jobs` | Jobs & Runs 로 통합. 기존 경로 유지 |
| Releases | `/pipelines/releases` | ETL Canvas publish 이력 상세 링크로 유지 |
| SQL Studio | `/sql-studio` | 운영 자산은 Transform 으로 승급. ad-hoc 분석용 직접 URL 유지 |
| Review Queue | `/crowd-tasks` | DQ/표준화 실패 상세 링크에서 접근 |
| Runtime Monitor | `/runtime` | 인프라 관제 보조. Monitoring 에서 필요한 지표만 노출 |
| Dead Letters | `/dead-letters` | 장애 상세 분석용 관리자 URL |
| API Keys | `/api-keys` | 외부 소비자 API 운영 시 관리자 URL |
| Security Events | `/security-events` | 보안 감사용 관리자 URL |
| Partition Archive | `/admin/partitions` | 장기 보관/복원용 관리자 URL |

---

## 4. 상세 기능 가이드

### 1. Dashboard (`/`)

**기능**
- Quick Start 카드 (5단계 진행도 자동 카운트)
- KPI 4종: 활성 소스 / 오늘 작업 / 성공·실패 카운트
- 최근 실패 5건

**목적** — 신규 운영자가 "다음에 뭘 해야 할지" 즉시 알 수 있게.

**사용법**
1. 로그인 (`admin` / `admin`) 후 자동 진입
2. Quick Start 카드의 미완료 단계 클릭 → 해당 디자이너로 이동
3. 운영 중에는 KPI 로 일일 상태 점검

---

## ② Build — 자산 작성

### 2. Source / API Connector (`/v2/connectors/public-api`)

**기능**
- 외부 OpenAPI 형 데이터 소스 등록
- 응답 포맷 7종 (JSON / XML / CSV / TSV / TEXT / Excel / Binary) — Phase 8.6
- URL 자동 파싱 (query string → params 자동 분리)
- HTTP method (GET / POST), auth (none / query_param / header / basic / bearer)

**목적** — 어떤 외부 API 든 *코딩 0줄* 로 등록. 정부 공공데이터 / 회사 ERP / 외부 SaaS 모두 동일 폼.

**사용법**
1. [+ 새 API 등록] 클릭
2. domain · resource · endpoint URL · auth · response_format · response_path 입력
3. [Test Call] 로 검증 (실제 외부 호출, 응답 row 미리보기)
4. DRAFT → REVIEW → APPROVED → PUBLISHED 단계 transition
5. ETL Canvas 의 `PUBLIC_API_FETCH` 노드에서 dropdown 으로 선택

**팁**
- secret_ref 는 backend `.env` 의 환경변수 이름 (실제 값 아님)
- pagination_kind 와 response_format 은 외부 API 문서 보고 정확히 매칭

---

### 3. Inbound Channel (`/v2/inbound-channels/designer`)

**기능**
- *외부에서 우리에게 push* 하는 채널 등록 (반대 방향)
- 인증 3종: HMAC SHA256 / API Key (`X-API-Key` 헤더) / mTLS (Phase 9)
- channel_kind 4종: WEBHOOK / FILE_UPLOAD / OCR_RESULT / CRAWLER_RESULT

**목적** — OCR 업체 / 크롤러 / 소상공인 업로드 등 외부가 데이터를 보내오는 경우의 endpoint 정의.

**사용법**
1. [+ 새 Inbound] → channel_code · domain · channel_kind 선택
2. auth_method 선택 + secret_ref env 변수명 지정
3. PUBLISHED 후 외부 업체에 endpoint URL 공지: `POST /v1/inbound/{channel_code}`
4. Auto Dispatcher (5초 polling) 가 RECEIVED → PROCESSING 자동 전환

**팁**
- Phase 8.4 — auth_method=`api_key` 정식 구현 (`X-API-Key` constant_time 비교)
- Phase 8.5 — Auto Dispatcher 5초 polling 자동 가동

---

### 4. Mart Workbench (`/v2/marts/designer`)

**기능**
- 마트 테이블 DDL 시각 설계 (컬럼 / PK / partition / index)
- load_policy (insert / upsert / merge) + key_columns 등록
- 4 템플릿 제공 (price_fact / product_master / stock_snapshot / promo_fact)

**목적** — 적재 대상 마트 테이블을 운영자가 직접 설계 + 적재 모드 결정.

**사용법**
1. [+ 새 Mart 설계] → 템플릿 선택 또는 빈 상태에서 시작
2. 컬럼 / PK / partition (월별 RANGE 권장) / index 입력
3. DDL 미리보기 → DRAFT → ... → PUBLISHED
4. Load Policy 탭에서 mode + key_columns + dedup 정의
5. ETL Canvas 의 `LOAD_TARGET` 노드에서 사용

**팁**
- partition 은 월별 (RANGE on observed_at) 권장
- PUBLISHED 후 컬럼 변경 시 Alembic migration 필요 (직접 ALTER 금지)

---

### 5. Field Mapping Designer (`/v2/mappings/designer`)

**기능**
- 외부 응답의 *JSON path* (`$.items[*].sensor_id`) → *mart 컬럼* 매핑
- 변환 함수 26+ allowlist (`text.trim`, `number.parse_decimal`, `date.normalize_ymd` 등)
- JSON Path Picker — sample 응답 → tree 클릭 → 자동 입력

**목적** — JSONB / XML 의 평탄화 + 정규화. **target_table 은 최종 mart 가 아닐 수도 있음** — `<domain>_stg` (평탄화 stg) 로 먼저 적재 후 SQL_ASSET 으로 후처리 권장.

**사용법**
1. domain 선택 → contract 선택 (Source/API Connector 등록 시 자동 생성)
2. [+ 새 매핑 행] → 우측 JSON Path Picker 에 sample 응답 붙여넣기
3. tree 의 leaf 노드 클릭 → source_path 자동 입력
4. target_table.column 매핑 + transform_expr (키 힌트 기반 자동 추천)
5. PUBLISHED → ETL Canvas 의 `MAP_FIELDS` 노드에서 사용

**target_table 권장 schema**
| schema | 용도 |
|---|---|
| `wf.tmp_run_*` | Canvas 실행 임시 sandbox (default) |
| `<domain>_stg.*` | **평탄화 stg (영구)** — 표준화 직전 |
| `<domain>_mart.*` | 최종 마트 |

---

### 6. Transform Designer (`/v2/transforms/designer`)

**기능** — 4 탭
1. **SQL Asset** — domain.sql_asset CRUD + transition (`SQL_ASSET_TRANSFORM` 노드 backing)
2. **HTTP Provider** — provider_kind=HTTP_TRANSFORM 카탈로그 (read-only)
3. **Function** — 26+ allowlist 함수 카탈로그 (read-only)
4. **Provider** — 전체 provider 카탈로그 (read-only)

**목적** — Canvas 노드에서 사용할 *재사용 가능한* 변환 자산을 등록. version 관리.

**사용법**
1. SQL Asset 탭 → [+ 새 SQL Asset]
2. SQL 작성 (SELECT 형태 권장 — sql_guard 가 직접 DML 차단)
3. Dry-run → row count 확인
4. PUBLISHED → ETL Canvas 의 `SQL_ASSET_TRANSFORM` 노드에서 dropdown

**중요 정책 (Phase 8.6)**
- 모든 운영 SQL 은 **반드시 여기에 등록**되어야 Canvas 에서 사용 가능
- SQL Studio 의 ad-hoc SELECT 는 *탐색용* — 운영 흐름에 들어가지 않음

---

### 7. Quality Workbench (`/v2/quality/designer`)

**기능** — DQ Rule kind 7+종
| kind | 폼 / SQL | 예시 |
|---|---|---|
| `row_count_min` | 폼 | `{"min": 1}` |
| `null_pct_max` | 폼 | `{"column": "value", "max": 0.05}` |
| `unique_columns` | 폼 | `{"columns": ["sensor_id", "ts"]}` |
| `reference` | 폼 | `{"column": "std_code", "ref_table": "..."}` |
| `range` | 폼 | `{"column": "value", "min": 0, "max": 100}` |
| `freshness` | 폼 | `{"max_age_minutes": 1440}` |
| `anomaly_zscore` | 폼 | `{"column": "...", "threshold": 3.0}` |
| `drift` | 폼 | `{"method": "kl_divergence", "threshold": 0.2}` |
| `custom_sql` | 직접 SQL | 파워유저용 |

**목적** — 적재 직전 데이터 품질 검증. fail_action=`block` 이면 mart 적재 차단 → hold queue 로 이동.

**사용법**
1. domain 선택
2. target_table — Phase 8.6 부터 **카탈로그 dropdown** (PUBLISHED 마트만 노출)
3. [+ 새 DQ Rule] → rule_kind 선택 → rule_json 입력 (대부분 폼, custom_sql 만 직접)
4. severity (INFO/WARN/ERROR/CRITICAL) + fail_action (block/warn/pass)
5. PUBLISHED → ETL Canvas 의 `DQ_CHECK` 노드에서 사용

---

### 8. ETL Canvas V2 (`/v2/pipelines/designer`)

**기능**
- 좌측 팔레트의 **20 노드** 카탈로그를 끌어다 놓고 edge 로 연결
- **Cron Picker 6 모드** (수동/N분/N시간/매일/요일+시각/고급)
- Auto-save / Dry-run / PUBLISHED 라이프사이클
- Canvas Readiness Checklist (source/load 박스 / 자산 선택 검증)
- Canvas 권장 패턴 박스 (빈 캔버스 진입 시)

**목적** — 시스템의 핵심. 운영자가 직접 데이터 흐름을 그림.

**노드 20종**
- DATA SOURCES (8): SOURCE_DATA / PUBLIC_API_FETCH / WEBHOOK_INGEST / FILE_UPLOAD_INGEST / DB_INCREMENTAL_FETCH / OCR_TRANSFORM / CRAWL_FETCH / OCR_RESULT_INGEST / CRAWLER_RESULT_INGEST / CDC_EVENT_FETCH (STUB)
- TRANSFORM (6): MAP_FIELDS / SQL_INLINE / SQL_ASSET / HTTP / FUNCTION / STANDARDIZE
- VALIDATE (2): DEDUP / DQ_CHECK
- LOAD / OUTPUT (2): LOAD_TARGET / NOTIFY

**사용법**
1. workflow name 입력 → 좌측 팔레트에서 노드 끌기
2. 노드 클릭 → 우측에서 자산 dropdown 선택 (PUBLISHED 만)
3. edge 연결 (왼쪽→오른쪽)
4. [Dry-run] 으로 검증 → DRAFT → ... → PUBLISHED
5. Cron Picker 로 schedule 설정 + 활성

**권장 패턴**: `SOURCE_DATA → MAP_FIELDS → DQ_CHECK → STANDARDIZE → SQL_ASSET → LOAD_TARGET`

---

## ③ Run — 실행 이력

### 9. Pipeline Runs (`/pipelines/runs`)

**기능**
- 워크플로 목록 + 최근 실행 이력
- 각 워크플로 [보기] 버튼 → ETL Canvas V2 라우팅 (Phase 8.5 수정)

**목적** — 어떤 워크플로가 언제 어떤 상태로 실행됐는지 한 화면.

**사용법**
- 워크플로 행 → [보기] = Canvas 진입
- 실행 행 클릭 → Pipeline Run Detail

---

### 10. Pipeline Run Detail (`/pipelines/runs/{id}`)

**기능 (Phase 8.5 보강)**
- ReactFlow 캔버스 — 노드별 상태 색상 (PENDING/READY/RUNNING/SUCCESS/FAILED)
- **노드별 duration gantt-mini** — 각 노드 시작/종료 시각화
- output_json preview (성공 노드)
- error_message 강조 박스 (실패 시)
- "처음부터 재실행" / **"이 노드부터 재실행"** 버튼

**목적** — 장애 대응. 어느 노드에서 막혔는지, 얼마나 걸렸는지 즉시 식별.

**사용법**
- Operations Dashboard 의 최근 실패 패널 / Pipeline Runs 에서 진입
- 실패 노드 클릭 → "이 노드부터" 재실행 (이전 노드는 SUCCESS 로 시드)

---

### 11. Releases (`/pipelines/releases`)

**기능** — PUBLISHED 워크플로의 release 이력 + 환경 배포 추적.

**목적** — 어느 시점 어느 워크플로 버전이 운영에 배포됐는지.

**사용법** — 각 release 행의 [워크플로] 클릭 → 해당 버전의 ETL Canvas (Phase 8.5 라우팅 수정).

---

## ④ Operate — 실 운영

### 12. Service Mart Viewer (`/v2/service-mart`)

**기능 (Phase 8 데모 — 농산물 가격 시연용)**
- 통합 service_mart 조회
- 가격 비교 / 추이 / 요약 차트 (PriceCompareCard / PriceTrendChart / PriceSummaryCard)
- 필터 토글 (할인 중 / 품절 / 검수 필요)

**목적** — 적재 결과를 외부 서비스 관점에서 미리보기.

**참고** — 공용 플랫폼이라 도메인이 다른 실증에서는 *별도 viewer 화면*을 사용자가 정의해야 함.

---

### 13. Raw Objects (`/raw-objects`)

**기능** — 외부 응답을 그대로 보존한 `raw.raw_object` 목록. content_hash 중복 차단, partition_date 분리.

**목적** — 적재 결과가 의심될 때 *원천* 까지 역추적.

**사용법** — Pipeline Run Detail 에서 raw 링크 클릭하거나 직접 검색. 운영자가 데이터 누락/오류 발견 시 raw 부터 확인.

---

### 14. Collection Jobs (`/jobs`)

**기능** — schedule 또는 manual trigger 로 실행된 ingest_job 이력 (raw 수집 단위).

**목적** — 워크플로 (`pipeline_run`) 보다 *낮은 레이어* — 단순 외부 호출 이력.

**사용법** — 외부 API 가 응답 안 한 경우 / rate limit 걸린 경우 등 채널 단위 진단.

---

### 15. Master Merge (`/master-merge`)

**기능** — 다중 소스에서 들어온 동일 entity 를 master 테이블로 자동 머지.

**목적** — 표준코드 매칭 후 마스터 정규화 (예: 같은 상품을 여러 채널에서 수집).

**사용법** — 도메인별 master 운영자가 머지 룰 검토 + 충돌 해결.

---

### 16. SQL Studio (`/sql-studio`)

**기능 (Phase 8.6 정책 정정)**
- *ad-hoc 탐색용* SQL 실행 (SELECT 만, audit 기록)
- 모든 실행은 `audit.sql_execution_log` 기록
- 상단 정책 배너 노출

**목적** — 데이터 탐색.

**중요 정책**
- **운영 SQL 은 반드시 Transform Designer 의 sql_asset 으로 등록 → Canvas 에서 사용** 해야 추적 가능
- DML 직접 실행 금지 (sql_guard 가 차단)

**사용법**
1. SELECT 작성 → [Validate] → [Preview]
2. 의미 있는 query 발견 시 Transform Designer 로 옮겨 sql_asset 으로 등록

---

### 17. Review Queue (`/crowd-tasks`)

**기능** — `crowd.task` 의 `std_low_confidence` task — 표준코드 자동 매칭 confidence 낮은 항목을 검수자가 직접 결정.

**목적** — AI 매칭이 모호한 경우 사람이 보정.

**사용법** — REVIEWER 권한 보유자가 큐에서 항목 선택 → 표준코드 결정 → 매핑 보정 → 다음 run 부터 자동 적용.

---

### 18. Operations Dashboard (`/v2/operations/dashboard`)

**기능** — 시스템 전반 운영 통합 화면. 카드 다수:
| 카드 | Phase | 내용 |
|---|---|---|
| KPI 4종 | 7 | Workflows / Runs(24h) / Success Rate / Pending Replay |
| **SLA Lag** | 8.5 | 수집→적재 p50/p95/p99 (≤60s 녹색, ≤180s 황색, >180s 적색) |
| **Auto Dispatcher** | 8.5 | RUNNING/STALE + 대기 envelope + 마지막 dispatch |
| **Airflow Scheduler** | 8.6 | RUNNING/STOPPED + schedule_enabled 워크플로 수 |
| **채널 데이터 신선도** | 8.5 | PUBLISHED 채널별 마지막 수신 시각 + 60min STALE |
| **Provider 호출/비용** | 8.5 | provider별 24h 호출/오류/비용 |
| **24h 시간별 추이** | 8.2 | success/failed 누적 막대 |
| **최근 실패 10건** | 8.4 | 실패 노드 + 원천 링크 + 30s polling |
| **실패 원인 분류** | 8.1 | node_type 별 실패 카테고리 |
| **Channels** | 7 | workflow별 24h 카운트 + 노드 heatmap |

**목적** — 운영자가 출근 시 본 화면 1개로 전체 상태 파악 + 즉시 대응.

**사용법**
1. SLA Lag 색상 → 임계 초과 시 즉시 확인
2. 채널 신선도 STALE → 클릭 → 상세
3. 최근 실패 → 실패 노드 클릭 → 재실행
4. Provider 비용 임계 추적

---

### 19. Runtime Monitor (`/runtime`)

**기능** — Worker / Redis / Object Storage / DB 등 *시스템 컴포넌트* 의 실시간 상태.

**목적** — Operations Dashboard 가 *데이터 흐름* 모니터링이라면, 이건 *인프라 헬스* 모니터링.

**사용법** — 장애 의심 시 어느 컴포넌트가 문제인지 식별.

---

## ⑤ Admin — 시스템 관리 (ADMIN 권한)

### 20. Dead Letters (`/dead-letters`)

**기능** — 처리 실패 후 retry 한도 초과한 메시지 큐.

**목적** — *완전 실패한* 작업을 운영자가 수동 검토 + 복구.

**사용법** — 실패 메시지 검토 → 원인 파악 → 재시도 또는 폐기.

---

### 21. Users (`/users`)

**기능** — 사용자 계정 + 역할 (ADMIN / DOMAIN_ADMIN / APPROVER / OPERATOR / REVIEWER) 관리.

**목적** — 권한 분리. 도메인별 ADMIN 분리 가능.

**사용법** — 신규 운영자 합류 시 계정 생성 + 역할 부여.

---

### 23. API Keys (`/api-keys`)

**기능** — 외부 소비자가 우리 Public API 호출용 키 관리. scope / rate_limit / expires_at.

**목적** — 외부 서비스에 데이터 제공 시 인증.

**사용법** — [신규 키 발급] → scope 지정 → 외부 측에 키 공유.

---

### 24. Security Events (`/security-events`)

**기능** — 인증 실패 / abuse / TLS 실패 등 보안 이벤트 로그.

**목적** — 외부 공격 / 키 유출 / 비정상 접근 패턴 감지.

**사용법** — 정기 리뷰 + 임계 초과 시 키 회수.

---

### 25. Partition Archive (`/admin/partitions`)

**기능** — `raw.raw_object_*`, `run.pipeline_run_*` 등 월별 파티션을 Object Storage 로 archive + DB 에서 detach.

**목적** — DB 크기 관리 + 비용 절감.

**사용법** — 월별 정기 archive (또는 cron). 필요 시 restore.

---

## 메뉴 사용 흐름 요약

```
[Build]                         [Run]                  [Operate]
Source ───┐                      ┌─ Pipeline Runs ──┐  ┌─ Operations Dashboard
           │                     │                  │  │  (SLA / Airflow / Failures)
Inbound ───┤                     │                  │  │
           │                     │                  │  │
Mart       │                     │                  │  ├─ Service Mart Viewer
           │                     │                  │  │
Mapping ───┼─→ ETL Canvas ─→ Pipeline Run ─────→  ─┤  ├─ Raw Objects
           │   (자산 조립)         (실행)              │  │
Transform ─┤                     │                  │  ├─ Collection Jobs
           │                     │                  │  │
Quality ───┘                     └─ Releases ───────┘  ├─ SQL Studio (탐색)
                                                       │
                                                       ├─ Review Queue (검수)
                                                       │
                                                       └─ Runtime Monitor

[Admin]
Dead Letters / Users / API Keys / Security Events / Partition Archive
```
