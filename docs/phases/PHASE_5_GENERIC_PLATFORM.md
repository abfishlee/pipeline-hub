# Phase 5 — 공용 데이터 수집 플랫폼 (v2 Generic)

**전제:** Phase 4 완료. 농축산물 가격 파이프라인 v1 이 NKS 위에서 안정 가동 + 운영팀
6~7명이 일상 운영.

**기간 목표:** 12~18주
**성공 기준 (DoD):**
1. v1 (농축산물 가격) 이 v2 generic platform 위에서 동일하게 동작 (회귀 0).
2. 새 도메인 1개를 v2 위에 **같은 작업 패턴** 으로 추가 가능 (예: IoT 센서 데이터 / POS 거래
   로그 / 의약품 가격) — 코드 작성 없이 YAML + SQL 만으로.
3. 도메인 분리 (`domains/agri.yaml`, `domains/iot.yaml` 등) 로 사용자가 선택 가능.

---

## 5.0 v1 vs v2 — 핵심 차이

| 영역 | v1 (현재) | v2 (목표) |
|---|---|---|
| 도메인 | 농축산물 가격만 | 임의 — agri / iot / pos / pharma / ... |
| 마트 스키마 | 하드코딩 (`mart.price_fact`, `mart.product_master`) | 도메인 yaml 로 정의 (`mart.<resource>_fact`, `mart.<resource>_master`) |
| 표준화 | std_code 1종 (식품 분류) | n 도메인 × 각자의 표준 코드 체계 |
| 노드 타입 7종 | 농축산물에 최적화 (`LOAD_MASTER` 가 mart.product_price 가정) | resource-agnostic (`LOAD_TARGET` 이 임의 mart 테이블) |
| `mart.standard_code.embedding` | 식품용 1536d | 도메인별 별도 테이블 + 별도 embedding |
| OCR / 크롤링 정책 | 영수증 / 마트 전단 특화 | extension point 추출 — 의약품 명세 / 부동산 매물 등도 |
| Crowd 검수 | 식품 검수자 1풀 | 도메인 × skill_tag 매트릭스 |

**핵심 통찰**: v1 의 모든 *비즈니스 로직* 은 사실 *도메인 = 농축산물* 라는 가정에 의해 코드에
박혀 있다. v2 는 그 가정을 **YAML 설정 + plugin domain** 으로 외재화.

---

## 5.1 마이그 전략 — Strangler Pattern

[Strangler Pattern](https://martinfowler.com/bliki/StranglerFigApplication.html) 으로
v1 → v2 점진 이전. *큰 빅뱅 재작성 없음.*

```
┌─── v1 ────────┐    ┌─── v2 (Strangler) ───┐
│ /v1/* (현행)  │    │ /v2/* (새 prefix)    │
│ mart.price_*  │    │ mart.{domain}_*      │
│ std_code 식품 │    │ 도메인 별 std code   │
└───────┬───────┘    └───────────┬──────────┘
        │                        │
        └─── 같은 PostgreSQL ────┘
             (점진 이전)
```

3단계:

1. **5.1 — generic 코어 추출**: v1 의 도메인 로직을 plugin point 로 분리. 새 코드는 모두
   `/v2/*` prefix. v1 동작 유지.
2. **5.2 — v1 을 v2 plugin (agri 도메인) 으로 재구성**: v1 의 mart.price_fact 등을
   `domains/agri.yaml` 로 정의. v1 endpoint 는 그대로 유지하되 내부 구현이 v2 generic
   엔진 사용.
3. **5.3 — 새 도메인 추가**: IoT / POS / pharma 등 사용자 시나리오에 맞춰 1개씩 추가
   하면서 generic 인터페이스 다듬기.

각 단계마다 v1 회귀 테스트 통과 필수.

---

## 5.2 작업 단위 체크리스트

### 5.2.1 generic schema 추상화 [W1~W3]

- [ ] migration: `domain.*` schema 신설
  - `domain.domain_definition (domain_code PK, name, description, schema_yaml jsonb)`
  - `domain.resource_definition (resource_id PK, domain_code FK, resource_code,
    canonical_table, fact_table)` — 각 도메인의 master/fact 테이블 정의
  - `domain.standard_code_namespace (namespace_id PK, domain_code FK, name)` —
    domain 별 std_code 체계
- [ ] backend/app/domain/registry.py: domain 별 ORM 모델 동적 로드 (yaml → SQLAlchemy)
- [ ] backend/app/api/v2/domains.py: domain CRUD (ADMIN)
- [ ] tests: agri 도메인을 domain.* 에 등록 → v1 mart.price_fact 가 그대로 보임

### 5.2.2 노드 타입 generic 화 [W3~W5]

- [ ] `SOURCE_API` → `SOURCE_DATA` (resource-agnostic, source_id + raw_object_type)
- [ ] `SQL_TRANSFORM` → 변경 없음 (이미 generic)
- [ ] `LOAD_MASTER` → `LOAD_TARGET` (target_table 이 임의 mart 테이블 가능, 단 도메인
      yaml 에 등록된 것만)
- [ ] `DEDUP` → 변경 없음 (key_columns generic)
- [ ] `DQ_CHECK` → 변경 없음 (input_table generic)
- [ ] `NOTIFY` → 변경 없음
- [ ] `STANDARDIZE` 신규 노드 — 도메인의 standard_code_namespace + embedding 테이블 사용
- [ ] tests: 같은 워크플로 그래프가 agri / iot 두 도메인에서 동작

### 5.2.3 표준화 엔진 generic 화 [W5~W7]

- [ ] backend/app/domain/standardization/registry.py: 도메인 별 표준화 후보 테이블 +
  embedding 모델 (HyperCLOVA 1536d 외에도 OpenAI ada-002 / 자체 모델 선택 가능)
- [ ] migration: 도메인 별 `<domain>_standard_code` 테이블 + IVFFLAT 인덱스
- [ ] backend/app/domain/standardization/three_stage.py: 3단계 폴백 로직은 그대로,
  pluggable
- [ ] tests: agri 의 식품 매칭 + iot 의 센서 모델명 매칭 — 같은 코드 경로

### 5.2.4 frontend Designer + SQL Studio domain-aware [W7~W9]

- [ ] frontend: 좌측 사이드바에 domain switcher
- [ ] Designer: 같은 7노드, 단 LOAD_TARGET 의 target_table 드롭다운이 선택된 도메인의
  fact 테이블만 보여줌
- [ ] SQL Studio: 같은 sandbox, 단 referenced_tables 검증이 선택된 도메인의 schema 만
  허용
- [ ] PipelineRunsList / PipelineReleases: domain 필터

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
  사용
- [ ] 회귀 테스트: 모든 v1 통합 테스트 (16+ 파일) 가 동일하게 통과
- [ ] 마이그 검증: production data 의 mart.price_fact 가 변경 없음 (row count 일치)

### 5.2.6 새 도메인 1개 추가 [W12~W15]

다음 중 1 도메인 — 사용자 시나리오에 따라 결정:

- 옵션 A: **IoT 센서 데이터** — 온도/습도/조도 센서 시계열, 표준 코드 = device_model_id
- 옵션 B: **POS 거래 로그** — 결제 트랜잭션, 표준 코드 = payment_method
- 옵션 C: **의약품 가격** — 약가, 표준 코드 = ATC code
- 옵션 D: **부동산 매물** — 시세, 표준 코드 = 동단위 코드

선택된 도메인:
- [ ] `domains/<chosen>.yaml` 작성
- [ ] migration: `mart.<resource>_*` 테이블 + 도메인 별 standard_code
- [ ] 샘플 워크플로 1개 + SQL 템플릿 5개 시드 (Phase 3.2.8 패턴)
- [ ] 운영자 매뉴얼 보강 (02_user_manual.html 의 채널 부분에 새 도메인 시나리오 추가)
- [ ] tests: 새 도메인의 end-to-end (SOURCE → STANDARDIZE → LOAD_TARGET → 마트 검증)

### 5.2.7 generic 화 부수 효과 — 외부 API [W15~W16]

- [ ] `/public/v1/*` (Phase 4.2.5) 가 도메인 인지: `/public/v2/{domain}/*`
  - GET `/public/v2/agri/prices/latest`
  - GET `/public/v2/iot/sensors/latest`
- [ ] api_key 의 scope 가 `<domain>.<resource>.read` 형식
- [ ] OpenAPI 별도 docs 도 도메인 별 분리

### 5.2.8 운영팀 onboarding 갱신 [W16~W18]

- [ ] 합류 자료 5종 (CURRENT.md) 의 docs/onboarding/* 갱신:
  - 도메인 추가 절차 (yaml + migration + seed)
  - 도메인 별 표준화 임계 튜닝
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
| 도메인 간 격리 부족 | 한 도메인의 SQL 이 다른 도메인 mart 접근 | sqlglot 의 ALLOWED_SCHEMAS 가 도메인 별 — `<domain>_mart`/`<domain>_stg` |
| pgvector 차원 통일 압박 | HyperCLOVA 1536, OpenAI 3072 등 차원 다름 | 도메인 별 별도 vector 테이블 + 인덱스 — 같은 테이블에 강제 통일 안 함 |
| 운영팀 학습 곡선 | yaml 작성 + 도메인 등록 절차 학습 비용 | 5.2.8 의 onboarding 자료 + Designer UI 의 마법사 |

---

## 5.5 Phase 5 진입 조건

다음이 모두 충족돼야 Phase 5 시작 권장:

- [ ] Phase 4 DoD 5종 모두 ✅
- [ ] NKS 위에서 v1 1개월 무사고 가동
- [ ] 운영팀 6~7명이 Phase 4 owner 영역에서 자율 운영 (의존 0)
- [ ] 새 도메인 추가 요청이 사업 측에서 들어옴 (의약품 / IoT / 부동산 등)
- [ ] v1 의 매출/외부 API 활동 안정 (Phase 5 작업 중에도 v1 운영 영향 0 보장)

위 조건이 안 갖춰진 상태에서 Phase 5 시작은 *조기 추상화* 위험.

---

## 5.6 Phase 5 종료 후 — Phase 6 전망

Phase 5 가 끝나면 다음 옵션:

- **Phase 6A — Marketplace**: 도메인 별 Public API 를 외부 개발자가 구독, 자체 도메인을
  upload 하는 플랫폼
- **Phase 6B — AI 자동화**: 새 도메인의 std_code 체계를 LLM 이 자동 제안, 표준화 임계
  자동 튜닝
- **Phase 6C — Multi-tenant**: 같은 인프라 위에 여러 회사가 자기 도메인 분리 운영

Phase 5 종료 시점에서 사업 방향에 따라 결정.

---

## 부록 — 변경되는 파일/테이블 추정

### Migration 추가 (Phase 5 한정)

| Migration | 설명 |
|---|---|
| `0021_domain_schema.py` | domain.* schema |
| `0022_resource_definition.py` | domain 별 resource 등록 |
| `0023_standard_code_namespace.py` | 도메인 별 std_code |
| `0024_v1_to_v2_compat_views.py` | v1 endpoint 호환 view (mart.price_fact → agri_resource view) |
| `0025+` | 새 도메인 1~N 의 mart 테이블 |

### Backend 모듈 추가

```
backend/app/domain/
  registry.py              # 도메인 yaml → ORM 동적 로드
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

---

## 마무리

**Phase 5 는 코드 양보다 설계 토론이 더 중요한 단계.** 추상화 한 단계 잘못 두면 6개월 뒤
*어차피 농축산물밖에 안 쓰니 generic 화는 무리수였다* 가 되거나, 너무 적게 두면 새 도메인
하나 추가에 또 다시 8주 걸리는 결과.

본 phase 의 핵심 의사결정은 **5.2.6 (새 도메인 1개 추가)** 시점에서 자연스럽게 검증됨 —
1주 안에 새 도메인 추가가 가능해지면 추상화가 적절. 4주 걸리면 추상화 부족.

Phase 4 종료 후 사업 측에서 *어떤 도메인이 시급한가* 가 명확해진 시점에 본 phase 시작.
