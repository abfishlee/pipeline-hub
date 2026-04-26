# Phase 5.1 — v2 Generic Platform 보완 / 테스트 / 안정화

**목적:** Phase 5에서 구현된 v2 generic platform의 실제 소스코드 상태를 기준으로,
운영 또는 고객 시연 전에 보완해야 할 부분, 반드시 실행해야 할 테스트, 테스트 후 후속 개선
항목을 정리한다.

이 문서는 `PHASE_5_GENERIC_PLATFORM.md`의 설계 문서가 아니라, 현재 repository의 실제
구현을 읽고 도출한 안정화 체크리스트다.

---

## 5.1.0 현재 소스 기준 판정

현재 Phase 5는 **백엔드 / DB / migration / 테스트 골격은 상당히 구현되어 있고**, 프론트엔드
v2 UX와 일부 generic runtime 전환은 아직 보완이 필요하다.

### 구현이 확인된 영역

- `domain.*` registry ORM
  - `backend/app/models/domain.py`
  - `DomainDefinition`, `ResourceDefinition`, `SourceContract`, `FieldMapping`,
    `LoadPolicy`, `DqRule`, `ProviderDefinition`, `SourceProviderBinding`, `SqlAsset`
    등이 존재.
- v2 API 라우터
  - `backend/app/api/v2/domains.py`
  - `contracts.py`
  - `mappings.py`
  - `providers.py`
  - `dryrun.py`
  - `dq_rules.py`
  - `public_router.py`
  - `backfill.py`
  - `perf.py`
- v2 public API
  - `/public/v2/{domain}/standard-codes`
  - `/public/v2/{domain}/{resource}/latest`
- provider registry 기반
  - `backend/app/domain/providers/factory.py`
  - `backend/app/domain/providers/circuit_breaker.py`
  - `secret_ref`, fallback, circuit breaker 구조 존재.
- v2 node runtime 일부
  - `MAP_FIELDS`
  - `SQL_INLINE_TRANSFORM`
  - `SQL_ASSET_TRANSFORM`
  - `HTTP_TRANSFORM`
  - `FUNCTION_TRANSFORM`
  - `LOAD_TARGET`
- Dry-run / guardrail
  - `backend/app/api/v2/dryrun.py`
  - `backend/app/domain/guardrails/sql_guard.py`
  - rollback 기반 dry-run 구조 존재.
- POS 도메인 검증 기반
  - `domains/pos.yaml`
  - `migrations/versions/0043_pos_mart.py`
- 성능 / backfill 기반
  - `backend/app/domain/perf_guards/slo.py`
  - `backend/app/domain/perf_guards/backfill.py`
  - `migrations/versions/0045_perf_slo_and_backfill.py`
- Phase 5 관련 integration test 파일 다수 존재.

### 부분 구현 또는 보완 필요 영역

- frontend v2 UX가 아직 약하다.
  - `FieldMappingDesigner`, `MartDesigner`, `DqRuleBuilder`, `DryRunResults`,
    `ProvidersPage` 같은 별도 v2 화면/라우트가 현재 `frontend/src/App.tsx`에 보이지 않음.
- OCR / Crawler worker는 아직 registry primary path로 전환되지 않았다.
  - `backend/app/workers/ocr_worker.py`는 settings 기반 `CLOVA -> Upstage` chain 사용.
  - `backend/app/workers/crawler_worker.py`는 `HttpxSpider` 직접 사용.
  - provider registry는 존재하지만 worker cutover는 미완.
- v2 node catalog는 13+ 전체가 아니라 핵심 6종 중심이다.
  - `OCR_TRANSFORM`, `CRAWL_FETCH`, `STANDARDIZE` dispatcher 미연결.
- 표준화 엔진은 아직 agri 중심이다.
  - `backend/app/domain/standardization.py`가 `mart.standard_code`를 직접 조회.
  - 도메인별 vector table / namespace / provider dimension runtime 전환 필요.
- 테스트 실행 환경이 준비되어 있지 않았다.
  - `uv`가 PATH에 없음.
  - 현재 Python에 `pytest`가 없음.

---

## 5.1.1 최우선 보완 과제

### P0 — 테스트 실행 환경 복구

**이유:** 현재 가장 큰 위험은 구현 여부보다, 테스트를 실제로 실행해 회귀를 확인할 수 없는
상태다.

작업:

- backend 개발 환경에서 `uv` 또는 `pytest` 실행 가능 상태 만들기.
- Python 버전과 dependency 설치 경로 정리.
- `backend/README` 또는 `docs/onboarding/02_local_dev.md`에 테스트 실행 명령 고정.

권장 명령:

```bash
cd backend
python -m pip install -e ".[dev]"
python -m pytest
```

또는 팀 표준이 `uv`라면:

```bash
cd backend
uv sync --dev
uv run pytest
```

Acceptance:

- `python -m pytest tests/test_health.py` 통과.
- Phase 5 핵심 integration test 일부 통과.
- CI 또는 로컬 runbook에 동일 명령 기록.

---

### P0 — v1 회귀 테스트 먼저 통과

**이유:** Phase 5의 제1 원칙은 v1 보존이다. v2 기능이 좋아도 v1 농축산물 파이프라인이 깨지면
운영 관점에서는 실패다.

우선 테스트:

```bash
cd backend
python -m pytest \
  tests/integration/test_ingest.py \
  tests/integration/test_raw_objects.py \
  tests/integration/test_pipeline_runtime.py \
  tests/integration/test_price_fact_pipeline.py \
  tests/integration/test_public_api.py \
  tests/integration/test_sql_studio.py
```

Acceptance:

- v1 ingest / raw / pipeline / mart / public API 회귀 100% 통과.
- 실패 시 Phase 5 보완보다 v1 회귀 복구를 우선한다.

---

### P0 — Phase 5 핵심 테스트 묶음 실행

**이유:** 코드상 Phase 5 구현은 많지만, 실제 DB/migration 상태와 결합되어 통과하는지 확인해야
한다.

우선 테스트:

```bash
cd backend
python -m pytest \
  tests/integration/test_registry_spike.py \
  tests/integration/test_domain_registry.py \
  tests/integration/test_guardrails.py \
  tests/integration/test_provider_registry.py \
  tests/integration/test_nodes_v2.py \
  tests/integration/test_step7_etl_ux.py \
  tests/integration/test_step8_shadow_cutover.py \
  tests/integration/test_step9_pos_domain.py \
  tests/integration/test_step10_public_v2.py \
  tests/integration/test_step11_perf_guards.py
```

Acceptance:

- 위 테스트 묶음이 통과.
- 실패 테스트는 `Phase 5.1 Known Issues`에 기록.
- 실패 원인이 fixture/환경인지 실제 로직인지 분리.

---

## 5.1.2 기능 보완 과제

### P1 — frontend v2 UX 라우트 추가

현재 backend에는 v2 dry-run, DQ rule, provider, domain registry API가 존재하지만, frontend
라우트는 기존 v1 화면 중심이다. 사용자가 “공용 플랫폼”으로 쓰려면 최소 v2 화면이 필요하다.

필요 화면:

- `frontend/src/pages/v2/FieldMappingDesigner.tsx`
- `frontend/src/pages/v2/MartDesigner.tsx`
- `frontend/src/pages/v2/DqRuleBuilder.tsx`
- `frontend/src/pages/v2/DryRunResults.tsx`
- `frontend/src/pages/v2/ProvidersPage.tsx`
- `frontend/src/pages/v2/DomainsPage.tsx`

필요 API client:

- `frontend/src/api/v2/domains.ts`
- `frontend/src/api/v2/contracts.ts`
- `frontend/src/api/v2/mappings.ts`
- `frontend/src/api/v2/dq.ts`
- `frontend/src/api/v2/dryrun.ts`
- `frontend/src/api/v2/providers.ts`

Acceptance:

- `/v2/domains`에서 domain 목록 조회.
- `/v2/providers`에서 provider 상태 조회.
- Field Mapping 화면에서 sample payload 검증 가능.
- Mart Designer에서 migration draft 생성 가능.
- DQ Rule Builder에서 custom SQL preview 가능.
- Dry-run 결과에서 row_count / error / target_summary 확인 가능.

---

### P1 — OCR / Crawler worker registry cutover

현재 provider registry와 circuit breaker는 존재하지만, 실제 worker는 아직 기존 path를 사용한다.

수정 대상:

- `backend/app/workers/ocr_worker.py`
- `backend/app/workers/crawler_worker.py`
- `backend/app/domain/providers/factory.py`
- `backend/app/domain/providers/shadow.py`

작업:

- source_id 기준 provider binding 조회.
- registry provider path를 shadow mode로 실행.
- v1 path 결과와 registry path 결과를 비교하여 health/audit 기록.
- 1주 shadow 통과 후 feature flag로 registry primary 전환.
- fallback provider 자동 선택.

Acceptance:

- OCR worker가 source binding에 따라 CLOVA/Upstage/external provider를 선택.
- Crawler worker가 httpx/playwright/external provider를 설정으로 선택.
- provider circuit OPEN 시 다음 fallback 사용.
- 기존 v1 OCR/Crawler integration test 회귀 0.

---

### P1 — STANDARDIZE node generic 연결

현재 standardization runtime은 `mart.standard_code` 중심이다. v2 generic platform에서는 도메인별
namespace와 embedding table을 사용해야 한다.

수정 대상:

- `backend/app/domain/standardization.py`
- `backend/app/domain/nodes_v2/__init__.py`
- 신규 또는 보완:
  - `backend/app/domain/nodes_v2/standardize.py`
  - `backend/app/domain/standardization/registry.py`

작업:

- `ResourceDefinition.standard_code_namespace` 읽기.
- namespace별 `std_code_table` 조회.
- threshold 전역 default + 도메인 override 지원.
- embedding table / dimension / provider registry 지원.
- `STANDARDIZE` node dispatcher 등록.

Acceptance:

- agri `AGRI_FOOD` 표준화 기존 회귀 통과.
- pos `PAYMENT_METHOD` alias 매칭 동작.
- vector dimension이 다른 domain이 있어도 테이블 분리 가능.

---

### P1 — v2 node catalog 확장

현재 dispatcher는 핵심 6종만 지원한다.

현재 지원:

- `MAP_FIELDS`
- `SQL_INLINE_TRANSFORM`
- `SQL_ASSET_TRANSFORM`
- `HTTP_TRANSFORM`
- `FUNCTION_TRANSFORM`
- `LOAD_TARGET`

추가 필요:

- `SOURCE_DATA`
- `DEDUP`
- `DQ_CHECK`
- `NOTIFY`
- `OCR_TRANSFORM`
- `CRAWL_FETCH`
- `STANDARDIZE`

Acceptance:

- `list_v2_node_types()`가 문서상 v2 catalog와 일치.
- v2 workflow 하나에서 source -> mapping -> transform -> DQ -> standardize -> load ->
  notify까지 e2e 실행 가능.

---

### P1 — LOAD_TARGET의 SCD2 / snapshot 구현 여부 결정

`LOAD_TARGET` 코드상 `scd_type_2`, `current_snapshot`은 placeholder로 실패 처리된다.

선택지:

- A. Phase 5.1에서 구현.
- B. 명확히 Phase 6로 이동하고 문서/테스트 기대값 수정.

권장:

- 고객 시연 전에는 `append_only`, `upsert`를 안정화.
- `scd_type_2`, `current_snapshot`은 Phase 6로 이동하되, API 응답에 “not implemented”가
  명확히 나오게 유지.

Acceptance:

- 문서와 테스트가 현재 구현 범위를 과장하지 않음.
- unsupported mode 호출 시 422 또는 명확한 failed payload 반환.

---

## 5.1.3 보안 / 안정성 점검

### SQL Guard 강화 검증

확인할 것:

- `DROP`, `DELETE FROM`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `COPY PROGRAM` 차단.
- v1 SQL Studio는 SELECT only.
- v2 SQL_INLINE / SQL_ASSET은 staging/temp write만 허용.
- LOAD_TARGET은 allowlist target만 write 허용.
- schema.table 미지정 SQL 차단.

테스트:

```bash
cd backend
python -m pytest \
  tests/test_sqlglot_validator.py \
  tests/integration/test_sql_studio.py \
  tests/integration/test_sql_studio_sandbox.py \
  tests/integration/test_guardrails.py
```

테스트 후 보완:

- 실제 운영 SQL 중 guard에 막히는 합법 SQL 목록 수집.
- allowlist 예외가 필요한 경우 ADR에 기록.
- 예외는 domain/resource 단위로 제한.

---

### API Key / RLS / Cache 분리 검증

확인할 것:

- v1 `retailer_allowlist`가 agri v2 scope로 자동 매핑되는지.
- v2 `domain_resource_allowlist`가 domain/resource별로 동작하는지.
- cache key에 api version, domain, resource, scope hash가 포함되는지.
- unauthorized domain은 403.

테스트:

```bash
cd backend
python -m pytest tests/integration/test_step10_public_v2.py
```

테스트 후 보완:

- domain별 rate limit이 실제 Redis key에서도 분리되는지 확인.
- abuse detector가 v2 domain label을 포함하는지 확인.
- `/public/v2/{domain}/docs` 제공 방식 확정.

---

### Provider secret 관리 검증

확인할 것:

- DB에는 secret 원문 저장 금지.
- `ProviderDefinition.secret_ref`만 저장.
- 실제 값은 `.env` 또는 향후 Secret Manager에서 로드.

테스트:

```bash
cd backend
python -m pytest tests/integration/test_provider_registry.py
```

테스트 후 보완:

- provider health page/API에서 secret 존재 여부만 표시하고 실제 값은 노출하지 않음.
- Secret Manager 도입 시 `resolve_secret()`만 교체 가능해야 함.

---

## 5.1.4 데이터 흐름 E2E 테스트

### v1 E2E

목표:

- 기존 농축산물 가격 파이프라인이 Phase 5 변경 후에도 그대로 동작.

시나리오:

1. source 등록.
2. `/v1/ingest/api` raw 수집.
3. outbox 발행.
4. transform worker 실행.
5. DQ_CHECK 통과.
6. LOAD_MASTER 또는 price_fact 적재.
7. `/public/v1/*` 조회.

Acceptance:

- v1 endpoint URL/response schema 변경 없음.
- mart row_count 기대값 일치.
- 중복 ingest 시 row 중복 없음.

---

### v2 POS E2E

목표:

- 농축산물과 다른 POS 도메인이 generic path로 동작.

시나리오:

1. `domains/pos.yaml` 로드.
2. POS source contract 등록.
3. sample transaction payload ingest.
4. MAP_FIELDS.
5. SQL_ASSET 또는 FUNCTION_TRANSFORM.
6. DQ_CHECK.
7. STANDARDIZE payment_method.
8. LOAD_TARGET to `pos_mart.pos_transaction`.
9. `/public/v2/pos/TRANSACTION/latest` 조회.

Acceptance:

- 코드 수정 없이 domain registry / mapping / load policy 중심으로 동작.
- `pos_mart.pos_transaction` row 증가.
- payment_method 표준화 결과가 `CARD`, `CASH`, `MOBILE_PAY` 등으로 수렴.

---

### v1 -> v2 shadow E2E

목표:

- agri v1 결과와 v2 generic 결과가 같은지 비교.

시나리오:

1. T0 snapshot 저장.
2. `domains/agri.yaml` 로드.
3. v1 query 실행.
4. v2 generic query 실행.
5. `audit.shadow_diff` 기록.
6. diff ratio 계산.
7. ADMIN cutover 승인 테스트.

Acceptance:

- T0 checksum 일치.
- shadow diff < 0.01%.
- diff 초과 시 cutover block.

---

## 5.1.5 프론트엔드 테스트

현재 frontend는 v1 운영 화면 중심이다. v2 UX를 추가한 뒤 아래를 테스트한다.

### Build test

```bash
cd frontend
pnpm install
pnpm build
```

Acceptance:

- TypeScript build 통과.
- Vite build 통과.

### UX smoke test

확인 화면:

- Login
- Dashboard
- Pipeline Designer
- SQL Studio
- API Keys
- v2 Domains
- v2 Providers
- v2 Field Mapping
- v2 Mart Designer
- v2 DQ Rule Builder
- v2 Dry-run

Acceptance:

- 모든 화면에서 API 호출 실패 시 사용자에게 명확한 error 표시.
- 긴 테이블명/컬럼명/SQL이 UI를 깨지 않음.
- domain switcher 변경 시 화면 상태가 올바르게 갱신.

---

## 5.1.6 테스트 후 보완해야 할 항목

테스트 후에는 단순히 “통과/실패”만 보지 말고 아래를 기록한다.

### 실패 유형 분류

| 유형 | 의미 | 액션 |
|---|---|---|
| 환경 실패 | DB/Redis/Object Storage/pytest 미준비 | onboarding/runbook 보완 |
| migration 실패 | Alembic 순서/권한/schema 충돌 | migration 수정, downgrade 검증 |
| v1 회귀 | 기존 농축산물 기능 깨짐 | Phase 5 작업 중지 후 v1 복구 |
| v2 로직 실패 | generic registry/node/load 오류 | 해당 STEP 구현 보완 |
| UX 실패 | 화면 없음/사용 어려움/에러 불명확 | frontend MVP 보완 |
| 성능 실패 | timeout/slow query/worker lag | perf guard threshold 조정 |

### 테스트 결과 산출물

- `docs/phases/PHASE_5_1_TEST_REPORT.md`
- 포함 항목:
  - 실행 일시
  - commit hash
  - 실행 환경
  - DB migration head
  - 통과/실패 테스트 목록
  - 실패 원인
  - 수정 PR/commit
  - 재테스트 결과

---

## 5.1.7 Phase 5.1 완료 기준

Phase 5.1은 아래 기준을 만족해야 완료로 본다.

- v1 핵심 회귀 테스트 통과.
- Phase 5 핵심 backend integration test 통과.
- v2 frontend MVP 화면 최소 4종 연결.
- OCR/Crawler provider registry shadow mode 동작.
- POS domain e2e 통과.
- `/public/v2/agri/*`, `/public/v2/pos/*` smoke 통과.
- SLO baseline 1회 측정.
- Backfill chunk/resume smoke 통과.
- 테스트 리포트 작성.
- 미구현 범위가 Phase 6 backlog로 명확히 이동.

---

## 5.1.8 권장 실행 순서

1. 테스트 실행 환경 복구.
2. Alembic migration head 확인.
3. v1 회귀 테스트 실행.
4. Phase 5 backend 핵심 테스트 실행.
5. 실패 항목을 P0/P1/P2로 분류.
6. frontend v2 UX MVP 라우트 추가.
7. OCR/Crawler worker registry shadow mode 연결.
8. STANDARDIZE node generic화.
9. POS e2e 재실행.
10. public v2 smoke 재실행.
11. perf/backfill smoke 재실행.
12. `PHASE_5_1_TEST_REPORT.md` 작성.
13. Phase 6 Field Validation 진입 여부 결정.

