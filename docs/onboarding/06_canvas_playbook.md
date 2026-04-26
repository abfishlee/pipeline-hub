# 6. Canvas-기반 새 도메인 추가 Playbook (Phase 6)

> **목적**: 새 운영자가 *코드 한 줄도 짜지 않고* Public API 1개를 등록하여
> 일/주간 자동 적재 파이프라인을 만든다. Phase 6 Wave 7 의 산출물.
>
> 이전 [03_domain_playbook.md](./03_domain_playbook.md) 는 backend API/SQL 기반
> 12 단계로 구성되어 있다. 본 문서는 **6 workbench + ETL Canvas v2** 기반의
> 새로운 표준 절차를 제시한다.

---

## 0. 사전 결정 (운영 매니저)

| 항목 | 결정 |
|---|---|
| domain_code | 소문자/언더스코어 영문, 길이 2~30 |
| resource_code | 대문자/언더스코어 영문, 비즈니스 의미가 드러나야 함 |
| target_table | `<domain>_mart.<resource>` 또는 `<domain>_mart.<custom>` |
| API 인증 방식 | none / query_param / header / basic / bearer 중 선택 |
| 적재 정책 | append_only / upsert / scd_type_2(Phase7+) / current_snapshot(Phase7+) |
| 수집 주기 | 5-필드 cron (UTC) — 예: `0 9 * * *` |

---

## 1. 6 Workbench 통과 — 화면 클릭만으로 자산 등록

### 1.1 Source Workbench (`/v2/connectors/public-api`)

1. `+ 새 connector` 클릭
2. URL / auth / query_template / response_path 입력
3. **"테스트 호출"** → 응답 미리보기 확인
4. DRAFT 저장 → REVIEW → APPROVED → PUBLISHED 전이

### 1.2 Mart Workbench (`/v2/marts/designer`)

**Mart Schema 탭** — 적재할 mart 테이블 설계
1. 컬럼 / 타입 / PK / partition / index 폼 입력
2. **"DDL 생성 + DRAFT 저장"** → diff 미리보기 확인
3. ADMIN 승인 → APPROVED → PUBLISHED → DDL 자동 적용

**Load Policy 탭** — 적재 정책
1. resource 선택 → mode (append/upsert) → key_columns
2. chunk_size / statement_timeout_ms 설정
3. PUBLISHED 까지 전이

### 1.3 Field Mapping Designer (`/v2/mappings/designer`)

1. 도메인 + contract 선택
2. `+ 새 매핑 행` — source_path → target_column + transform_expr
3. 자주 쓰는 함수: `text.trim`, `text.upper`, `number.parse_decimal`,
   `date.normalize_ymd`, `date.parse`, `id.uuid_v4`
4. PUBLISHED 까지 전이

### 1.4 Quality Workbench (`/v2/quality/designer`)

**DQ Rules 탭**
1. 도메인 + target_table 선택
2. `+ 새 DQ Rule` — 6종 rule_kind 중 선택:
   - `row_count_min`: 최소 row 수
   - `null_pct_max`: NULL 비율 % 상한
   - `unique_columns`: 컬럼 조합 unique
   - `reference`: FK-like (다른 mart 참조)
   - `range`: 값 범위
   - `custom_sql`: SELECT 만 허용 (sql_guard 통과 필수)
3. severity (INFO/WARN/ERROR/BLOCK) + sample_limit
4. PUBLISHED 까지 전이

**Standardization 탭**
- read-only: 등록된 namespace 와 표준코드 보기
- alias 편집은 Phase 7 backlog

### 1.5 Transform Designer (`/v2/transforms/designer`)

선택적 — SQL Asset 또는 HTTP Provider 가 필요한 경우만:
- **SQL Asset 탭**: 등록·승인된 SQL artifact (SQL_ASSET_TRANSFORM 노드 backing)
- **HTTP Provider 탭**: provider_kind=HTTP_TRANSFORM 카탈로그 (read-only)
- **Function 탭**: 26+ allowlist 함수 카탈로그 (read-only)
- **Provider 탭**: 전체 provider 카탈로그 (read-only)

### 1.6 ETL Canvas v2 (`/v2/pipelines/designer`)

1. workflow name 입력
2. 좌측 palette 에서 박스 드래그:
   - DATA SOURCES: SOURCE_DATA / **PUBLIC_API_FETCH** / OCR / CRAWL_FETCH
   - TRANSFORM: **MAP_FIELDS** / SQL_INLINE / SQL_ASSET / HTTP / FUNCTION / STANDARDIZE
   - VALIDATE: DEDUP / **DQ_CHECK**
   - LOAD/OUTPUT: **LOAD_TARGET** / NOTIFY
3. 박스 클릭 → 우측 drawer 에서 자산 dropdown 선택
   - 자산이 없으면 **"+ 새 자산"** 링크 → 해당 designer 로 이동
4. 박스 사이 화살표 연결 → **저장**

---

## 2. Run & Publish

### 2.1 Dry-run (검증)

캔버스 toolbar **"Dry-run"** 클릭 → `/v2/dryrun/workflow/{id}`:
- 위상 정렬 순서로 모든 박스 dry-run
- 각 박스 status (success/failed/skipped) + row_count + duration
- 실 mart 변경 0 (rollback 보장)

### 2.2 Publish 승인

자산별 Mini Publish Checklist:
- `/v2/publish/{entity_type}/{entity_id}` 페이지
- 7 항목 자동 평가 → all_passed 시 ADMIN 의 PUBLISH 버튼 enable
- Workflow 자체 PUBLISH: 캔버스 toolbar 의 **"PUBLISH"** 버튼

### 2.3 스케줄 활성화

PUBLISHED 워크플로의 toolbar:
- cron 필드 (5-필드 UTC) 입력
- **활성** 체크박스 → "스케줄 저장"
- 다음 실행 시각 표시

---

## 3. 운영 모니터

| 화면 | 용도 |
|---|---|
| `/pipelines/runs` | 일자별 run 이력 + status |
| `/pipelines/runs/{run_id}` | 박스별 상세 실행 결과 |
| `/runtime` | 실시간 worker 상태 |
| `/v2/dryrun/workflow/{id}` | 최근 dry-run 이력 |
| `/dead-letters` | 실패한 작업 (ADMIN 만) |

---

## 4. 자주 발생하는 함정

| 증상 | 원인 / 조치 |
|---|---|
| 박스 drawer 의 dropdown 이 비어있음 | 같은 도메인의 PUBLISHED 자산이 없음. 1.1~1.5 의 자산을 PUBLISHED 까지 전이 |
| Dry-run 의 PUBLIC_API_FETCH 박스 401 | secret_ref 의 환경변수 미등록. Backend `.env` 또는 NCP Secret Manager 확인 |
| MAP_FIELDS dry-run row_count 0 | upstream 의 source_table 이 아직 생성 전. PUBLIC_API_FETCH 가 먼저 실행되어야 staging 테이블 생성 |
| LOAD_TARGET schema 거부 | sql_guard 정책. `<domain>_mart` schema 만 적재 가능. mart_design 결과의 schema 와 LOAD_TARGET 의 target_table 일치 확인 |
| PUBLISH 버튼 disabled | Mini Checklist 7 항목 중 일부 fail. /v2/publish/.../... 페이지에서 실패 항목 확인 후 자산 보완 |
| transform_expr 검증 실패 | function registry 26 종 외 함수 사용. Transform Designer 의 Function 카탈로그에서 정확한 이름 확인 |

---

## 5. 다음 도메인을 추가할 때 (반복)

새 운영자도 같은 6 workbench + Canvas 흐름을 따른다:

1. **Source Workbench** — 새 OpenAPI connector 등록
2. **Mart Workbench** — 새 mart table + load policy
3. **Field Mapping** — 응답 → mart 매핑
4. **Quality Workbench** — DQ rule
5. **ETL Canvas** — 4박스 조립
6. **Dry-run + Publish** — 검증 + 활성화

> *코드 수정은 다음의 경우에만*: 새로운 transform 함수 추가 (Function registry 확장),
> 새로운 provider 종류 (provider_kind 확장), 새로운 노드 종류 추가.

---

## 6. 참고

- [PHASE_6_PRODUCT_UX.md](../phases/PHASE_6_PRODUCT_UX.md) — Phase 6 전체 plan + KPI
- [kamis_demo_quickstart.md](../kamis_demo_quickstart.md) — KAMIS 13분 시연 시나리오
- [03_domain_playbook.md](./03_domain_playbook.md) — backend API 기반 12 단계 (개발자용)
- [v2_etl_designer.md](./v2_etl_designer.md) — ETL Canvas v1 (Phase 3.2)
- [provider_registry.md](./provider_registry.md) — Provider binding 가이드
- [dq_rule_authoring.md](./dq_rule_authoring.md) — DQ rule 작성 상세
