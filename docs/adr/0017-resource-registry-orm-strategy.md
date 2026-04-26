# ADR-0017 — Resource Registry ORM 전략 (Phase 5.2.1a Spike)

- **Status:** Accepted (Hybrid 채택)
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 5.2.1a Dynamic Resource Registry Spike (1주 선행)
- **참고 docs:** `docs/phases/PHASE_5_GENERIC_PLATFORM.md` § 5.2.1a, § 5.4 위험 표

## 1. 컨텍스트

Phase 5 의 핵심은 "도메인 N개" 를 *코드 변경 없이* 추가하는 것. 각 도메인의 mart 테이블,
vector 임베딩 (차원 다를 수 있음), staging 테이블이 *yaml 등록만* 으로 동작해야 함.

기존 v1 은 모든 테이블이 SQLAlchemy ORM 의 정적 declarative 클래스로 정의:

```python
class ProductMaster(Base):
    __tablename__ = "product_master"
    __table_args__ = {"schema": "mart"}
    product_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ...
```

이 방식은 *컴파일 타임에 모든 테이블이 알려짐* 이 전제. v2 의 *runtime 에 yaml 로
도메인 추가* 모델과 충돌.

질문: **v2 generic resource 를 어떻게 SQLAlchemy 로 다룰 것인가?**

## 2. 결정

### **Hybrid (Option C) 채택.**

```
v1 정적 도메인 (agri 농축산물)        →  ORM declarative class 그대로 유지
v2 generic resource (iot/pos/pharma)  →  SQLAlchemy Core + reflected Table
도메인별 vector 테이블 (차원 다양)    →  Core + 명시 SQL 캐스팅 (`CAST(:v AS vector)`)
```

핵심 메커니즘:

1. **v1 unchanged** — `ProductMaster`, `PriceFact`, `DataSource` 등 *모든 v1 ORM
   클래스 그대로*. typed `Mapped[T]` + mypy + ORM relationship 의 장점 유지.
2. **v2 = HybridResourceRegistry** — 본 ADR 의 spike 로 검증된 패턴:
   - `register_resource(domain_code, resource_code, schema_name, table_name)` 호출
     시 SQLAlchemy `MetaData.reflect()` 로 PG 에서 컬럼 메타 가져옴.
   - CRUD 는 Core 의 `select() / insert() / update() / delete()` 로 직접 작성.
   - JOIN 도 Core — `select(l_tbl, r_tbl).select_from(l_tbl.join(r_tbl, ...))`.
3. **도메인별 차원 다른 vector 테이블** — pgvector `vector(N)` 을 SQLAlchemy 가
   NullType 으로 인식 → caller 가 `CAST(:v AS vector)` 로 명시 캐스팅. 차원 검증은
   yaml 의 `dim` 메타가 책임.
4. **Alembic migration 정책**:
   - v1 ORM 변경 = 기존 Alembic autogenerate 흐름 그대로.
   - v2 generic resource 의 *yaml 변경* = `domain.resource_definition` row 변경 +
     별도 *명시적 migration* 작성 (autogenerate X). yaml 가 *코드 import 시점* 에
     알려지지 않으므로 autogenerate 가 detect 못 함.

### 핵심 결정 1 — ORM 동적 클래스 (Option A) 기각

`type()` 으로 declarative class 동적 생성 시 발견된 한계:

- **registry conflict**: 같은 `(schema, table)` 에 대해 두 번 `Base` 만들면 SQLAlchemy
  가 *"class is already mapped"* 충돌. *별도 Base 인스턴스* 마다 분리해도 ORM 의 글로벌
  registry 와 섞이며 metadata 격리 비용 큼.
- **mypy 무력**: `Mapped[T]` type hint 는 *임포트 시점에 추론* 이라 runtime 동적 클래스
  의 column 은 mypy 가 모름. 운영 코드에서 `pm.product_id` 가 *Any* 로 떨어짐.
- **Alembic autogenerate 비호환**: autogenerate 는 *Base.metadata 가 import 시점에 모든
  테이블 알고 있어야* 함. 동적 생성은 *yaml 로드 → DB 변경* 의 inversion 이라 *반드시
  명시적 migration*.

### 핵심 결정 2 — Core only (Option B) 기각

모든 도메인 (v1 + v2) 을 Core + reflection 으로 통일하는 옵션. 기각 사유:

- **v1 코드 변경 폭 큼** — Phase 1~4 내내 typed ORM 으로 작성된 도메인 로직
  (`pipeline_runtime`, `crowd review`, `master_merge` 등) 을 모두 Core SQL 로 재작성.
  *추상화 검증 효과 대비 비용 압도적*.
- **lazy loading / relationship 손실** — v1 의 `pm.connectors` 같은 relationship 사용
  포기. 운영 화면의 N+1 query 문제 재현 가능성 높음.
- **mypy / IDE 자동완성 손실** — v1 코드 가독성 큰 폭 저하.

→ Core only 는 *v1 이 전혀 없는 그린필드* 에서만 합리적. 본 프로젝트는 v1 이 운영 중인
*brownfield*.

### 핵심 결정 3 — Hybrid 의 경계 명확화

| 영역 | ORM (v1 정적) | Core + reflection (v2) |
|---|---|---|
| 농축산물 mart (`mart.price_fact` 등) | ✅ | (등록만 — yaml 의 `canonical_table` 가리킴) |
| 신규 도메인 mart (`pos_mart.txn_fact`) | ❌ | ✅ |
| 도메인별 vector 테이블 | ❌ | ✅ |
| ctl/audit/run/wf/dq schema | ✅ | ❌ |
| Phase 4 의 RLS / api_key / DQ 게이트 | ✅ | ❌ |

→ *v2 generic 라우트* (`/v2/*`) 만 HybridResourceRegistry 사용. Phase 4 의 모든 도메인
로직은 ORM 으로 그대로.

### 핵심 결정 4 — vector 차원 동적 지원

PoC 검증: 같은 도메인 안에서 `embedding_512` 와 `embedding_1024` 두 차원의 테이블이
동시에 존재 → Core registry 가 *각각 독립 Table* 로 reflect → 정상 INSERT/SELECT.

운영 시 정책:

- 도메인 yaml 의 `embedding_model` (예: `hyperclova-1536`, `openai-3-large`) 명시.
- registry 가 모델명 → 차원 매핑 (`HybridResourceRegistry.EMBEDDING_DIMENSIONS`) 로
  검증.
- 한 도메인이 여러 모델 (다른 차원) 사용 가능 — 별도 테이블만 yaml 에 등록.

## 3. 검증 (Spike 결과)

PoC 코드: `backend/app/experimental/registry_spike.py`
PoC 데이터: migration `0030_spike_iot.py` 의 `iot_spike_mart` schema

| 검증 항목 | 결과 |
|---|---|
| Hybrid `register_resource` + reflect | ✅ |
| INSERT (sensor_v1) → PK 반환 | ✅ |
| SELECT with WHERE | ✅ |
| UPDATE / DELETE | ✅ |
| JOIN (sensor + reading) | ✅ |
| vector(512) INSERT (CAST AS vector) | ✅ |
| vector(1024) INSERT (다른 차원, 같은 도메인) | ✅ |
| v1 ORM (`DataSource.product_id` 등) 회귀 | ✅ 영향 0 |
| 같은 (schema, table) 두 번 등록 — extend_existing | ✅ |

## 4. 회수 조건 (Hybrid → 다른 옵션 전환 트리거)

다음 *어떤 것* 이라도 발생하면 후속 ADR + 옵션 전환 검토:

1. **runtime 성능 회귀** — Core 의 SQL 생성 비용이 ORM 대비 2x+ 느리게 측정되면.
   현재 spike 측정: 1만 row INSERT = ORM 대비 ~1.1x (무시 가능).
2. **JOIN/aggregation 복잡도 폭증** — Core SQL builder 가 운영자에게 너무 어려우면.
   대응 1: query helper layer 추가. 대응 2: SQL Studio 로 사용자가 직접 SQL.
3. **vector 차원이 1개로 통일됨** — 모든 도메인이 같은 모델 사용으로 수렴하면 도메인별
   별도 테이블의 필요성 사라짐. (현 시점 비현실적 — HyperCLOVA 1536 vs OpenAI 3072
   는 강제 통일 불가.)
4. **Alembic 의 yaml 기반 migration 자동화 한계** — `domain.resource_definition` 변경
   시 *항상 명시 migration 작성* 부담이 운영자에게 너무 큰 경우. 대응: yaml-to-migration
   helper CLI (`python -m app.cli.materialize_resource <domain> <resource>`) 도입.

## 5. 영향

**긍정적**:

- v1 코드 변경 0 — 4 phase 동안 쌓인 도메인 로직 (pipeline_runtime, crowd, master_merge,
  RLS 등) 100% 보존.
- v2 generic resource 가 *yaml 등록 + reflect* 만으로 동작 — 새 도메인 추가의 *코어 비용
  최소화*.
- 도메인별 차원 다른 vector 테이블 자연 지원 — Phase 5.4 위험표의 *pgvector 차원 통일
  압박* 회피.

**부정적**:

- v2 generic resource 는 *typed Mapped 의 IDE 자동완성/mypy 검증 없음*. 운영자가 컬럼
  이름을 *yaml 에 일치* 시키도록 schema 검증 helper 가 필수 (5.2.1 의 contract
  validator 가 책임).
- v1 ORM + v2 Core 두 가지 mental model 공존 — 신규 운영자 학습 곡선. → 5.2.9
  onboarding 에서 *언제 ORM, 언제 Core* 가이드 필요.
- Alembic autogenerate 가 v2 영역에 부분적으로만 동작 — yaml 변경마다 명시 migration
  작성. 보완: helper CLI (회수 조건 § 4 참조).

**중립**:

- 차원 다른 vector 테이블의 IVFFLAT 인덱스 생성은 *명시 SQL* 로 처리. autogenerate
  안 됨 (의도된 한계).

## 6. 후속 작업 (Phase 5.2.1 정식 진입 시)

본 ADR 채택 후:

- [ ] `backend/app/experimental/registry_spike.py` 의 `HybridResourceRegistry` 를
  `backend/app/domain/registry.py` 로 이전 (정식화).
- [ ] migration `0030_spike_iot.py` downgrade 로 정리.
- [ ] Phase 5.2.1 의 `domain.*` schema (0030~0036) 와 통합 — registry 가 yaml 대신
  `domain.resource_definition` row 를 source of truth 로 사용.
- [ ] Mart Designer (Phase 5.2.4) 가 registry 의 `list_columns` 를 호출 → 폼 자동
  생성.

## 7. 참고

- `backend/app/experimental/registry_spike.py` — Hybrid PoC + Option A/B 의 한계
  코드 (실측).
- `migrations/versions/0030_spike_iot.py` — `iot_spike_mart` schema (spike 종료 시
  downgrade).
- `backend/tests/integration/test_registry_spike.py` — 9 케이스 (CRUD + JOIN +
  vector 두 차원 + v1 회귀).
- PHASE_5_GENERIC_PLATFORM.md § 5.2.1a, § 5.4 위험표.
- SQLAlchemy 2.0 docs — [Working with Reflected Tables](https://docs.sqlalchemy.org/en/20/core/reflection.html)
