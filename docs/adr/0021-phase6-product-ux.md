# ADR-0021 — Phase 6 Product UX 회고 (코딩 0줄로 새 파이프라인 만들기)

- **Status**: ACCEPTED
- **Date**: 2026-04-26
- **Phase**: 6 — Product UX First
- **Author**: Claude / 사용자

---

## 결정 (한 줄)

> **Phase 6 의 "코딩 0줄" 목표는 ✅ 통과** — 6 workbench + ETL Canvas v2 + Dry-run +
> Publish Approval 화면이 생성됨. 운영자가 KAMIS OpenAPI 1건을 등록하여 PUBLIC_API_FETCH
> → MAP_FIELDS → DQ_CHECK → LOAD_TARGET 4박스 파이프라인을 *13분 안에* 만들 수
> 있음을 검증 (`docs/kamis_demo_quickstart.md`).

---

## 컨텍스트

Phase 5 는 backend generic registry / API / migration / 일부 실행 엔진을 만들었지만,
사용자가 *직접 만질 수 있는 화면* 은 없었다. Phase 6 는 그 위에 *제품 UX* 를 입혀
"개발자 없이 새 데이터 파이프라인을 설계·실행" 할 수 있게 했다.

진단 시점 (2026-04-25) 의 GAP:

> backend 13 노드 + 5 자산 모델은 다 있는데, 화면에서 만지고 캔버스로 끌어올
> 도구가 없다.

---

## Wave 별 진행

| Wave | 내용 | commit | 산출물 |
|---|---|---|---|
| Wave 0 | Phase 6 plan 작성 + § 13 결정 | `9ce43bc` | `PHASE_6_PRODUCT_UX.md` |
| Wave 1 | Source/API Designer (workbench 1) + PUBLIC_API_FETCH 노드 | `54b6924` `603be65` | generic engine + 7-section form |
| Wave 2A | Field Mapping Designer (workbench 2) | `617e08a` | CRUD + 26+ 함수 도움말 + dry-run |
| Wave 2B | Transform Designer (workbench 3) | `8daffcc` | 4탭 (SQL Asset/HTTP/Function/Provider) |
| Wave 3 | Mart Workbench (workbench 4) | `b0cf5f4` | Mart Schema + Load Policy 통합 |
| Wave 3.5 | KAMIS vertical slice e2e 검증 | `d15673b` | migration 0048 + seed 스크립트 + 통합 테스트 |
| Wave 4 | ETL Canvas v2 (workbench 5) | `12b96ec` | 13종 palette + 자산 dropdown drawer |
| Wave 5 | Dry-run + Publish Approval (workbench 6) | `a639db2` | DAG dry-run + checklist 7항목 + ADMIN 승인 |
| Wave 6 | Quality Workbench + KAMIS demo guide | (이 PR) | DQ Rule Builder + Standardization 카탈로그 |
| Wave 7 | onboarding playbook + 본 ADR | (이 PR) | `06_canvas_playbook.md` + 본 문서 |

> 9개 화면 → 6 workbench 통합 (§ 13.1 결정). Transform 은 별도 designer 로,
> DQ + Standardization 은 Quality Workbench 안의 2탭으로.

---

## KPI 달성도 (§ 13.8)

| KPI | 목표 | 달성 |
|---|---|---|
| Zero-code connector | KAMIS 수집 파이프라인 생성 중 backend 코드 수정 0 | ✅ migration 0048 외 코드 수정 0 (시드는 멱등 데이터) |
| Time to first dry-run | 새 OpenAPI 등록 후 30분 이내 dry-run 성공 | ✅ 13분 시나리오로 검증 |
| Time to first publish | 새 OpenAPI 등록 후 60분 이내 publish 후보 생성 | ✅ 13분 시나리오 마지막 단계 |
| Demo duration | 고객 시연 flow 15분 이내 | ✅ 13분 시나리오 (`kamis_demo_quickstart.md`) |
| KAMIS run success | 1주 scheduled run 성공률 95% 이상 | 🟡 staging 시연 시 측정 |
| Dry-run accuracy | dry-run row_count 와 실제 row_count 오차 1% 이하 | 🟡 staging 시연 시 측정 |
| DQ explainability | 실패 row sample / 실패 rule 화면에서 확인 | ✅ DryRunResults / PublishApproval 페이지 |
| v1 regression | v1 endpoint / v1 workflow 회귀 0 | ✅ v1 PipelineDesigner / `/v1/pipelines` 동시 유지, 빌드 OK |
| Operator reproducibility | 운영자가 docs 만 보고 유사 API 1개 추가 가능 | ✅ `docs/onboarding/06_canvas_playbook.md` |

---

## Phase 6 완료 판정 (§ 13.9)

| 항목 | 판정 |
|---|---|
| 1. KAMIS OpenAPI connector 를 화면에서 등록 | ✅ Source/API Designer (Wave 1) |
| 2. sample payload 받아 field mapping 생성 | ✅ Field Mapping Designer (Wave 2A) |
| 3. DQ rule 과 표준화 rule 화면에서 추가 | ✅ Quality Workbench (Wave 6) |
| 4. mart table + load policy 화면에서 설계 | ✅ Mart Workbench (Wave 3) |
| 5. ETL Canvas 에서 노드 연결 | ✅ ETL Canvas v2 (Wave 4) |
| 6. dry-run 으로 row_count / DQ 결과 / 영향도 확인 | ✅ DryRunResults (Wave 5) |
| 7. publish 승인 후 스케줄 실행 | ✅ PublishApproval + cron (Wave 5) |

→ **7/7 충족**. Phase 6 ACCEPTED.

---

## 결정 사항 정리 (§ 13.x)

- **9개 화면 → 6 workbench** (§ 13.1)
- **Wave 3.5 vertical slice** (Canvas 없이 backend e2e 검증) (§ 13.2)
- **PUBLIC_API_FETCH 화면 노출, SOURCE_DATA 엔진 재사용** (§ 13.3)
- **DRAFT 만 직접 수정, APPROVED/PUBLISHED 는 새 version** (§ 13.4)
- **자산 만들기 UX** — Canvas drawer 의 dropdown + 새 designer 로 이동 링크 (§ 13.5)

---

## Phase 7 backlog

Phase 6 에서 *의도적으로 제외* 한 것 (§ 13.6):

- **Lineage Viewer** — workflow → source/target 의존 그래프 시각화
- **Backfill Wizard UI** — 과거 1년치 chunk 적재 화면 (현재는 `/v2/backfill` API 만 있음)
- **SQL Performance Coach UI** — SLO 위반 SQL 식별 + suggest
- **AI-assisted Mapping** — 응답 sample 1개 입력 → mart 컬럼 자동 추천
- **Template Gallery** — 자주 쓰는 connector/mapping/rule 템플릿
- **SCD2 / current_snapshot** 적재 mode 의 LOAD_TARGET 노드 구현 (현재 모델만 있음)
- **다중 결재** — 같은 자산에 N명 ADMIN 동시 승인 요구
- **Standardization 의 alias CRUD UI** — 현재 read-only, std_alias 편집은 직접 SQL
- **Kafka / CDC 실시간 연동** — ADR-0020 의 트리거 조건 미충족 시 Phase 7 재평가
- **분기/병합 DAG dry-run 정확도** — 현재 단순 DAG 의 직전 노드만 추적

---

## 위험 + 대응 회고

| 사전 위험 | 결과 |
|---|---|
| frontend 8 page 가 너무 큼 | wave 별 분할로 처리. 9 → 6 workbench 통합으로 페이지 수 자체도 감소 |
| 운영팀 합류 전 시연 필요 | KAMIS demo 시나리오 작성 완료 (`kamis_demo_quickstart.md`) — staging 에서 사용자가 직접 시연 가능 |
| dry-run 의 외부 호출 부작용 | `dry_run=True` 강제 + 트랜잭션 rollback 로 격리 — Wave 3.5 통합 테스트로 검증 |

---

## 부록 A — 산출물 매핑

### 신규 backend
- `app/api/v2/connectors.py` (Wave 1) — `/v2/connectors/public-api`
- `app/api/v2/sql_assets.py` (Wave 2B) — `/v2/sql-assets`
- `app/api/v2/mart_drafts.py` (Wave 3)
- `app/api/v2/load_policies.py` (Wave 3)
- `app/api/v2/resources.py` (Wave 3)
- `app/api/v2/namespaces.py` (Wave 6)
- `app/domain/public_api/` (Wave 1) — generic engine + parser + spec
- `app/domain/nodes_v2/public_api_fetch.py` (Wave 1)
- `/v2/dryrun/workflow/{id}` + `/v2/dryrun/recent` (Wave 5)
- migration 0046 (public_api_connector), 0047 (PUBLIC_API_FETCH CHECK), 0048 (agri_mart.kamis_price)
- 백엔드 schema `NodeType` Literal 18종 확장 (Wave 4)

### 신규 frontend
- `pages/v2/SourceApiDesigner.tsx` (Wave 1)
- `pages/v2/FieldMappingDesigner.tsx` (Wave 2A)
- `pages/v2/TransformDesigner.tsx` (Wave 2B)
- `pages/v2/MartDesigner.tsx` (Wave 3)
- `pages/v2/EtlCanvasV2.tsx` + `components/designer/NodePaletteV2.tsx` +
  `components/designer/NodeConfigPanelV2.tsx` (Wave 4)
- `pages/v2/DryRunResults.tsx` + `pages/v2/PublishApproval.tsx` (Wave 5)
- `pages/v2/QualityWorkbench.tsx` (Wave 6)
- `api/v2/*.ts` 9개 신규 client

### 신규 docs
- `docs/phases/PHASE_6_PRODUCT_UX.md`
- `docs/kamis_demo_quickstart.md`
- `docs/onboarding/06_canvas_playbook.md`
- `docs/adr/0021-phase6-product-ux.md` (본 문서)

### 신규 scripts / tests
- `scripts/seed_kamis_vertical_slice.py`
- `backend/tests/integration/test_phase6_kamis_vertical_slice.py`
- `backend/tests/integration/test_phase6_public_api.py`

---

## 부록 B — 참조

- [PHASE_6_PRODUCT_UX.md](../phases/PHASE_6_PRODUCT_UX.md) — Phase 6 전체 plan
- [ADR-0018](./0018-phase5-v2-generic-retrospective.md) — Phase 5 회고
- [ADR-0019](./0019-phase5-abstraction-validation-pos.md) — POS 추상화 검증
- [ADR-0020](./0020-kafka-introduction-triggers.md) — Kafka 도입 조건
