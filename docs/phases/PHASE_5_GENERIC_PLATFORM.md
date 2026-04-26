# Phase 5 — 공용 데이터 수집 플랫폼 (v2 Generic)

**전제:** Phase 4 완료. 농축산물 가격 파이프라인 v1 이 NKS 위에서 안정 가동 + 운영팀
6~7명이 일상 운영.

**기간 목표:** 12~18주
**성공 기준 (DoD):**
1. v1 (농축산물 가격) 이 v2 generic platform 위에서 동일하게 동작 (회귀 0).
2. 새 도메인 1개를 v2 위에 **같은 작업 패턴** 으로 추가 가능 (예: IoT 센서 데이터 / POS 거래
   로그 / 의약품 가격) — 코드 작성 없이 YAML + SQL 만으로.
3. 도메인 분리 (`domains/agri.yaml`, `domains/iot.yaml` 등) 로 사용자가 선택 가능.
4. 사용자가 source schema / field mapping / staging / mart / DQ / load policy 를 직접 설계할
   수 있고, 플랫폼은 sandbox / approval / compatibility check 로 안전하게 실행한다.
5. v2 의 공통 수집 공정이 Data Contract, Raw 보존, Schema Validation, DQ, Lineage,
   Observability 를 포함한다.
6. 성능 baseline 과 가드레일이 정의되어, 사용자가 만든 schema / SQL / DQ / backfill 이
   플랫폼 전체 성능을 망가뜨리지 않는다.

---

## 5.0A 현실 배포 순서와 Phase 4 후반부 재배치

현재 제품 흐름은 **로컬 개발 → 회사 서버 시연 → 고객 컨펌 → NCP/NKS 운영 전환** 순서로
진행한다. 따라서 Phase 4 문서의 `4.2.8b NKS 이관`, `4.2.9 장애 복구/HA`,
`4.2.10 관제/비용 대시보드` 는 지금 당장 구현하는 백로그가 아니라, 고객 컨펌 이후 운영
전환 단계에서 수행하는 인프라 트랙으로 둔다.

권장 순서:

```
A. 로컬 개발 완료
   - Phase 4 의 앱/도메인 기능 검증
   - Crowd, DQ, Public API, Merge, Archive 등 핵심 기능 smoke

B. 회사 서버 시연 배포
   - Docker Compose 기반 staging
   - nginx + SSL
   - PostgreSQL / Redis / MinIO 또는 회사 인프라
   - demo data + demo account
   - 기본 backup / restore / restart runbook

C. 고객 시연 / 컨펌
   - 기능 검증
   - 데이터 흐름 설명
   - 공용 v2 platform 요구사항 수집
   - NCP VM 으로 충분한지, NKS 가 필요한지 판단

D. v2 Generic 고도화 / 프로토타입
   - source contract / mapping / mart / DQ / provider registry / ETL UX 검증
   - 고객이 원하는 "공용 수집 플랫폼" 방향이면 Phase 5 를 우선 진행

E. NCP 운영 전환
   - NCP VM + managed DB 로 갈지, 바로 NKS 로 갈지 결정
   - 비용/운영팀/트래픽 기준으로 인프라 선택

F. NKS 이관
   - Phase 4.2.8b 를 실행

G. HA / DR / 비용 대시보드
   - Phase 4.2.9, 4.2.10 을 NKS 안정화 이후 실행
```

재배치 원칙:

| 항목 | 기존 Phase 4 위치 | 권장 실행 시점 | 이유 |
|---|---|---|---|
| NKS 이관 | 4.2.8b | 고객 컨펌 후 NCP 운영 전환 단계 | Terraform/NKS/Argo CD 는 실제 NCP 환경과 운영팀이 있어야 가치가 큼 |
| 장애 복구 / HA | 4.2.9 | NKS 이관 후 | PITR/HPA/pod 장애 리허설은 NKS/Cloud DB 환경에서 검증해야 함 |
| 비용 대시보드 | 4.2.10 | NCP 운영 안정화 후 | NCP Billing, OCR 비용, NKS 비용은 실제 운영 리소스가 있어야 의미 있음 |
| 회사 서버 시연 배포 | 신규 | Phase 5 전후 병행 | 고객 컨펌을 위한 최소 운영 환경이 먼저 필요 |

회사 서버 시연 단계의 최소 산출물:

- `infra/docker-compose.yml` 기반 staging 기동 절차.
- nginx reverse proxy + SSL 설정.
- `.env` / secret 관리 절차.
- DB migration + seed + demo account.
- backup / restore / restart runbook.
- demo scenario: source 등록 → 수집 → raw → transform → DQ → mart → public/internal API.
- 기본 관제: Grafana core/runtime dashboard, worker lag, DLQ, ON_HOLD, API error rate.

이 문서의 Phase 5 는 NKS 이관 완료를 필수 전제로 하지 않는다. 단, v2 가 운영 제품으로
확정되고 고객 컨펌 이후 트래픽/운영 요구가 커지면 Phase 4.2.8b~4.2.10 을 별도 인프라
트랙으로 재개한다.

---

## 5.0 v1 vs v2 — 핵심 차이

| 영역 | v1 (현재) | v2 (목표) |
|---|---|---|
| 도메인 | 농축산물 가격만 | 임의 — agri / iot / pos / pharma / ... |
| 마트 스키마 | 하드코딩 (`mart.price_fact`, `mart.product_master`) | 도메인 yaml 로 정의 (`mart.<resource>_fact`, `mart.<resource>_master`) |
| 표준화 | std_code 1종 (식품 분류) | n 도메인 × 각자의 표준 코드 체계 |
| 노드 타입 7종 | 농축산물에 최적화 (`LOAD_MASTER` 가 mart.product_price 가정) | resource-agnostic (`LOAD_TARGET` 이 임의 mart 테이블) |
| `mart.standard_code.embedding` | 식품용 1536d | 도메인별 별도 테이블 + 별도 embedding |
| OCR / 크롤링 정책 | CLOVA/Upstage + httpx spider 중심 | provider registry 로 추상화 — CLOVA/외부 OCR/Playwright/외부 크롤링 서비스 교체 |
| Crowd 검수 | 식품 검수자 1풀 | 도메인 × skill_tag 매트릭스 |

**핵심 통찰**: v1 의 모든 *비즈니스 로직* 은 사실 *도메인 = 농축산물* 라는 가정에 의해 코드에
박혀 있다. v2 는 그 가정을 **YAML 설정 + plugin domain** 으로 외재화.

### 5.0.1 v2 표준 수집 공정

v2 는 특정 도메인 mart 를 미리 정해두는 시스템이 아니라, 사용자가 자기 도메인의 데이터
공정을 설계하고 플랫폼이 그 설계를 안전하게 실행하는 **공용 수집 운영체제**다.

공통 공정:

```
Source Contract
  → Raw Preservation
  → Schema Validation
  → Field Mapping
  → Staging / Canonical Model
  → DQ Validation
  → Lineage
  → Target Load
  → Observability
  → Governance
```

| 공정 | v2 책임 |
|---|---|
| Source Contract | source 별 payload schema, 필수 필드, 타입, schema version, compatibility 정책 |
| Raw Preservation | v1 의 `raw.raw_object` + Object Storage + content_hash/idempotency 유지 |
| Schema Validation | JSON Schema / table schema 기반 검증. 실패 시 raw 는 보존하고 processing 은 HOLD |
| Field Mapping | source field → staging/canonical/mart field 매핑. UI + YAML 양쪽 지원 |
| Staging | 도메인별 임시 표준 모델. JSONB 만능 저장소가 아니라 분석/적재용 컬럼화 지원 |
| DQ Validation | DQ rule registry + inline assertion + custom SQL. profiling 기반 rule 추천은 v2 후반 |
| Lineage | raw_object → transform SQL → target table/column 의 lineage metadata 기록. OpenLineage 호환 준비 |
| Target Load | append-only / UPSERT / SCD Type 2 / soft delete / current snapshot 등 load policy 선택 |
| Observability | ingest latency, worker lag, DQ duration, SQL cost, mart load rows/sec 를 공통 지표화 |
| Governance | domain/schema 변경 승인, SQL approval, mart publish checklist, audit log |

수집 모드는 네 가지를 공통 인터페이스로 추상화한다:

| 모드 | 용도 | 초기 우선순위 |
|---|---|---|
| API push | 외부 시스템이 우리 `/v2/ingest/{source}` 로 직접 전송 | 1순위 |
| API polling | partner API 를 주기적으로 조회. `updated_at`/cursor watermark 필수 | 1순위 |
| Webhook | 가격/재고 변경 시 외부 시스템이 이벤트 알림 | 2순위 |
| CDC/Kafka | 깊은 제휴 또는 대규모 실시간 동기화. Debezium/Kafka 계열 | 조건부 |

Kafka/CDC 는 v2 기본 전제가 아니다. 상대 시스템의 DB 로그 접근/replication 권한이 필요하므로,
먼저 Partner API + 짧은 주기 incremental polling + webhook 을 안정화하고, 트래픽/제휴 수준이
올라간 뒤 선택한다.

### 5.0.2 v2 설계 원칙

**최상위 원칙 4종 (Phase 5 모든 결정의 기준):**

1. **v1 은 절대 흔들지 않는다** — schema/endpoint/운영 화면 모두 보존.
2. **v2 는 옆에 세운다** — `/v2` prefix + `<domain>_mart` schema 로 *별도 트랙*. v1 의
   `mart.*`, `stg.*`, `raw.*` 는 그대로.
3. **신규 도메인에서 generic 설계를 검증한다** — agri (v1) 는 *마지막* 에 흡수. 추상화의
   적정성은 *처음 보는 도메인 추가 시간* 으로 측정.
4. **v1 은 나중에 registry 에 등록해서 천천히 흡수한다** — Phase 5 초반엔 v1 mart 테이블을
   *그대로 yaml 에 등록* 만 하고, rename/move 는 Phase 5 후반 또는 Phase 6 이후.

**세부 원칙:**

- **v1 public contract 보존** — Phase 5 기간 동안 v1 API, v1 DB schema, v1 운영 화면은
  public contract. 명시적 deprecation ADR 없이 삭제/breaking change 금지.
- **raw 는 절대 잃지 않는다** — validation/DQ/transform 실패여도 원천 보존.
- **도메인 로직은 코드보다 설정으로 외재화** — domain yaml, DB registry, UI designer.
- **사용자 자유도는 sandbox 와 approval 로 제어** — custom SQL, mart 변경, DQ rule publish 는 검증 후 승인.
- **첫 새 도메인 1개가 추상화의 적정성을 검증** — 1~2주 안에 추가되면 적정, 4주 이상이면 추상화 부족.
- **성능 가드레일은 기능의 일부** — flexible schema / SQL / DQ / backfill 은 항상 cost guard 와 함께 제공.

---

## 5.1 마이그 전략 — Strangler Pattern

[Strangler Pattern](https://martinfowler.com/bliki/StranglerFigApplication.html) 으로
v1 → v2 점진 이전. *큰 빅뱅 재작성 없음.*

```
┌─── v1 (절대 흔들지 않음) ──────┐  ┌─── v2 (Strangler) ──────────┐
│ /v1/*  endpoint 보존           │  │ /v2/* (새 prefix)           │
│ mart.* / stg.* / raw.* 그대로  │  │ <domain>_mart.* schema      │
│ std_code 식품 (mart.standard_code) │  │ 도메인 별 std code (domain.*) │
│ Phase 4 RLS view 그대로        │  │ registry view 추가          │
└────────────┬───────────────────┘  └─────────────┬───────────────┘
             │                                    │
             └──────── 같은 PostgreSQL ───────────┘
                       (점진 이전)
```

**Schema 격리 전략 (Q4 결정):**

- v1 (agri legacy) — `mart.price_fact`, `mart.product_master`, `stg.price_observation`
  *그대로 유지*. rename/move 금지.
- 신규 도메인 — `<domain>_mart.*`, `<domain>_stg.*`, `<domain>_raw.*` 별도 schema.
  - `iot_mart.sensor_fact`, `pharma_mart.price_fact`, `pos_mart.txn_fact`, ...
- v1 의 mart 테이블은 *그대로 domain registry 에 등록* — yaml 에 `canonical_table:
  mart.product_master` 처럼 v1 경로를 그대로 가리킴 (Q3 결정).
- agri legacy → `agri_mart` schema 로 옮기는 것은 *Phase 5 후반 또는 Phase 6* 후속 결정.

3단계:

1. **5.1 — generic 코어 추출**: v1 의 도메인 로직을 plugin point 로 분리. 새 코드는 모두
   `/v2/*` prefix. v1 동작 유지.
2. **5.2 — v1 을 v2 plugin (agri 도메인) 으로 재구성**: v1 의 mart.price_fact 등을
   `domains/agri.yaml` 로 정의. v1 endpoint 는 그대로 유지하되 내부 구현이 v2 generic
   엔진 사용. *기존 mart 경로 변경 X.*
3. **5.3 — 새 도메인 추가**: POS / IoT / pharma 등 사용자 시나리오에 맞춰 1개씩 추가
   하면서 generic 인터페이스 다듬기. *신규 도메인 schema 는 `<domain>_*` 로 시작.*

각 단계마다 v1 회귀 테스트 통과 필수.

### 5.1.1 Git / Repository 정책

Phase 5 는 새 저장소를 만들지 않고 **현재 repository 안에서 v2 를 추가**한다. v1 의 raw/outbox,
worker, SQL Studio, Designer, observability 자산을 재사용하고, 회귀 테스트를 한 repo 안에서
계속 돌리기 위해서다.

정책:

- `main` 은 v1 안정 브랜치. Phase 5 작업은 `feature/v2-generic-platform` 에서 시작.
- 새 코드는 `/v2` API prefix, `domain.*` schema, `backend/app/api/v2`, `backend/app/generic`
  또는 `backend/app/domain/registry.py` 계열로 추가한다.
- v1 endpoint 와 v1 mart table 은 Phase 5 중 삭제/rename 금지. 필요한 경우 compat view 로 감싼다.
- 공통 코어 추출은 테스트가 있는 작은 단위로만 수행한다. v1 파일을 대규모 이동하지 않는다.
- 모든 PR/commit 기준: backend unit/integration + frontend build + v1 E2E smoke 가 통과해야 한다.
- v2 가 운영 안정화되고 독립 제품/팀/배포 단위가 필요해진 뒤에만 package 또는 repo 분리를 재검토한다.

---

## 5.2 작업 단위 체크리스트

### 5.2.0 사용자 설계 모델 + 가드레일 [W1~W2]

공용 플랫폼의 핵심은 사용자가 자기 데이터 도메인의 "공장 설계도"를 직접 만들 수 있게 하는
것이다. 단, 플랫폼은 위험한 설계를 sandbox / approval / compatibility check 로 막는다.

사용자가 직접 설계 가능한 항목:

| 항목 | 예 |
|---|---|
| Source/API schema | `salePrice:number`, `sku:string`, `updatedAt:datetime`, required 여부 |
| Field mapping | `itemNm → product_name`, `salePrice → price`, `stockQty → stock_qty` |
| Staging model | raw JSON 을 어떤 컬럼형 staging table 로 펼칠지 |
| Mart model | master / fact / dimension / current snapshot table 설계 |
| Key / constraint | business key, unique key, partition key, foreign/reference check |
| Load policy | append-only, UPSERT, SCD Type 2, soft delete, latest snapshot |
| DQ rule | null/range/unique/reference/custom_sql, severity, timeout, sample limit |
| Schedule / backfill | cron, polling interval, batch size, 날짜 범위, 재실행 시작 노드 |

가드레일:

- 허용된 domain schema 밖의 SQL 접근 차단.
- `DROP`/`DELETE`/`TRUNCATE`/외부 파일 함수 등 destructive SQL 차단.
- mart schema 변경은 DRAFT → REVIEW → APPROVED → PUBLISHED 상태머신 적용.
- source schema 변경은 versioning + backward compatibility check 필수.
- DQ custom SQL 은 preview/explain + timeout + max scanned rows 정책을 통과해야 publish 가능.
- LOAD_TARGET 은 domain registry 에 등록된 target table 에만 적재 가능.

### 5.2.1a Dynamic Resource Registry Spike [W1, 1주 선행]

**목적:** 도메인별 vector 차원 / 동적 테이블 정의를 SQLAlchemy 어떻게 다룰지 1주
spike. 본 spike 결과로 5.2.1 의 registry 구현 방향을 결정.

검증 항목:

- [ ] **옵션 A — SQLAlchemy ORM 동적 클래스 생성** (yaml → `type()` declarative class)
  + Alembic autogenerate 호환성.
- [ ] **옵션 B — SQLAlchemy Core + reflected Table** (`MetaData.reflect()`) +
  registry metadata 기반 query builder.
- [ ] **옵션 C — Hybrid**: v1 같은 *고정 도메인* 은 ORM, *신규 도메인* 은 Core reflection.

추천 (도입 전 검증):

> **정적 v1 ORM 유지 + v2 generic resource 는 SQLAlchemy Core + reflected Table.**
> 모든 도메인 테이블을 ORM 클래스로 강제 생성 X. 도메인별 vector 테이블도 Core 기반
> query builder.

산출물:

- [ ] `docs/adr/0017-resource-registry-orm-strategy.md` — 옵션 A/B/C 비교 + 채택 사유.
- [ ] PoC: 가짜 도메인 `iot.sensor_v1` schema → reflected Table → SELECT/INSERT 동작.
- [ ] Alembic migration 생성 정책 — 도메인 yaml 변경 시 어떤 방식으로 migration 생성?

### 5.2.1 generic schema 추상화 [W2~W4] (5.2.1a 결과 반영)

- [ ] migration: `domain.*` schema 신설
  - `domain.domain_definition (domain_code PK, name, description, schema_yaml jsonb)`
  - `domain.resource_definition (resource_id PK, domain_code FK, resource_code,
    canonical_table, fact_table)` — 각 도메인의 master/fact 테이블 정의.
    *v1 mart 테이블도 그대로 등록 가능* (`canonical_table='mart.product_master'`).
  - `domain.standard_code_namespace (namespace_id PK, domain_code FK, name)` —
    domain 별 std_code 체계
  - **`domain.source_contract`** — `(source_id, domain_code, resource_code, schema_version)`
    **복합 UNIQUE** (Q5 결정). 한 source 가 여러 (domain, resource) contract 를 가질
    수 있음.
    - 컬럼: `contract_id PK, source_id FK, domain_code, resource_code,
      schema_version, schema_json, compatibility_mode, resource_selector_json,
      status`
    - `resource_selector_json` — payload path / endpoint / payload.type 으로 어떤
      resource 인지 판단 (예: `{"path":"$.items.foodPrices"}` 또는
      `{"endpoint":"/prices/agri"}`).
  - `domain.field_mapping (mapping_id PK, contract_id, source_path, target_table,
    target_column, transform_expr)` — source → staging/mart 매핑
  - `domain.load_policy (policy_id PK, resource_id, mode, key_columns, partition_expr,
    scd_options_json)` — target load 방식
  - `domain.dq_rule (rule_id PK, domain_code, target_table, rule_kind, rule_json,
    severity, timeout_ms, status)` — DQ rule registry
  - `domain.provider_definition (provider_code PK, provider_kind, implementation_type,
    config_schema, is_active)` — OCR/CRAWLER/AI_TRANSFORM/HTTP provider registry
  - `domain.source_provider_binding (binding_id PK, source_id, provider_code, priority,
    fallback_order, config_json)` — source 별 provider 선택과 fallback 정책
- [ ] backend/app/domain/registry.py: domain 별 모델 로드 (5.2.1a spike 결과 반영 —
  ORM 동적 vs Core reflection 중 선택).
- [ ] backend/app/api/v2/domains.py: domain CRUD (ADMIN)
- [ ] backend/app/api/v2/contracts.py: source contract CRUD + compatibility check +
  resource_selector validation
- [ ] backend/app/api/v2/mappings.py: field mapping CRUD + sample payload validation
- [ ] backend/app/api/v2/providers.py: provider CRUD + source binding + health status
- [ ] tests: agri 도메인을 domain.* 에 등록 (canonical_table='mart.product_master'
  그대로) → v1 mart.price_fact 가 그대로 보임 + v1 endpoint 회귀 0.
- [ ] tests: 한 source 가 (agri, PRICE) + (pharma, PRICE) 두 contract 를 동시에
  가질 때 resource_selector 가 raw payload 를 올바르게 분기.
- [ ] tests: source schema v1 → v2 backward-compatible / breaking change 판정

### 5.2.1.1 OCR / Crawler Provider Registry [W2~W4]

현재 v1 은 이미 추상화의 씨앗을 갖고 있다.

- OCR 은 `OcrProvider` protocol 을 통해 CLOVA/Upstage 를 같은 `OcrResponse` 로 normalize.
- 크롤링은 `CrawlerSpider` protocol 을 통해 `HttpxSpider` 를 도메인 로직 밖에 격리.

하지만 provider 선택은 아직 코드에 가깝다. 예를 들어 OCR 은 worker 의 provider chain 에
CLOVA/Upstage 를 직접 붙이고, 크롤러는 worker 가 `HttpxSpider` 를 직접 생성한다. v2 공용
플랫폼에서는 source 별로 OCR/크롤링 구현을 바꿀 수 있어야 한다.

필요한 이유:

- OCR 은 CLOVA 를 계속 쓸지, Upstage/Google Vision/AWS Textract/자체 OCR/외부 OCR API 로
  바꿀지 미정이다.
- 크롤링은 직접 httpx/Playwright 로 할 수도 있고, 외부 scraping API 를 호출할 수도 있다.
- 도메인마다 비용/정확도/속도/법적 제약이 다르므로 provider 선택과 fallback 이 source 단위로
  달라져야 한다.
- 벤더 장애 시 fallback 순서만 바꿔 운영 복구가 가능해야 한다.

목표 구조:

```yaml
source_code: RECEIPT_UPLOAD
source_type: OCR
providers:
  - provider_code: clova
    priority: 1
    confidence_threshold: 0.85
  - provider_code: upstage
    priority: 2
```

```yaml
source_code: ONLINE_MALL_CRAWL
source_type: CRAWLER
providers:
  - provider_code: playwright
    priority: 1
    respect_robots: true
    rate_limit_per_min: 30
  - provider_code: external_scraping_api
    priority: 2
```

체크리스트:

- [ ] OCR provider registry: `clova`, `upstage`, `external_ocr_api` baseline.
- [ ] Crawler provider registry: `httpx`, `playwright`, `external_scraping_api` baseline.
- [ ] provider_kind: `OCR | CRAWLER | AI_TRANSFORM | HTTP_TRANSFORM`.
- [ ] implementation_type: `internal_class | external_api`.
- [ ] source 별 fallback_order / timeout / retry / rate_limit / cost_hint 설정.
- [ ] provider health check + circuit breaker status 를 admin UI 에 표시.
- [ ] worker 는 provider_code 를 보고 factory 에서 구현체를 생성. worker 내부 hard-code 제거.
- [ ] tests: 같은 OCR raw_object 를 clova mock / upstage mock / external mock 으로 교체 실행.
- [ ] tests: 같은 crawl source 를 httpx mock / playwright mock / external service mock 으로 교체 실행.

이 섹션의 목표는 v1 의 좋은 추상화(`OcrProvider`, `CrawlerSpider`)를 유지하되, provider 선택을
코드가 아니라 DB/UI 설정으로 끌어올리는 것이다.

### 5.2.2 노드 타입 generic 화 [W3~W5]

- [ ] `SOURCE_API` → `SOURCE_DATA` (resource-agnostic, source_id + raw_object_type)
- [ ] `MAP_FIELDS` 신규 — source contract / field_mapping 기준으로 raw payload 를 staging
      column 으로 펼침.
- [ ] `SQL_TRANSFORM` → `SQL_INLINE_TRANSFORM` 으로 명확화. 노드 안에 직접 SQL 작성.
- [ ] `SQL_ASSET_TRANSFORM` 신규 — SQL Studio 에서 APPROVED 된 `sql_query_version_id`
      를 호출해 transform 실행.
- [ ] `HTTP_TRANSFORM` 신규 — 외부 정제 API / AI 모델 / 주소 정제 / 표준화 API 호출.
- [ ] `FUNCTION_TRANSFORM` 신규 — 시스템 내부에 등록된 정제 함수 또는 내부 API 호출.
- [ ] `LOAD_MASTER` → `LOAD_TARGET` (target_table 이 임의 mart 테이블 가능, 단 도메인
      yaml 에 등록된 것만)
- [ ] `DEDUP` → 변경 없음 (key_columns generic)
- [ ] `DQ_CHECK` → rule registry 를 참조할 수 있게 확장. inline assertion 도 유지.
- [ ] `NOTIFY` → 변경 없음
- [ ] `STANDARDIZE` 신규 노드 — 도메인의 standard_code_namespace + embedding 테이블 사용
- [ ] tests: 같은 워크플로 그래프가 agri / iot 두 도메인에서 동작

v2 노드 카탈로그 초안:

| 노드 | 역할 | 비고 |
|---|---|---|
| `SOURCE_DATA` | raw/API/upload/DB/crawler/public API source 선택 | 원천 선택의 단일 입구 |
| `MAP_FIELDS` | source field → staging/canonical field 매핑 | schema mismatch 를 여기서 검출 |
| `SQL_ASSET_TRANSFORM` | SQL Studio 승인 SQL 호출 | `sql_query_version_id` 기반, APPROVED 만 실행 |
| `SQL_INLINE_TRANSFORM` | 노드 config 에 직접 SQL 작성 | 실험/임시 transform. publish 전 승인 권장 |
| `HTTP_TRANSFORM` | 외부 API/AI 모델 호출 | secret_ref, retry, timeout, output_schema 필수 |
| `FUNCTION_TRANSFORM` | 내부 등록 함수/API 호출 | allowlist 기반. 임의 코드 실행 금지 |
| `OCR_TRANSFORM` | OCR provider registry 호출 | source 별 provider/fallback 선택 |
| `CRAWL_FETCH` | crawler provider registry 호출 | httpx/playwright/external service 선택 |
| `STANDARDIZE` | 도메인별 표준코드/임베딩 매칭 | agri/iot/pharma 등 plugin |
| `DEDUP` | key 기준 중복 제거 | 현재 구조 유지 |
| `DQ_CHECK` | DQ rule 실행 | registry + inline assertion |
| `LOAD_TARGET` | mart/master/fact/dimension 적재 | append/upsert/SCD/current snapshot |
| `NOTIFY` | Slack/Email/Webhook 알림 | outbox 기반 |

`LOAD_TARGET` 는 사용자가 직접 `INSERT` 문을 쓰는 대신, 기본적으로 안전한 load policy 를
선택하게 한다. 고급 사용자의 custom load SQL 은 APPROVED SQL asset 으로만 허용한다.

```yaml
source_table: stg.cleaned_prices
target_table: mart.price_fact
load_policy: append_only   # append_only | upsert | scd_type_2 | current_snapshot
key_columns: [seller_id, product_id, observed_at]
partition_column: observed_at
```

이 방식은 재실행 멱등성, chunked load, audit, rollback, partition, 권한 검사를 플랫폼이
통제하기 위함이다.

### 5.2.3 표준화 엔진 generic 화 [W5~W7]

- [ ] backend/app/domain/standardization/registry.py: 도메인 별 표준화 후보 테이블 +
  embedding 모델 (HyperCLOVA 1536d 외에도 OpenAI ada-002 / 자체 모델 선택 가능)
- [ ] migration: 도메인 별 `<domain>_standard_code` 테이블 + IVFFLAT 인덱스
- [ ] backend/app/domain/standardization/three_stage.py: 3단계 폴백 로직은 그대로,
  pluggable
- [ ] tests: agri 의 식품 매칭 + iot 의 센서 모델명 매칭 — 같은 코드 경로

### 5.2.4 frontend Designer + SQL Studio domain-aware + v2 ETL UX [W7~W9]

**W7~W9 MVP (5.2.6 새 도메인 추가에 *반드시* 필요한 4종):**

- [ ] **Field Mapping UI** ★ — source field tree ↔ target column drag/drop. 타입
  불일치 즉시 표시. (없으면 새 도메인 추가 자체가 불가능.)
- [ ] **Mart Table Designer** ★ — 컬럼/타입/key/partition/load_policy 를 폼으로 정의 +
  migration 초안 생성.
- [ ] **DQ Rule Builder** ★ — null/range/unique/reference/custom_sql 폼. severity +
  timeout.
- [ ] **Run Simulation / Dry-run** ★ — 실제 mart 적재 없이 row_count, DQ 결과, 예상
  load 영향 확인.
- [ ] frontend: 좌측 사이드바에 domain switcher (위 4 page 가 도메인 인지)
- [ ] Designer: 같은 노드 카탈로그, 단 LOAD_TARGET 의 target_table 드롭다운이 선택된
  도메인의 fact 테이블만 보여줌
- [ ] SQL Studio: 같은 sandbox, 단 referenced_tables 검증이 선택된 도메인의 schema 만
  허용
- [ ] PipelineRunsList / PipelineReleases: domain 필터

**Phase 6 (Field Validation) 으로 미루는 후순위:**

- [ ] Source Contract Wizard — JSON 샘플 / OpenAPI snippet → schema 초안. 실제 외부
  공공데이터포털 OpenAPI 1~2개 붙이면서 검증.
- [ ] Lineage View — raw field → staging column → mart column 그래프.
- [ ] Backfill Wizard — 단계형 입력. *실제 backfill 운영 사고가 1번 발생한 후* 가
  더 적합.
- [ ] Pipeline Template Gallery — API polling / webhook / DB incremental / OCR /
  crawler 템플릿. *실 도메인 2~3개 운영 후* 패턴이 명확해진 시점.
- [ ] Error Sample Viewer 고도화 — DQ 실패 sample + rule 한 화면.
- [ ] Node-level Data Preview — 노드 출력 sample + transform diff.
- [ ] Publish Checklist — contract valid / target key / DQ / schedule / performance.
- [ ] SQL Studio Performance Coach — EXPLAIN cost / full scan / partition filter
  / cross join 경고.

#### v2 ETL UX 기본 흐름

사용자는 처음부터 SQL/JSON config 를 직접 만지는 대신, 다음 순서로 파이프라인을 만든다.

```
1. 원천 데이터 선택
   → 2. 샘플/스키마 확인
   → 3. 필드 매핑
   → 4. 정제 방법 선택
   → 5. DQ 설정
   → 6. mart 적재 정책 선택
   → 7. Dry-run
   → 8. Publish
```

| 단계 | 사용자 행동 | 시스템 동작 |
|---|---|---|
| 원천 선택 | API/upload/DB/crawler/public API 선택 | `SOURCE_DATA` 생성 |
| 샘플 확인 | raw payload / first rows 확인 | schema inference + contract 후보 생성 |
| 필드 매핑 | source field 를 target field 로 연결 | `MAP_FIELDS` 생성, type mismatch 표시 |
| 정제 선택 | SQL / 승인 SQL / 외부 API / 내부 함수 / AI 모델 중 선택 | transform 노드 생성 |
| DQ 설정 | null/range/unique/reference/custom_sql rule 선택 | `DQ_CHECK` 생성 |
| mart 적재 | target table, key, partition, load_policy 선택 | `LOAD_TARGET` 생성 |
| Dry-run | 실제 mart 적재 없이 실행 | staging temp + DQ + expected rows |
| Publish | 승인 후 스케줄/수동 실행 가능 | DRAFT → PUBLISHED |

#### 정제 방법 선택지

| 방법 | 노드 | 사용 예 | 가드레일 |
|---|---|---|---|
| SQL Studio 승인 SQL | `SQL_ASSET_TRANSFORM` | 재사용 가능한 정제 SQL | APPROVED 버전만 실행 |
| 임시 SQL | `SQL_INLINE_TRANSFORM` | 빠른 실험/단발 변환 | validate/preview/explain 필수 |
| 외부 API/AI 모델 | `HTTP_TRANSFORM` | 상품명 정제, 주소 정제, LLM/embedding 호출 | secret_ref, timeout, retry, output_schema |
| 내부 정제 함수 | `FUNCTION_TRANSFORM` | 도메인별 품질 코드, 표준화 함수 | registry allowlist, version pin |
| OCR provider | `OCR_TRANSFORM` | 영수증/전단/문서 OCR | provider registry, confidence gate, fallback |
| Crawler provider | `CRAWL_FETCH` | 정적/동적 HTML 또는 외부 크롤링 서비스 | robots/rate limit/provider policy |
| DQ rule | `DQ_CHECK` | row_count/null/unique/range/reference/custom_sql | severity, timeout, sample_limit |

글로벌 도구와의 대응:

| 글로벌 패턴 | v2 대응 |
|---|---|
| Airbyte source/destination connector | `SOURCE_DATA`, `LOAD_TARGET` |
| Airflow operator/task | 노드 카탈로그 (`HTTP_TRANSFORM`, `FUNCTION_TRANSFORM`, `SQL_*`) |
| dbt model/test | `SQL_ASSET_TRANSFORM`, `DQ_CHECK` |
| Great Expectations expectation suite | `domain.dq_rule` + `DQ_CHECK` |
| Dagster software-defined asset | mart target + upstream lineage |

핵심 원칙:

- 정제 노드는 데이터를 바꾸고, DQ 노드는 통과/실패를 판단한다.
- mart 적재는 직접 `INSERT` 보다 `LOAD_TARGET` 설정을 기본으로 한다.
- custom SQL/API/function 은 모두 version, approval, timeout, audit 를 가진다.
- OCR/크롤링은 벤더가 아니라 provider interface 를 기준으로 설계한다. CLOVA/httpx 는 기본
  구현일 뿐, source 별로 다른 provider 로 교체 가능해야 한다.
- Designer 는 최종적으로 DAG 를 만들지만, 사용자는 "원천 → 정제 → 검사 → 적재"의 업무 흐름으로
  이해해야 한다.

### 5.2.5 v1 → v2 plugin 마이그 [W9~W12]

- [ ] `domains/agri.yaml` 작성:
  ```yaml
  domain_code: AGRI
  name: 농축산물 가격
  resources:
    - resource_code: PRICE_FACT
      canonical_table: mart.product_master
      fact_table: mart.price_fact
      standard_code_namespace: AGRI_FOOD
    - resource_code: DAILY_AGG
      fact_table: mart.price_daily_agg
  embedding_model: hyperclova-1536
  channels: [POS_API, DB_INCREMENTAL, CRAWL, OCR_RECEIPT, OCR_LEAFLET, KAMIS, MEAT_API]
  ```
- [ ] backend/app/api/v1/* 의 모든 endpoint 가 내부적으로 v2 generic 엔진 + agri yaml
  사용. *v1 endpoint URL/응답 schema 변경 X.*
- [ ] 회귀 테스트: 모든 v1 통합 테스트 (16+ 파일) 가 동일하게 통과
- [ ] **마이그 검증 — T0 snapshot + checksum + 1주 shadow** (단순 row count 일치 X):
  1. migration 시작 시점 T0 기록.
  2. T0 기준 v1 `mart.price_fact` / `mart.product_master` 의 row_count + content
     checksum (예: `md5(string_agg(...))`) 저장.
  3. v2 registry / compat view 적용.
  4. T0 기준 동일 query 재실행 → row_count + checksum 일치 확인.
  5. 이후 *1주 shadow run* — v1 write path 와 v2 generic path 가 같은 raw 입력에
     대해 동일 결과 (mart row + checksum) 생성하는지 dual-path 비교.
  6. shadow 1주 통과 후 v1 write 비활성화 가능 (단, endpoint 는 그대로).

### 5.2.6 새 도메인 1개 추가 [W12~W15]

5.2.5 끝난 시점에 결정. 사업팀이 원하는 도메인이 있으면 그게 우선. *기술 검증* 만
보면 다음 우선순위:

| 우선순위 | 도메인 | 선정 사유 |
|---|---|---|
| **1순위** | **POS 거래 로그** | 표준 코드 set 작음 (payment_method 5~10종), fact 성격이 다름 (트랜잭션) — generic engine 의 *마트 schema 다양성* 검증에 좋음 |
| 2순위 | IoT 센서 시계열 | 시계열 dense, std_code 가 device_model — *partition 정책 + 시계열 query 패턴* 검증 |
| 3순위 | 부동산 매물 | 지리 인덱스 + 매물 상태 변화 — *검증 강도는 가장 높지만 범위가 큼* (PostGIS 도입 부담) |
| 4순위 | 의약품 가격 | 농축산물과 너무 비슷 — 추상화가 *어쨌든 통과해 버려서 검증 강도 낮음* |

선택된 도메인 (5.2.5 끝난 시점에 확정):
- [ ] `domains/<chosen>.yaml` 작성
- [ ] migration: `<chosen>_mart.*` 테이블 + 도메인 별 standard_code (별도 schema)
- [ ] 샘플 워크플로 1개 + SQL 템플릿 5개 시드 (Phase 3.2.8 패턴)
- [ ] 운영자 매뉴얼 보강 (02_user_manual.html 의 채널 부분에 새 도메인 시나리오 추가)
- [ ] tests: 새 도메인의 end-to-end (SOURCE → STANDARDIZE → LOAD_TARGET → 마트 검증)
- [ ] **추상화 검증 KPI**: 새 도메인 1개 추가에 걸린 시간 측정. 1~2주 = 적정,
  4주+ = 추상화 부족 → 5.2.5 까지의 generic 화 재검토.

### 5.2.7 generic 화 부수 효과 — 외부 API [W15~W16]

- [ ] `/public/v1/*` (Phase 4.2.5) 가 도메인 인지: `/public/v2/{domain}/*`
  - GET `/public/v2/agri/prices/latest`
  - GET `/public/v2/iot/sensors/latest`
  - GET `/public/v2/pos/transactions/latest`
- [ ] **api_key multi-domain scope** (Q9 결정):
  - scope = `["agri.prices.read", "pharma.prices.read", "iot.sensors.read"]` (배열)
  - `domain_resource_allowlist` JSONB 컬럼 신설 — v1 의 `retailer_allowlist` 는
    `agri 전용` 으로 호환 유지하되, v2 는 도메인별 allowlist 키 사용:
    ```json
    {
      "agri": {"retailer_ids": [1,2,3]},
      "pharma": {"vendor_ids": [10,20]},
      "iot": {"device_group_ids": [100]}
    }
    ```
  - 한 api_key 가 여러 도메인 조회 가능 (B2B 고객의 키 관리 부담 회피).
- [ ] migration: `ctl.api_key` 에 `domain_resource_allowlist JSONB` 컬럼 추가.
  v1 의 `retailer_allowlist` 는 *deprecated 표시* + agri 도메인의 자동 매핑.
- [ ] RLS GUC 도 도메인별: `app.<domain>_allowlist` 또는 `app.allowlist_json`
  (단일 GUC 에 JSON 으로 통합 검토 — Phase 4.2.4 ADR-0012 의 후속).
- [ ] OpenAPI 별도 docs 도 도메인 별 분리 (`/public/v2/{domain}/docs`)

### 5.2.8 Performance & Scalability [W15~W17]

v2 는 도메인/소스/테이블 수가 늘어나는 제품이다. 사용자의 자유도를 열어주는 만큼, 성능을
망가뜨리는 설계를 사전에 막아야 한다.

#### 수집 성능

- [ ] source 별 `poll_interval`, `batch_size`, `max_concurrency`, `rate_limit_per_min` 정의.
- [ ] API polling 은 `updated_at`/cursor 기반 watermark 필수. full scan polling 금지.
- [ ] raw JSON 은 64KB 기준 inline, 대용량 payload 는 Object Storage 우선.
- [ ] `raw.raw_object` 는 partition 유지. source_id + received_at + partition_date 조회 패턴 최적화.
- [ ] ingest p95 latency / rows/sec / dedup hit rate 를 source/domain label 로 노출.

#### Worker / Queue 성능

- [ ] queue 분리: ingest / transform / dq / load / notification / backfill.
- [ ] domain/source 별 worker routing 가능. OCR/AI 같은 heavy job 은 별도 queue.
- [ ] Redis Streams consumer lag, retry count, DLQ count, job duration p95 대시보드화.
- [ ] backpressure 정책: lag 임계 초과 시 polling throttle, backfill pause, low-priority queue 지연.
- [ ] Kafka 도입 조건 문서화: Redis lag 지속, 장기 replay 필요, 외부 stream 제공, CDC 대규모화.

#### DB / Schema 성능

- [ ] fact/current/history table 생성 시 partition key 와 primary/business key 필수 검토.
- [ ] append-only fact 는 event_time/observed_at/run_date 기준 partition 권장.
- [ ] 자주 필터링되는 컬럼 인덱스 추천. JSONB 는 raw 보존용, 분석용 필드는 컬럼화 권장.
- [ ] mart table publish 전 estimated row size, index count, partition policy, retention policy 확인.
- [ ] 대용량 target 에 대한 LOAD_TARGET 은 chunked insert/upsert 와 statement timeout 적용.

#### DQ / SQL 성능

- [ ] DQ rule 별 `timeout_ms`, `sample_limit`, `max_scan_rows`, `incremental_only` 옵션.
- [ ] full table DQ 와 incremental partition DQ 구분. 기본은 최근 partition / changed rows.
- [ ] custom_sql 은 SQL Studio EXPLAIN + 위험 패턴 검사 통과 후 publish 가능.
- [ ] profiling 은 sample 기반으로 시작하고, heavy profiling 은 Airflow batch 로 분리.
- [ ] 실패 row sample 저장은 최대 N건 제한.

#### Backfill 성능

- [ ] 날짜 범위 backfill 은 chunk 로 쪼개고, chunk 별 checkpoint/resume 제공.
- [ ] 운영 시간대 throttle, max_parallel_runs, domain priority 설정.
- [ ] dry-run 에서 예상 row 수, 예상 duration, target partitions, DQ cost 를 표시.

#### 성능 SLO 초안

| 지표 | 초기 목표 |
|---|---|
| ingest API p95 latency | 300ms 이하 (Object Storage 업로드 제외) |
| raw insert throughput | 로컬 기준 1,000 rows/min baseline 측정 |
| Redis Streams consumer lag | steady state 1분 이하 |
| pipeline node state SSE delay | p95 1초 이하 |
| SQL preview | 5초 timeout + LIMIT 강제 |
| DQ custom_sql | 기본 30초 timeout |
| backfill | chunk 단위 재시작 가능, 전체 실패 시 처음부터 재실행 금지 |

### 5.2.9 운영팀 onboarding 갱신 [W17~W18]

- [ ] 합류 자료 5종 (CURRENT.md) 의 docs/onboarding/* 갱신:
  - 도메인 추가 절차 (yaml + migration + seed)
  - 도메인 별 표준화 임계 튜닝
  - source contract / field mapping / DQ rule / mart designer 사용법
  - 성능 가드레일: partition, index, EXPLAIN, backfill throttle
  - Phase 4 의 owner 매트릭스 → 도메인 owner 추가
- [ ] ADR-0018: v2 generic 결정 회고

---

## 5.3 비즈니스 가치

| 시나리오 | v1 추정 비용 | v2 추정 비용 |
|---|---|---|
| 새 도메인 (예: 의약품 가격) 추가 | 5~8주 (코드 + 마이그 + 테스트) | 1~2주 (yaml + seed + 검증) |
| 기존 도메인의 새 채널 추가 | 1~2주 | 0.5주 (config 변경) |
| 표준화 임계 도메인 별 튜닝 | 코드 변경 + redeploy | DB row 1개 update |

운영팀이 자율적으로 새 도메인을 추가할 수 있게 되면 매주 1개 도메인씩 + 4분기에 12개 도메인
가능 — 회사가 *플랫폼 비즈니스* 로 전환.

---

## 5.4 위험 + 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| v1 회귀 | 운영 중인 농축산물 데이터 손상 | 마이그 단계마다 회귀 테스트 + shadow 트래픽 1주 |
| 너무 많은 추상화 | 코드 복잡도 ↑, 유지보수 ↓ | 첫 새 도메인 (5.2.6) 까지만 추상화, 그 이후는 "추가" 만 |
| 도메인 간 격리 부족 | 한 도메인의 SQL 이 다른 도메인 mart 접근 | v1 (agri legacy) 는 `mart.*` 그대로 / 신규 도메인은 `<domain>_mart`/`<domain>_stg` 별도 schema. sqlglot 의 ALLOWED_SCHEMAS 가 *현재 컨텍스트의 도메인* + agri legacy schema 만 허용 |
| pgvector 차원 통일 압박 | HyperCLOVA 1536, OpenAI 3072 등 차원 다름 | 도메인 별 별도 vector 테이블 + 인덱스 — 같은 테이블에 강제 통일 안 함 |
| 운영팀 학습 곡선 | yaml 작성 + 도메인 등록 절차 학습 비용 | 5.2.9 의 onboarding 자료 + Designer UI 의 마법사 |
| 사용자가 만든 SQL/DQ 가 DB 를 압박 | slow query, lock wait, 장애 | SQL Studio performance coach + timeout + max_scan_rows + approval |
| backfill 폭주 | worker/DB backlog 급증 | chunking + max_parallel_runs + throttle + checkpoint resume |
| API polling 과다 | partner API 차단 / 비용 증가 | source 별 rate limit + watermark + exponential backoff |
| mart schema 난립 | 운영/비용/쿼리 복잡도 증가 | domain registry review + naming convention + lifecycle/retention 정책 |
| Kafka 조기 도입 | 운영 복잡도 ↑ | Redis Streams baseline 초과 조건을 만족할 때만 ADR 로 결정 |

---

## 5.5 Phase 5 진입 조건

다음이 모두 충족돼야 Phase 5 시작 권장:

- [ ] Phase 4 DoD 5종 모두 ✅
- [ ] **v1 이 회사 서버 staging 또는 prod-like 환경에서 1개월 무사고 가동**
  (NKS 필수 X — 5.0A 의 현실 배포 순서 우선. NKS 이관 후에는 같은 기준을 NKS 에서
  재검증.)
- [ ] 운영팀이 Phase 4 owner 영역에서 자율 운영 (의존 0) — 인원 수와 무관.
- [ ] 새 도메인 추가 요청이 사업 측에서 들어옴 (POS / IoT / 의약품 / 부동산 등)
- [ ] v1 의 매출/외부 API 활동 안정 (Phase 5 작업 중에도 v1 운영 영향 0 보장)
- [ ] Phase 4 성능 baseline 측정 완료 — ingest, worker lag, SQL preview, pipeline run,
  DQ duration, mart load rows/sec.
- [ ] v2 개발 브랜치 정책 확정 — 같은 repo, v1 보존, `/v2` prefix, rollback 절차.

위 조건이 안 갖춰진 상태에서 Phase 5 시작은 *조기 추상화* 위험.

---

## 5.6 Phase 5 종료 후 — Phase 6 실증

Phase 5 가 끝나면 곧바로 **Phase 6 — Field Validation** 으로 넘어간다. 목표는 v2 generic
설계가 실제 외부 데이터와 사용자 업로드에서도 동작하는지 검증하는 것이다.

참조: [`PHASE_6_FIELD_VALIDATION.md`](./PHASE_6_FIELD_VALIDATION.md)

Phase 6 핵심 검증:

- 실제 공공데이터포털 OpenAPI 1~2개 수집.
- 사용자 업로드 샘플 페이지 제공.
- API 데이터와 업로드 데이터를 같은 v2 공정으로 raw → staging → DQ → mart 처리.
- 실증 결과를 Phase 5 generic schema / Designer UX / 성능 가드레일 보정 backlog 로 환류.

---

## 부록 — 변경되는 파일/테이블 추정

### Migration 추가 (Phase 5 한정)

번호는 **현재 Alembic head 기준 다음 번호부터** 시작. Phase 4 종료 시점 head =
`0029_master_merge.py` 이므로 Phase 5 는 `0030_*` 부터.

| Migration | 설명 |
|---|---|
| `0030_domain_schema.py` | `domain.*` schema 신설 |
| `0031_resource_definition.py` | domain 별 resource 등록 (v1 mart 테이블도 등록) |
| `0032_standard_code_namespace.py` | 도메인 별 std_code namespace |
| `0033_source_contract_and_mapping.py` | source × domain × resource × version contract + field mapping |
| `0034_load_policy_and_dq_rule.py` | load policy / DQ rule registry |
| `0035_provider_registry.py` | OCR/CRAWLER/AI/HTTP provider registry + source binding |
| `0036_v1_to_v2_compat_views.py` | v1 endpoint 호환 view + Phase 4 RLS view 와 통합 |
| `0037_api_key_multi_domain_scope.py` | `ctl.api_key.domain_resource_allowlist` JSONB 추가 |
| `0038+` | 새 도메인 1~N 의 mart 테이블 (`<domain>_mart.*` schema) |

> **주의**: 위 번호는 *Phase 4 종료 직후* 기준. Phase 4 와 Phase 5 사이에 hot-fix
> migration 이 들어가면 Phase 5 시작 시점에 *현재 head 기준 다음 번호로 재계산* 필요.
> 부록의 고정 번호는 가이드일 뿐이며, 실제 PR 시점의 head 를 따른다.

### Backend 모듈 추가

```
backend/app/domain/
  registry.py              # 도메인 yaml → ORM 동적 로드
  contracts.py             # source schema/version/compatibility
  mappings.py              # source field → target field mapping
  load_policy.py           # append/upsert/SCD/current snapshot
  dq_registry.py           # DQ rule registry + execution plan
  providers.py             # OCR/CRAWLER/AI/HTTP provider registry
  provider_factory.py      # provider_code → implementation 생성
  standardization/
    registry.py            # 도메인별 embedding 모델
    three_stage.py         # 폴백 (pluggable)
  domains/
    agri/                  # v1 logic 을 plugin 으로
    iot/                   # 새 도메인
    ...
```

### Frontend

| 위치 | 변경 |
|---|---|
| `App.tsx` | 도메인 router (`/v2/{domain}/...`) |
| `components/Layout.tsx` | 좌측 사이드바에 domain switcher |
| `pages/PipelineDesigner.tsx` | LOAD_TARGET 의 target_table 드롭다운 도메인 별 |
| `pages/SqlStudio.tsx` | referenced_tables 검증이 도메인 인지 |
| `pages/DomainsPage.tsx` (신규) | ADMIN 의 도메인 등록/관리 |
| `pages/ContractsPage.tsx` (신규) | source schema / version / compatibility 관리 |
| `pages/MappingDesigner.tsx` (신규) | source field → staging/mart field 매핑 |
| `pages/MartDesigner.tsx` (신규) | mart table / key / partition / load policy 설계 |
| `pages/DqRuleBuilder.tsx` (신규) | DQ rule registry 관리 |
| `pages/LineageView.tsx` (신규) | raw → stg → mart lineage 시각화 |

---

## 마무리

**Phase 5 는 코드 양보다 설계 토론이 더 중요한 단계.** 추상화 한 단계 잘못 두면 6개월 뒤
*어차피 농축산물밖에 안 쓰니 generic 화는 무리수였다* 가 되거나, 너무 적게 두면 새 도메인
하나 추가에 또 다시 8주 걸리는 결과.

본 phase 의 핵심 의사결정은 **5.2.6 (새 도메인 1개 추가)** 시점에서 자연스럽게 검증됨 —
1주 안에 새 도메인 추가가 가능해지면 추상화가 적절. 4주 걸리면 추상화 부족.

Phase 4 종료 후 사업 측에서 *어떤 도메인이 시급한가* 가 명확해진 시점에 본 phase 시작.
