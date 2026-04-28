# Phase 8.6 — 웹에서 직접 검증하는 시나리오

**날짜:** 2026-04-27
**목적:** 사용자가 *공용 데이터 수집 파이프라인 플랫폼* 의 핵심 흐름을
웹 화면에서 직접 단계별로 검증할 수 있도록.

**도메인 무관 시나리오** — IoT 센서 데이터를 *예시* 로 사용. 농축산물/부동산/IT 등 어떤
도메인이든 같은 절차.

---

## 0. 사전 준비

```bash
# (선택) 기존 데이터 모두 wipe
cd backend
PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe \
  ../scripts/phase8_6_wipe_all.py --yes

# 인프라 + 서버 가동
cd infra && docker compose up -d
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
cd backend && uvicorn app.main:create_app --factory --port 8000
cd frontend && pnpm dev
```

이후 http://localhost:5173 → admin/admin 로그인.

---

## 시나리오 단계 (웹 화면)

### Step 1 — 실 API 선정

외부에서 호출 가능한 테스트/실증 API endpoint 를 하나 정한다. 응답은 JSON/XML/CSV/TSV/TEXT/Excel/Binary 중 하나여야 한다.

**검증**: 브라우저나 curl 로 endpoint 호출 시 200 응답과 샘플 body 확인.

### Step 2 — Source / API Connector 등록

화면: **좌측 메뉴 → "Source / API Connector"** (`/v2/connectors/public-api`)

1. [+ 새 API 등록]
2. domain: `iot` (없으면 신규 등록 — 도메인 무관 시나리오 시연용)
3. resource_code: `sensor_reading`
4. endpoint_url: Step 1 의 실 API URL 붙여넣기
5. http_method: `GET`, auth_method: `none`
6. response_format: `json`, response_path: `$.items`
7. [저장] → DRAFT
8. [Test Call] 버튼 → 5건 row 응답 확인
9. DRAFT → REVIEW → APPROVED → PUBLISHED 순서로 transition

**검증**: 화면에 PUBLISHED 배지.

### Step 3 — Mart Workbench

화면: **좌측 메뉴 → "Mart Workbench"** (`/v2/marts/designer`)

1. [+ 새 Mart 설계]
2. domain: `iot`, schema: `iot_mart`, table: `sensor_reading`
3. 컬럼: `sensor_id TEXT PK`, `value NUMERIC(10,2)`, `ts TIMESTAMPTZ PK`
4. DDL 미리보기 → DRAFT 저장 → REVIEW → APPROVED → PUBLISHED
5. Load Policy 탭에서 mode=`upsert`, key_columns=`["sensor_id","ts"]` 등록

**검증**: 화면에 mart + load_policy 모두 PUBLISHED.

### Step 4 — Field Mapping Designer

화면: **좌측 메뉴 → "Field Mapping Designer"** (`/v2/mappings/designer`)

1. domain: `iot`, contract: Step 2 connector 자동 생성
2. [+ 새 매핑 행] → 우측의 **JSON Path Picker** 에 Step 2 test call sample body 붙여넣기
3. tree 의 leaf (`sensor_id`, `value`, `ts`) 클릭 → source_path 자동 입력
4. target_table: `iot_mart.sensor_reading`, target_column 각각 매핑
5. transform_expr: `sensor_id` 는 `text.trim`, `value` 는 `number.parse_decimal`
6. DRAFT → ... → PUBLISHED

**검증**: 화면에 mapping 3행 PUBLISHED + Dry-run 통과.

### Step 5 — Quality Workbench

화면: **좌측 메뉴 → "Quality Workbench"** (`/v2/quality/designer`)

1. domain: `iot`
2. target_table: **dropdown 에서** `iot_mart.sensor_reading` 선택 (Phase 8.6 카탈로그 통합)
3. [+ 새 DQ Rule]
4. rule_kind: `row_count_min` → rule_json: `{"min": 1}`
5. severity: `ERROR`, fail_action: `block`
6. PUBLISHED

**검증**: 화면에 DQ rule 1건 PUBLISHED.

### Step 6 — ETL Canvas V2

화면: **좌측 메뉴 → "ETL Canvas"** (`/v2/pipelines/designer`)

1. 빈 캔버스 — 상단의 **Phase 8.6 권장 패턴 박스** 확인
2. 좌측 팔레트에서 노드 4개 끌어다 놓기:
   - `SOURCE_DATA` (source_code = `phase86_iot_src` — Step 2 자동 생성)
   - `MAP_FIELDS` (Step 4 매핑 선택)
   - `DQ_CHECK` (Step 5 룰 선택)
   - `LOAD_TARGET` (Step 3 load_policy 선택)
3. 노드 간 edge 연결 (왼쪽→오른쪽)
4. workflow name: `phase86_iot_pipeline` → [저장] → DRAFT
5. [Dry-run] → 4 노드 모두 통과
6. PUBLISHED 로 transition
7. **Cron Picker (Phase 8.6)**: 모드 = `1 분마다` → 활성 → 스케줄 저장

**검증**:
- Canvas 에 4 노드 PUBLISHED
- 다음 실행 시각 미리보기 노출
- 화면 상단의 schedule 정보에 `*/1 * * * *` 표시

### Step 7 — Pipeline Runs (자동 trigger 검증)

화면: **좌측 메뉴 → "Pipeline Runs"** (`/pipelines/runs`)

1. (Airflow 가 가동 중이면) 1~2 분 대기
2. 화면 새로고침 → `phase86_iot_pipeline` 의 신규 RUNNING/SUCCESS run 1건 자동 생성 확인
3. (Airflow 미가동이면) Canvas 에서 [실행] 버튼으로 수동 trigger

**검증**: pipeline_run 1건 SUCCESS, node_run 4건 모두 SUCCESS.

### Step 8 — Pipeline Run Detail

화면: 위 run 클릭 → `/pipelines/runs/{id}`

1. ReactFlow 캔버스에 4 노드 모두 초록색 (SUCCESS)
2. **Phase 8.5 — 노드 timeline (gantt-mini)** 에서 각 노드의 duration 시각화
3. 각 노드의 output preview 펼쳐서 row count 확인

### Step 9 — Service Mart Viewer + Operations Dashboard

화면: **`/v2/operations/dashboard`**

1. **SLA Lag** 카드 — p95 lag 표시 (수집→적재)
2. **Auto Dispatcher** — RUNNING
3. **Airflow Scheduler** (Phase 8.6) — RUNNING/STOPPED 표시
4. **채널 데이터 신선도** — 등록한 채널 노출
5. **Provider 호출/비용** — 외부 호출 0건 (Mock 은 비용 없음)
6. **24h 시간별 추이** — 최근 1건 막대 표시
7. **최근 실패 10건** — 비어 있어야 함 (모두 SUCCESS)

### Step 10 — Quick Start 카드 검증

화면: **Dashboard** (`/`)

1. **Quick Start 카드** 5/5 완료 → "✓ 준비 완료" 녹색 배너
2. 각 단계가 Source 1+ / Mapping 1+ / Mart 1+ / Workflow 1+ / Run 1+ 모두 PUBLISHED 로 카운트

---

## 자동 검증 (선택)

위 시나리오 중 *backend 데이터 흐름 부분* 만 자동 검증:

```bash
cd backend
PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m pytest \
  tests/integration/test_phase8_6_scenario.py -v
```

10 단계 모두 통과 시 시나리오 핵심 plumbing 검증 완료. 단, 위 *웹 시나리오* 의
Canvas 작성·실행 부분은 사용자가 직접 화면에서 검증.

---

## 통과 조건

- [ ] Step 1: Mock 등록 완료 + serve URL 200
- [ ] Step 2: Connector PUBLISHED + Test Call 5 row
- [ ] Step 3: Mart + load_policy PUBLISHED
- [ ] Step 4: 매핑 PUBLISHED + Dry-run 통과
- [ ] Step 5: DQ rule PUBLISHED
- [ ] Step 6: Workflow PUBLISHED + Cron Picker 1분마다
- [ ] Step 7: pipeline_run 자동 생성 + SUCCESS
- [ ] Step 8: 노드 timeline + output preview 정상
- [ ] Step 9: Operations Dashboard 6 카드 모두 정상 표시
- [ ] Step 10: Quick Start 5/5 완료 배너

모든 항목 통과 = Phase 8.6 시나리오 검증 완료. **Phase 9 진입 가능**.
