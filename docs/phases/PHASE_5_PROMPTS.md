# Phase 5 — 단계별 실행 프롬프트 (복사-붙여넣기 용)

본 문서는 [PHASE_5_GENERIC_PLATFORM.md](./PHASE_5_GENERIC_PLATFORM.md) 의 12개 단계를
실제 실행할 때 사용자가 그대로 복사해 Claude 에 붙여넣을 수 있는 프롬프트 모음.

각 프롬프트는 다음 형식:

```
PHASE_5_*.md X.X.X '제목' 을 구현해.

진행 전 다음을 먼저 확인하고 답을 받은 뒤 진행해:
- Q1. ...
- Q2. ...

기능:
- ...

Acceptance:
- ...

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

**Claude 사용 패턴:**
1. 사용자가 STEP N 프롬프트 복사 → 붙여넣기
2. Claude 가 *사전 확인 질문* 먼저 물음 (3~7개)
3. 사용자 답변
4. Claude 가 자동 모드로 실행 → 단일 commit + push
5. Claude 가 STEP N+1 프롬프트 제안

---

## 실행 순서 한눈에 보기

| # | 단계 | 기간 | 선결조건 |
|---|---|---|---|
| 0 | **사전 준비 체크리스트** | — | Phase 4 완료 |
| 1 | 5.2.1a Dynamic Resource Registry **Spike** | 1주 | STEP 0 |
| 2 | 5.2.0 사용자 설계 모델 + 가드레일 | 1~2주 | STEP 1 (ADR-0017) |
| 3 | 5.2.1 generic schema 추상화 (`domain.*`) | 2~3주 | STEP 1, 2 |
| 4 | 5.2.1.1 OCR/Crawler Provider Registry | 2~3주 | STEP 3 (provider 테이블) |
| 5 | 5.2.2 노드 타입 generic 화 (7→13+) | 2~3주 | STEP 3, 4 |
| 6 | 5.2.3 표준화 엔진 generic 화 | 2주 | STEP 3 |
| 7 | 5.2.4 ETL UX MVP 4종 | 2~3주 | STEP 3, 5 |
| 8 | 5.2.5 v1 → v2 plugin (agri.yaml) | 3주 | STEP 3, 5, 7 |
| 9 | **5.2.6 새 도메인 1개 추가 ★ 추상화 검증** | 3주 | STEP 8 (shadow 1주 통과) |
| 10 | 5.2.7 외부 API 도메인 인지 | 1~2주 | STEP 9 |
| 11 | 5.2.8 성능 & 확장성 가드레일 | 2~3주 | STEP 9 |
| 12 | 5.2.9 운영팀 onboarding 갱신 + ADR-0018 | 2주 | STEP 9, 10, 11 |

---

## STEP 0 — 사전 준비 체크리스트

Phase 5 *시작 전* 사용자가 직접 확인/결정할 사항. Claude 가 묻기 전에 명확히.

```
Phase 5 시작 전, 다음 항목들을 점검하고 답해줘. 답이 안 된 항목이 있으면 Phase 5
진입을 보류해야 해.

[A. v1 안정성]
- v1 이 회사 서버 staging 또는 prod-like 환경에서 1개월 무사고 가동되었는가? (Y/N)
- v1 의 핵심 운영 지표 (ingest p95, worker lag, DLQ pending) 가 baseline 측정되었는가?
- 회사 서버 staging 의 docker-compose / nginx / SSL / .env 가 정리되어 있는가?

[B. 사업측 시그널]
- 새 도메인 추가 요청이 사업측에서 확정되었는가? 어느 도메인인가?
  ( ) POS 거래 로그       ( ) IoT 센서 시계열
  ( ) 의약품 가격         ( ) 부동산 매물
  ( ) 사업팀 미정 — 기술 검증 기준 (POS 1순위) 으로 진행
- 사업측 요구 timeline 이 있는가? (예: 분기말까지 새 도메인 1개 PoC)

[C. 운영팀 / 인원]
- Phase 5 작업에 투입 가능한 인원은 몇 명인가?
- 운영팀이 Phase 4 owner 영역에서 자율 운영 중인가? (의존 0)

[D. v2 브랜치 정책]
- v2 작업을 `feature/v2-generic-platform` 브랜치에서 진행 OK?
- v1 endpoint / mart schema / 운영 화면을 *Phase 5 기간 동안 변경 금지* 정책에 동의?
- main 의 현재 Alembic head 는 0029_master_merge 인가? (Phase 5 migration 은 0030~)

[E. 기술 결정 (5.2.1a Spike 전)]
- ORM 전략 후보 중 *기본 추천* 으로 진행 OK?
  → Hybrid: v1 ORM 유지 + v2 generic = SQLAlchemy Core + reflected Table
- 위 추천이 spike 1주에서 검증되지 않으면 *다른 옵션 (A: 동적 ORM / B: Core only)*
  으로 전환할 의사가 있는가?

[F. Phase 5 산출물 commit 정책]
- 각 STEP 마다 단일 commit + push 를 main 이 아닌 feature 브랜치에 진행 OK?
- main 으로의 merge 는 STEP 8 (v1 마이그) shadow run 1주 통과 후 진행?

위 6개 항목 중 미확정인 것 답해줘. 모두 명확하면 STEP 1 (5.2.1a Spike) 프롬프트 보내.
```

---

## STEP 1 — 5.2.1a Dynamic Resource Registry **Spike** (1주)

**목적**: ORM 전략 결정 + ADR-0017 + 가짜 도메인 PoC. 본격 5.2.1 진입 전 *가장 큰 기술 위험 제거*.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.1a 'Dynamic Resource Registry Spike' 를 구현해.

진행 전 다음을 먼저 확인:
- Q1. ORM 옵션 A/B/C 중 *우선 검증* 할 것은? (기본 추천 = C Hybrid)
- Q2. spike 산출물의 PoC 도메인 이름은? (기본: `iot_spike` schema 임시 생성 후 정리)
- Q3. ADR-0017 의 *결론* 을 spike 결과와 동시에 commit 할지, spike 후 별도 turn 으로 할지?
- Q4. spike 코드는 production 코드에 남길지, `experimental/` 아래에 임시로 둘지?
       (기본: backend/app/experimental/registry_spike.py 로 격리, ADR 만 main 산출)

기능:
- 옵션 A — SQLAlchemy ORM 동적 클래스 생성:
  - yaml → `type()` declarative class
  - Alembic autogenerate 호환성 검증
  - 한계: typed Mapped column / mypy 호환 / SQLAlchemy registry conflict
- 옵션 B — SQLAlchemy Core + reflected Table:
  - `MetaData.reflect()` + registry metadata 기반 query builder
  - 한계: ORM 의 lazy loading / relationship 못 씀
- 옵션 C — Hybrid:
  - v1 (정적 도메인) = ORM 유지
  - v2 generic resource = Core + reflected Table
  - 도메인별 vector 테이블도 Core 기반 query builder
- 가짜 도메인 PoC — `iot_spike_mart.sensor_v1` schema → SELECT/INSERT/JOIN 동작 검증
- Alembic migration 생성 정책 검증 — yaml 변경 시 어떻게 migration 생성?

산출물:
- backend/app/experimental/registry_spike.py — 옵션 A/B/C 의 *최소 동작 코드*
- migrations/versions/0030_spike_iot.py — spike 용 (롤백 전제)
- docs/adr/0017-resource-registry-orm-strategy.md — A/B/C 비교 + 채택 사유 + 회수 조건
- 회귀: 기존 v1 통합 테스트 100% 통과 (spike 가 v1 깨뜨리지 않음)

Acceptance:
- Hybrid (옵션 C) 가 가짜 도메인의 SELECT/INSERT/JOIN 모두 동작
- ADR-0017 에 옵션 A/B/C 의 트레이드오프 명시 + 채택 옵션 + 회수 조건 (= 다음 옵션
  으로 전환할 트리거)
- v1 회귀 테스트 100% 통과
- spike migration 0030 은 *spike 종료 시 downgrade 가능* 하도록 작성

자동 모드. 단일 commit + push 후 STEP 2 (5.2.0) 명령어 제안.
```

---

## STEP 2 — 5.2.0 사용자 설계 모델 + 가드레일 (1~2주)

**목적**: 사용자가 직접 설계할 수 있는 8개 항목 + 가드레일 7종 정의.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.0 '사용자 설계 모델 + 가드레일' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. 가드레일 7종 중 *Phase 5 안에 모두* 구현할지, 일부는 Phase 6 로 미룰지?
       (예: SQL Performance Coach 는 Phase 6 의도 = 5.2.4 MVP 와 일치)
- Q2. mart 변경 상태머신 (DRAFT→REVIEW→APPROVED→PUBLISHED) 을 어디에 적용?
       ( ) mart 변경만 ( ) mart + source contract + DQ rule 모두
- Q3. DROP/DELETE/TRUNCATE 차단의 적용 범위?
       ( ) custom SQL 전체 ( ) v2 만 ( ) v2 + v1 의 SQL Studio 도 강화
- Q4. domain registry review 의 승인자는? ADMIN 1명 또는 APPROVER 다중 승인?

기능:
- 사용자 설계 가능 항목 8종 *카탈로그* 정의 (DB schema 미반영, 정의만):
  Source schema / Field mapping / Staging / Mart / Key/constraint / Load policy /
  DQ rule / Schedule/backfill
- 가드레일 7종 구현:
  1. 허용 schema 외 SQL 접근 차단 — sqlglot ALLOWED_SCHEMAS 동적 (도메인 인지)
  2. DROP/DELETE/TRUNCATE/외부 파일 함수 등 destructive SQL 차단
  3. mart 변경 상태머신 DRAFT→REVIEW→APPROVED→PUBLISHED
  4. source schema 변경 = versioning + backward compat check
  5. DQ custom SQL = preview/explain + timeout + max_scan_rows 통과 시 publish
  6. LOAD_TARGET 은 domain registry 등록 테이블만
  7. domain registry review 워크플로 (ADMIN 승인)
- ADR-0017 의 결정 (Spike 결과) 을 본격 적용한 첫 번째 단계
- backend/app/domain/guardrails/ 신규 모듈
- 가드레일 단위 테스트 7~10개

Acceptance:
- v1 의 sqlglot ALLOWED_SCHEMAS 가 *도메인 인지* 로 동작 (현 컨텍스트의 도메인 +
  agri legacy schema 만 허용)
- DROP TABLE / TRUNCATE / DELETE FROM 같은 SQL 이 v2 라우트에서 차단 (403/422)
- mart 변경 PR 시 PUBLISHED 까지 가는 상태머신 통과 검증
- v1 회귀 100% 통과

자동 모드. 단일 commit + push 후 STEP 3 (5.2.1) 명령어 제안.
```

---

## STEP 3 — 5.2.1 generic schema 추상화 `domain.*` (2~3주)

**목적**: domain registry 의 *코어 스키마* + v2 API 스켈레톤.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.1 'generic schema 추상화' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. migration 번호 — 현재 head 가 0029 면 0030 이 spike 용으로 사용되었는가?
       Spike migration 을 downgrade 후 0030~0036 으로 재사용할지, 0031~0037 로 미뤄
       사용할지?
- Q2. domain.* schema 의 권한 — Phase 4.2.4 의 4 PG role 중 어디에 GRANT?
       (기본 추천: app_rw 만 RW, app_mart_write 는 RO, app_public/app_readonly 는 접근 X)
- Q3. resource_selector_json 의 형식 표준화 — JSONPath / endpoint match / payload.type
       3가지 중 어느 것을 1차 지원? (3가지 모두 지원 시 우선순위 룰 필요)
- Q4. /v2 라우트의 인증 — Phase 4.0.5 의 require_roles 그대로? 아니면 v2 전용 권한
       (예: DOMAIN_ADMIN, RESOURCE_OWNER) 추가?
- Q5. compatibility_mode 옵션 — backward / forward / full / none 4가지 중 default?
       (Avro/Confluent 표준 따라 기본 backward 추천)

기능:
- migration 0030~0036 (또는 0031~0037, 위 Q1 결정 따라):
  - `0030_domain_schema.py` — domain.* schema 신설
  - `0031_resource_definition.py` — domain_definition / resource_definition /
    standard_code_namespace
  - `0032_source_contract.py` — source_contract (source × domain × resource × version
    복합 UNIQUE) + resource_selector_json
  - `0033_field_mapping_and_load_policy.py` — field_mapping + load_policy
  - `0034_dq_rule_registry.py` — dq_rule
  - `0035_provider_registry.py` — provider_definition + source_provider_binding
  - `0036_v1_compat_views.py` — v1 endpoint 호환 view (Phase 4.2.4 RLS view 와 통합)
- backend/app/models/domain.py — ORM (정적 — Spike 결과 따라 ORM/Core 혼용)
- backend/app/domain/registry.py — yaml → registry 로드 (Spike 결과 적용)
- backend/app/api/v2/domains.py — domain CRUD (ADMIN)
- backend/app/api/v2/contracts.py — source_contract CRUD + compatibility check +
  resource_selector validation
- backend/app/api/v2/mappings.py — field_mapping CRUD + sample payload validation
- backend/app/api/v2/providers.py — provider CRUD + source binding + health
- tests/integration/test_domain_registry.py:
  - agri 도메인을 domain.* 에 등록 (canonical_table='mart.product_master' 그대로)
    → v1 mart.price_fact 가 그대로 보임 + v1 회귀 0
  - 한 source 가 (agri, PRICE) + (pharma, PRICE) 동시 contract — resource_selector
    가 raw payload 를 올바르게 분기
  - source schema v1 → v2 backward / forward / breaking 판정

Acceptance:
- domain.* 7개 테이블 적용 + Phase 4.2.4 의 RLS 정책 매트릭스 충돌 없음
- agri.yaml 로드 후 v1 mart.product_master / mart.price_fact 가 v2 generic engine
  통해 조회 가능
- 한 raw_object 가 도메인별로 다른 contract 로 평가되는 분기 통과
- v1 회귀 100% 통과

자동 모드. 단일 commit + push 후 STEP 4 (5.2.1.1 Provider Registry) 명령어 제안.
```

---

## STEP 4 — 5.2.1.1 OCR / Crawler Provider Registry (2~3주)

**목적**: v1 의 OcrProvider / CrawlerSpider 추상화를 *DB 설정으로* 끌어올림.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.1.1 'OCR / Crawler Provider Registry' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. provider_kind 4종 (OCR / CRAWLER / AI_TRANSFORM / HTTP_TRANSFORM) 모두 Phase 5
       에서 구현? AI_TRANSFORM 은 Phase 6 으로 미루고 OCR / CRAWLER / HTTP_TRANSFORM
       만 먼저?
- Q2. v1 의 기존 OcrProvider chain (CLOVA → Upstage) 을 *완전 제거* 하고 registry 기반으로
       옮길지, *호환 mode* 로 두 path 공존시킬지?
       (기본 추천: shadow 1주 후 v1 path 제거)
- Q3. external_api 형 provider 의 secret 관리 — APP_*_API_KEY env 그대로 사용? 아니면
       provider 별 secret_ref 를 ctl.secrets 같은 별도 테이블에 보관?
- Q4. circuit breaker 라이브러리 — pybreaker / 자체 구현?
- Q5. fallback 정책 — retry 횟수 + circuit breaker open 시간 + retry-after 응답
       header 처리 정책의 default 값?

기능:
- migration `<head+1>_provider_registry_seed.py` — v1 의 CLOVA/Upstage/HttpxSpider 를
  default provider 로 seed
- backend/app/domain/providers.py — provider_kind 별 abstract interface
- backend/app/domain/provider_factory.py — provider_code → implementation 인스턴스
- v1 의 worker 들 (`ocr_worker`, `crawler_worker`) 을 registry 기반으로 refactor —
  단, *기존 동작 회귀 0* 보장 (shadow mode 1주 후 cutover)
- circuit breaker — provider 별 실패율 임계 초과 시 OPEN, retry_after 후 HALF_OPEN
- frontend/src/pages/ProvidersPage.tsx — provider 목록 + health status + circuit
  breaker 상태 (ADMIN)
- tests:
  - 같은 OCR raw_object 를 clova mock / upstage mock / external_api mock 으로 교체 실행
  - 같은 crawl source 를 httpx mock / playwright mock / external mock 으로 교체 실행
  - circuit breaker OPEN 시 fallback provider 자동 사용

Acceptance:
- OCR worker 가 source 별 binding 에 따라 provider 선택 (코드 변경 0)
- v1 의 영수증 OCR 통합 테스트 100% 통과 (회귀 0)
- circuit breaker 가 5xx 연속 5건 시 OPEN → 60초 후 HALF_OPEN
- ProvidersPage 에서 운영자가 provider 우선순위 변경 → 즉시 다음 요청에 반영

자동 모드. 단일 commit + push 후 STEP 5 (5.2.2 노드 generic) 명령어 제안.
```

---

## STEP 5 — 5.2.2 노드 타입 generic 화 (7→13+) (2~3주)

**목적**: v1 의 7노드 카탈로그를 v2 의 13+노드 generic 카탈로그로 확장.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.2 '노드 타입 generic 화' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. v1 의 기존 워크플로 처리 — 자동 마이그? 아니면 v1 워크플로는 그대로 두고 v2 만
       신규 카탈로그?
       (강한 추천: v1 워크플로 자동 마이그 X. 기존 SOURCE_API/SQL_TRANSFORM/LOAD_MASTER
        는 그대로. v2 신규 워크플로만 새 카탈로그 사용. 5.2.5 단계에서 점진 마이그.)
- Q2. SQL_INLINE_TRANSFORM 과 SQL_ASSET_TRANSFORM 의 분리 정책 — APPROVED SQL 만
       프로덕션 가능 / DRAFT/INLINE 은 sandbox 만? 아니면 INLINE 도 publish 가능?
- Q3. HTTP_TRANSFORM 의 secret_ref — 4번 step 에서 정한 secret 관리 방식 그대로?
- Q4. FUNCTION_TRANSFORM 의 allowlist — 어떤 함수들을 1차 등록? (예: 주소 정제,
       전화번호 normalize, 한글 자모 분리, 날짜 parse 등)
- Q5. STANDARDIZE 노드 — 도메인별 standard_code_namespace 와 결합. 임베딩 차원 다른
       경우 동적 로딩 어떻게?

기능:
- 신규 노드 6종:
  - MAP_FIELDS — source contract 기반 raw payload → staging 컬럼화
  - SQL_INLINE_TRANSFORM — 노드 안에 직접 SQL (실험/임시)
  - SQL_ASSET_TRANSFORM — APPROVED sql_query_version_id 호출
  - HTTP_TRANSFORM — 외부 API/AI/주소정제 호출 (secret_ref + retry + timeout)
  - FUNCTION_TRANSFORM — registry allowlist 기반 내부 함수
  - OCR_TRANSFORM — provider registry (5.2.1.1) 결합
  - CRAWL_FETCH — provider registry 결합
  - STANDARDIZE — 도메인별 std_code 매칭
- 기존 노드 generic 화:
  - SOURCE_API → SOURCE_DATA (resource-agnostic, source_id + raw_object_type)
  - LOAD_MASTER → LOAD_TARGET (load_policy 기반: append/upsert/SCD2/snapshot)
  - DEDUP / DQ_CHECK / NOTIFY — generic 호환만 보강
- backend/app/domain/nodes_v2/* 신규 모듈 — v1 nodes 코드 변경 없이 *옆에* 추가
- backend/app/workers/pipeline_node_v2_worker.py — v2 노드 dispatch
- frontend Designer 의 노드 카탈로그 v2 토글 (선택적 — v2 워크플로만 새 카탈로그 노출)
- tests:
  - 같은 워크플로 그래프가 agri / pos 두 도메인에서 동작 (shadow 도메인)
  - LOAD_TARGET 의 4가지 load_policy 모두 검증 (append / upsert / SCD2 / snapshot)
  - HTTP_TRANSFORM 의 timeout / retry / circuit breaker 동작
  - MAP_FIELDS 가 type mismatch 를 정확히 검출

Acceptance:
- v1 워크플로 (7 노드) 100% 회귀 통과
- v2 워크플로 1개를 만들어 13+ 노드 모두 사용해 e2e 통과
- LOAD_TARGET 의 멱등성 (재실행 시 row 중복 X) 보장

자동 모드. 단일 commit + push 후 STEP 6 (5.2.3 표준화 generic) 명령어 제안.
```

---

## STEP 6 — 5.2.3 표준화 엔진 generic 화 (2주)

**목적**: 도메인별 vector 테이블 + embedding 모델 pluggable.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.3 '표준화 엔진 generic 화' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. 1차 지원 embedding 모델 — HyperCLOVA 1536d (v1) 외에 어떤 것?
       ( ) OpenAI ada-002 (1536d)   ( ) OpenAI text-embedding-3-large (3072d)
       ( ) 자체 모델 (커스텀 차원)  ( ) 확장 미정
- Q2. 도메인별 vector 테이블 명명 규칙 — `<domain>_mart.<resource>_embedding` 권장.
       동의?
- Q3. 3단계 폴백 (alias → trigram → embedding) 의 임계값 — 도메인별 다르게? 아니면
       전역 default 후 도메인별 override?
- Q4. 임베딩 호출 비용 — 도메인별 monthly budget cap 을 두는가?

기능:
- backend/app/domain/standardization/registry.py — 도메인별 embedding model 정의
- backend/app/domain/standardization/three_stage.py — 3단계 폴백 로직 *그대로 유지*,
  pluggable 만 추가
- migration: 도메인별 `<domain>_mart.<resource>_embedding` 테이블 + IVFFLAT 인덱스
  생성 helper (yaml → migration 자동 생성 — Spike 결정 따라)
- v1 의 standardization 코드를 *registry 기반* 으로 리팩토링 (기존 동작 회귀 0)
- tests:
  - agri 의 식품 매칭 + pos 의 결제수단 매칭 — 같은 코드 경로
  - 임베딩 차원이 다른 두 도메인 동시 동작
  - 3단계 폴백 단계별 정확성

Acceptance:
- v1 의 농축산물 표준화 100% 회귀
- 가짜 도메인 (POS / IoT) 의 임베딩 매칭이 동일 코드 경로로 동작
- 도메인별 vector 테이블의 IVFFLAT 인덱스 생성 후 검색 < 100ms

자동 모드. 단일 commit + push 후 STEP 7 (5.2.4 ETL UX MVP) 명령어 제안.
```

---

## STEP 7 — 5.2.4 ETL UX MVP 4종 (2~3주)

**목적**: 새 도메인 추가에 *반드시* 필요한 frontend 4종.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.4 'ETL UX MVP — Field Mapping / Mart Designer /
DQ Rule Builder / Dry-run' 4종 만 구현해.

진행 전 다음을 먼저 확인:
- Q1. domain switcher 의 권한 모델 — 한 user 가 여러 도메인 권한 가질 수 있는가?
       ( ) Yes — user × domain 권한 매트릭스
       ( ) No — user 는 1 도메인만 (단순)
- Q2. Mart Designer 의 migration 초안 — 자동 생성 후 ADMIN 승인? 아니면 PR 로 검토?
- Q3. DQ Rule Builder 의 custom_sql — sandbox 검증을 어디서? SQL Studio 와 통합?
       아니면 DQ Rule Builder 안에 별도 preview 영역?
- Q4. Dry-run 의 *실제 mart 적재 없이* 어떻게 row_count 추정? (EXPLAIN ANALYZE 의
       cost?  실제 실행 후 트랜잭션 rollback?)
       (기본 추천: 트랜잭션 rollback 으로 정확한 row_count + DQ 결과 산출)
- Q5. Phase 6 으로 미루는 후순위 8종 (Lineage / Backfill Wizard / Performance Coach /
       Template Gallery / Error Sample Viewer / Source Wizard / Node Preview /
       Publish Checklist) 중 *지금 너무 필요해서 미룰 수 없는 것* 이 있는가?

기능 (MVP 4종):
- Field Mapping UI:
  - source field tree (JSONPath) ↔ target column 의 drag/drop
  - 타입 불일치 즉시 표시 (number → text 등)
  - sample payload 1건으로 dry validate
- Mart Table Designer:
  - 컬럼 / 타입 / key / partition / load_policy 폼
  - migration 초안 SQL 생성 + diff 미리보기 + 가드레일 통과 여부
- DQ Rule Builder:
  - null / range / unique / reference / custom_sql 폼
  - severity / timeout / sample_limit
  - custom_sql 은 SQL Studio sandbox 와 동일 EXPLAIN/preview 통과 후 publish
- Run Simulation / Dry-run:
  - 실제 mart 적재 없이 트랜잭션 rollback 기반
  - row_count / DQ 결과 / load 영향 (예상 update/insert 수) 표시
  - 추정 duration

산출:
- frontend/src/pages/v2/{FieldMappingDesigner,MartDesigner,DqRuleBuilder,DryRunResults}.tsx
- frontend/src/api/v2/{contracts,mappings,mart,dq}.ts
- backend/app/api/v2/dryrun.py — 트랜잭션 rollback 기반 dry-run
- v2 라우트 가드 — domain switcher 와 결합
- tests:
  - Field Mapping 의 type mismatch 검출 케이스 5+
  - Mart Designer 의 migration 초안 → DRAFT 상태 commit
  - Dry-run 이 mart 에 영향 없음 (트랜잭션 rollback 검증)

Acceptance:
- 새 도메인 worker (가짜 POS) 가 4 page 만으로 e2e 파이프라인 정의 가능
- Dry-run 후 mart 의 row count 변화 0
- Mart Designer 가 만든 migration 초안이 alembic upgrade 통과 (DRAFT → REVIEW 까지)

자동 모드. 단일 commit + push 후 STEP 8 (5.2.5 v1 마이그) 명령어 제안.
```

---

## STEP 8 — 5.2.5 v1 → v2 plugin (agri.yaml) (3주)

**목적**: v1 의 농축산물 가격 로직을 v2 generic engine + agri yaml 로 흡수. *T0 +
shadow 1주* 검증.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.5 'v1 → v2 plugin 마이그' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. shadow run 1주 동안 v1 path / v2 path 둘 다 활성? 아니면 v1 만 active + v2 가
       비동기 검증?
       (기본 추천: dual-active. v1 응답을 user 에게, v2 결과는 비교만)
- Q2. shadow 1주 후 v1 write disable 시점 — 자동 cutover? 아니면 ADMIN 의 명시적
       승인 후 cutover?
       (강한 추천: ADMIN 명시 승인. 자동 cutover 시 사고 위험)
- Q3. T0 snapshot 의 checksum 알고리즘 — md5(string_agg(...)) 충분? 아니면 sha256?
       대용량 mart.price_fact 에 부담은?
- Q4. dual-path diff 가 임계 (예: 1% row mismatch) 초과 시 — alert? auto-rollback?
       human escalation?
- Q5. agri.yaml 의 canonical_table — v1 의 mart.product_master 그대로 쓸지, 새
       AGRI_PRODUCT 같은 alias 도입할지?

기능:
- domains/agri.yaml 작성 — v1 mart 테이블을 *그대로* 가리킴
- backend/app/api/v1/* 의 endpoint 가 내부적으로 v2 generic engine + agri yaml 사용
  (v1 endpoint URL/응답 schema 변경 X)
- shadow run 인프라:
  - migration `<head+1>_dual_path_audit.py` — `audit.shadow_diff` 테이블 (v1 row /
    v2 row / diff_kind / observed_at)
  - middleware: v1 응답 결과 + v2 generic 결과 비교 → 불일치 시 audit 적재
- 6단계 검증 절차:
  1. T0 시점 기록
  2. v1 mart.price_fact / mart.product_master 의 row_count + checksum 저장
  3. v2 registry / compat view 적용
  4. T0 기준 동일 query 재실행 → row_count + checksum 일치 확인
  5. 1주 shadow run — dual-path 비교
  6. shadow 1주 통과 + ADMIN 승인 후 v1 write 비활성화
- frontend AdminPage — shadow_diff 모니터 + cutover 승인 버튼
- tests:
  - 모든 v1 통합 테스트 (16+ 파일) 동일 통과
  - shadow run 의 dual-path diff 가 0 (동일 입력 → 동일 출력)
  - ADMIN 의 cutover 승인 워크플로

Acceptance:
- T0 snapshot 일치 ✅
- 1주 shadow run 의 dual-path diff < 0.01%
- ADMIN cutover 승인 후 v1 write disable + v1 endpoint 그대로 동작
- v1 통합 테스트 100% 통과

자동 모드. 단일 commit + push 후 STEP 9 (5.2.6 새 도메인 ★) 명령어 제안.
```

---

## STEP 9 — 5.2.6 새 도메인 1개 추가 ★ 추상화 검증 (3주)

**목적**: Phase 5 의 *추상화 적정성* KPI 측정. 1~2주 = 적정, 4주+ = 부족.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.6 '새 도메인 1개 추가' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. **새 도메인 최종 결정** — 사업팀 요청이 있으면 그것. 없으면 기술 검증 우선:
       ( ) POS 거래 로그 (1순위)   ( ) IoT 센서 시계열 (2순위)
       ( ) 부동산 매물 (3순위)     ( ) 의약품 가격 (4순위)
       ( ) 기타: ___________
- Q2. 새 도메인의 데이터 소스 — 실제 외부 API 인가, mock 데이터로 시작인가?
       (mock 시작 → Phase 6 Field Validation 에서 실 API)
- Q3. 새 도메인의 std_code 체계 — 표준이 정해져 있나?
       POS = payment_method (5~10종) / IoT = device_model_id /
       부동산 = 동단위코드 / 의약품 = ATC code
- Q4. 추상화 검증 KPI 측정 시작 시점 — STEP 9 시작 시 시계 0 부터?
       어디서 어떻게 시간 측정? (commit timestamp / 설계 시간 별도?)
- Q5. 2주 안에 끝났을 때 vs 4주 걸렸을 때 회수 액션 — *4주 초과 시 5.2.5 까지의
       generic 화 재검토* 라는 결정에 동의?

기능:
- domains/<chosen>.yaml 작성
- migration `<head+1>_<chosen>_mart.py` — `<chosen>_mart.*` 별도 schema 의 fact/master
  테이블 + 도메인별 standard_code + IVFFLAT 인덱스
- 샘플 워크플로 1개 + SQL 템플릿 5개 시드
- 운영자 매뉴얼 갱신 (docs/deliverables/02_user_manual.html 또는 docs/onboarding/)
- e2e 테스트:
  - SOURCE_DATA → MAP_FIELDS → SQL_INLINE_TRANSFORM → DQ_CHECK → STANDARDIZE →
    LOAD_TARGET → 마트 검증
  - 4 가지 load_policy 중 도메인에 맞는 것 검증
  - 도메인별 std_code 매칭

추상화 검증 측정:
- STEP 9 시작 commit timestamp 기록
- 모든 작업 완료 (e2e 통과 + frontend 동작) commit timestamp 기록
- 차이 = 추상화 적정성 KPI
- ADR-0019 신설 — Phase 5 추상화 검증 결과 (KPI + 회수 액션)

Acceptance:
- 새 도메인의 e2e 파이프라인 통과
- domains/<chosen>.yaml 만으로 신규 도메인 동작 (코드 수정 0 — frontend 빼고)
- 추상화 KPI 1~2주 ✅ / 3주 ⚠️ / 4주+ ❌
- v1 회귀 100%
- ADR-0019 작성

자동 모드. 단일 commit + push 후 STEP 10 (5.2.7 외부 API 도메인) 명령어 제안.

만약 4주+ 가 걸렸다면 STEP 10 진입 전에 *5.2.5 까지 generic 화의 어디가 부족했는가*
회고 turn 을 먼저 가지자.
```

---

## STEP 10 — 5.2.7 외부 API 도메인 인지 (1~2주)

**목적**: `/public/v2/{domain}/*` + multi-domain api_key.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.7 'generic 화 부수 효과 — 외부 API' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. v1 의 retailer_allowlist 의 deprecation timeline — Phase 5 안에서 deprecation
       시작? Phase 6 까지 호환? 아예 영구 호환?
       (기본 추천: Phase 5 에서 *deprecated 표시*, Phase 6 까지 호환, Phase 7 에서 제거)
- Q2. 한 api_key 가 multi-domain scope 인 경우 — domain 별 retailer_allowlist 의
       schema 가 다름. JSONB 안에 어떻게 표현?
       (PHASE_5_GENERIC_PLATFORM.md 5.2.7 의 예시 JSON 그대로 OK?)
- Q3. /public/v2/{domain}/docs 분리 — 각 도메인의 OpenAPI sub-app 별도? 아니면
       단일 OpenAPI 에 tag 로 분리?
- Q4. v1 /public/v1/* 와 v2 /public/v2/* 동시 운영 — Phase 4.2.5 의 응답 캐시 (Redis)
       가 도메인 인지로 fingerprint 확장?

기능:
- migration `<head+1>_api_key_multi_domain.py` — ctl.api_key 에 다음 컬럼:
  - domain_resource_allowlist JSONB (예: `{"agri":{"retailer_ids":[1,2]},"pos":{"shop_ids":[100]}}`)
  - retailer_allowlist 는 deprecated 표시 (컬럼 유지) + agri 자동 매핑 호환
- backend/app/api/v2/public/* — domain 별 sub-app:
  - `/public/v2/agri/prices/latest` 등
  - `/public/v2/pos/transactions/latest` 등 (5.2.6 결정 도메인)
  - `/public/v2/agri/docs`, `/public/v2/pos/docs`
- backend/app/core/rate_limit.py 확장 — 도메인 × api_key 단위
- backend/app/db/session.py 의 RLS GUC 도 도메인별
- frontend ApiKeysPage 갱신 — multi-domain scope 입력 + domain_resource_allowlist 폼
- tests:
  - multi-domain api_key 발급 → /public/v2/agri 와 /public/v2/<chosen> 모두 200
  - 도메인 미포함 scope → 403
  - v1 retailer_allowlist 가 자동으로 agri 도메인 allowlist 로 매핑
  - rate limit 이 (api_key, domain) 단위로 동작

Acceptance:
- 한 api_key 로 2+ 도메인 조회 가능
- Phase 4.2.4 의 RLS / Phase 4.2.5 의 cache / Phase 4.2.6 의 abuse_detector 모두
  도메인 인지로 동작
- v1 /public/v1/* 100% 회귀

자동 모드. 단일 commit + push 후 STEP 11 (5.2.8 성능) 명령어 제안.
```

---

## STEP 11 — 5.2.8 성능 & 확장성 (2~3주)

**목적**: 사용자 자유도 vs 성능 가드레일 5축.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.8 'Performance & Scalability' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. 성능 SLO 7종의 baseline — Phase 4 종료 시점에 측정되었는가?
       ingest p95, raw insert throughput, Redis lag, SSE delay, SQL preview,
       DQ custom_sql, backfill chunk
- Q2. Kafka 도입 트리거 4가지 (Redis lag 지속 / replay 1주+ / 외부 stream / CDC 대규모)
       중 *현재 가까운 것* 이 있는가?
- Q3. SQL Studio Performance Coach 는 5.2.4 MVP 에서 후순위로 미뤘는데, 5.2.8 의
       성능 가드레일과 결합해서 *backend 만* 구현할까? (frontend 알림은 Phase 6)
- Q4. backfill 의 chunk_size / max_parallel_runs default — 현재 데이터량 (10만~30만
       rows/일) 기준 어떤 값이 적절?

기능:
- 5축 가드레일:
  1. **수집** — source 별 poll_interval/batch_size/rate_limit_per_min/max_concurrency
     설정 + watermark 기반 polling 강제
  2. **Worker/Queue** — domain/source 별 worker routing, OCR/AI heavy job 별도 queue,
     backpressure (lag 임계 초과 시 polling throttle)
  3. **DB/Schema** — partition key 검토 helper, JSONB 컬럼화 권장 linter,
     mart publish 전 row size / index count / retention 확인
  4. **DQ/SQL** — DQ rule timeout_ms / sample_limit / max_scan_rows / incremental_only
     + custom_sql 의 EXPLAIN + 위험 패턴 검사
  5. **Backfill** — chunk + checkpoint/resume + max_parallel_runs + throttle +
     dry-run 의 예상 row 수/duration/target partitions/DQ cost 표시
- backend/app/domain/perf_guards.py 신규
- backend/app/api/v2/backfill.py — chunk 기반 backfill API
- prometheus metrics 확장 — domain label 추가
- ADR-0020 — Kafka 도입 트리거 (조건부 — 향후 활성화 시 기준)
- tests:
  - poll_interval / rate_limit / max_concurrency 가드레일 통과
  - backfill chunk resume 후 중복 0
  - DQ timeout 초과 시 graceful fail

Acceptance:
- 7종 SLO 측정 자동화 + Grafana 대시보드 갱신
- backfill 1년치 (예: 365 chunks) e2e 통과 + 중간 fail 시 resume 가능
- Kafka 도입 조건이 ADR 로 명시 (현재 충족 X 이면 도입 X)

자동 모드. 단일 commit + push 후 STEP 12 (5.2.9 onboarding) 명령어 제안.
```

---

## STEP 12 — 5.2.9 운영팀 onboarding 갱신 + ADR-0018 (2주)

**목적**: Phase 5 회고 + 운영팀 자료 갱신.

```
PHASE_5_GENERIC_PLATFORM.md 5.2.9 '운영팀 onboarding 갱신' 전체를 구현해.

진행 전 다음을 먼저 확인:
- Q1. docs/onboarding/* 의 어떤 문서를 갱신? 5종 합류 자료 (CURRENT.md 의) 모두?
- Q2. ADR-0018 (v2 generic 회고) 에 포함할 핵심 항목 — 추상화 KPI / 의도하지 않은
       추상화 부족 / Spike 결과의 적중률 / cutover 사고 / shadow run 의 false positive
       / 기타?
- Q3. Phase 6 Field Validation 으로 미룬 8종 ETL UX 항목의 우선순위 다시 정렬?
- Q4. 새 도메인 추가 절차 (yaml + migration + seed) 를 *playbook* 화 — markdown
       chapter? 인터랙티브 마법사 (frontend)? 또는 둘 다?

기능:
- docs/onboarding/* 갱신:
  - 도메인 추가 절차 (yaml + migration + seed) — step-by-step playbook
  - 도메인별 표준화 임계 튜닝 (registry update SQL)
  - source contract / field mapping / DQ rule / mart designer 사용법
  - 성능 가드레일 (partition / index / EXPLAIN / backfill throttle)
  - Phase 4 owner 매트릭스 → 도메인 owner 추가
- ADR-0018 — v2 generic 결정 회고 (추상화 KPI + 회수 액션 + Phase 6 backlog)
- Phase 6 backlog 정리 (PHASE_6_FIELD_VALIDATION.md 갱신)

Acceptance:
- 새 운영자가 docs/onboarding/ 만 보고 새 도메인 1개 추가 e2e 가능 (with 도움 없이)
- ADR-0018 에 KPI 결과 (1~2주 / 3주 / 4주+) 명시
- Phase 6 진입 조건이 PHASE_6_FIELD_VALIDATION.md 에 정리

자동 모드. 단일 commit + push 후 Phase 5 종료 + Phase 6 진입 안내.
```

---

## 부록 A — Phase 5 시작 전 사용자 결정 매트릭스 (한 번에)

STEP 0 의 6개 영역 외에, 각 STEP 별 핵심 결정 항목 한 페이지 요약:

| STEP | 핵심 결정 | default 추천 |
|---|---|---|
| 1 | ORM 옵션 (A/B/C) | C Hybrid |
| 1 | spike PoC 격리 위치 | `backend/app/experimental/` |
| 2 | 가드레일 적용 범위 | 7종 모두 v2. v1 영향 X |
| 2 | 상태머신 적용 대상 | mart + source contract + DQ rule |
| 3 | migration 번호 | 0030~0036 (head 다음) |
| 3 | resource_selector 형식 | JSONPath 1차 |
| 3 | compatibility_mode default | backward |
| 4 | provider_kind 1차 범위 | OCR + CRAWLER + HTTP_TRANSFORM (AI_TRANSFORM 후순위) |
| 4 | v1 OcrProvider chain | shadow 1주 후 제거 |
| 5 | v1 워크플로 자동 마이그 | X (5.2.5 단계에서 점진) |
| 5 | INLINE vs ASSET 정책 | ASSET 만 publish |
| 6 | 1차 embedding 모델 | HyperCLOVA 1536 + OpenAI ada-002 |
| 7 | domain switcher 권한 | user × domain 매트릭스 |
| 7 | Dry-run 정확도 | 트랜잭션 rollback 기반 |
| 8 | shadow run dual-path | dual-active 1주 |
| 8 | cutover 승인자 | ADMIN 명시 승인 |
| 9 | 새 도메인 | 사업팀 요청 우선, 없으면 POS |
| 9 | 4주+ 시 액션 | 5.2.5 까지 generic 화 재검토 turn |
| 10 | retailer_allowlist deprecation | Phase 5 표시, Phase 7 제거 |
| 11 | Kafka 도입 트리거 | ADR-0020 으로 명시만, 도입 X |
| 12 | onboarding 형식 | markdown playbook + 인터랙티브 마법사 (Phase 6 결합) |

---

## 부록 B — 비상 회피 (각 STEP 의 회수 트리거)

| STEP | 회수 트리거 | 회수 액션 |
|---|---|---|
| 1 | Spike 1주에서 옵션 C 안 됨 | A 또는 B 로 전환 + 1주 추가 spike |
| 2 | 가드레일 7종이 v1 회귀 일으킴 | v2 라우트만 적용으로 좁힘 |
| 3 | RLS / Phase 4.2.4 와 충돌 | compat view layer 추가 |
| 4 | Provider Registry refactor 로 v1 OCR 회귀 | shadow mode 영구 유지 |
| 5 | 13+ 노드의 e2e 가 안 됨 | 핵심 6노드 (SOURCE_DATA / MAP_FIELDS / SQL_ASSET / LOAD_TARGET / DQ / NOTIFY) 만 1차 |
| 6 | 도메인별 vector 차원 운영 부담 | 차원 통일 (예: 1536) 강제 옵션 추가 |
| 7 | MVP 4종이 부족 | 1~2 page 추가 + 1주 연장 |
| 8 | shadow diff > 1% | cutover 보류 + 회귀 분석 turn |
| 9 | 4주+ 걸림 | 5.2.5 까지 회고 turn → generic 화 보강 |
| 10 | api_key 마이그 사고 | rollback + v1 retailer_allowlist path 영구 유지 |
| 11 | SLO baseline 측정 안 됨 | Phase 6 로 미룸 |
| 12 | onboarding 자료 부족 | Phase 6 와 합쳐 통합 매뉴얼 작성 |

---

## 사용 안내

1. **STEP 0 부터 시작** — 사용자가 6개 영역 답변 → Claude 가 Phase 5 진입 가능 판정
2. 각 STEP 의 프롬프트를 *그대로 복사* → Claude 에 붙여넣기
3. Claude 는 *진행 전 확인 질문* 먼저 (각 STEP 의 Q1~Q5 정도)
4. 사용자 답변 → 자동 모드 실행 → 단일 commit + push
5. 다음 STEP 프롬프트 안내
6. 4주+ 가 걸린 STEP 발생 시 *부록 B 회수 트리거* 발동 → 회고 turn

**전체 일정 추정**: 14~18 주 (Spike 1 + STEP 2~12 합계). KPI 측정에 따라 단축/연장.
