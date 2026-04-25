# Phase 3 — Visual ETL Designer + SQL Studio (핵심만)

**기간 목표:** **7주 (2026-07-13 ~ 2026-08-29)** — 원래 8~10주에서 압축. 운영팀 합류 9/1 데드라인.
**성공 기준 (DoD):** 기본 파이프라인 설계/실행이 가능하고, SQL sandbox + 승인 플로우가 동작. Visual ETL 고도화는 Phase 4(운영팀 합류 후)로 이월.

**⚠️ 압축된 스코프:** 아래 "Phase 4로 이월" 섹션 참고. 노드 타입도 6종만 우선.

---

## 3.1 Phase 3 범위

**포함:**
- ✅ `wf.pipeline / pipeline_node / pipeline_edge` 기반 정의
- ✅ Pipeline Runtime (자체 DAG 실행기)
- ✅ 노드 상태 실시간 반영 (SSE + Redis Pub/Sub)
- ✅ Visual Designer 프론트 (React Flow)
- ✅ **노드 타입 6종 (압축):**
  `SOURCE_API / SQL_TRANSFORM / DEDUP / DQ_CHECK / LOAD_MASTER / NOTIFY`
  - Phase 4로 이월: `SOURCE_DB`, `OCR`, `CRAWLER`, `HUMAN_REVIEW`
- ✅ SQL Studio
  - sqlglot 기반 정적 검증
  - sandbox 실행 (임시 schema)
  - 실행 계획 조회
  - 승인 플로우 (mart 쓰기는 APPROVER role만)
  - lineage 자동 추출 (OpenLineage 이벤트)
- ✅ 배치 스케줄 화면 (cron 편집, Backfill 트리거)
- ✅ 파이프라인 버전 관리 (PUBLISHED 버전 별도)
- ✅ SQL 템플릿 라이브러리 (자주 쓰는 정제 쿼리)

**제외 (Phase 4로 이월):**
- ❌ 추가 노드 타입 (`SOURCE_DB`, `OCR`, `CRAWLER`, `HUMAN_REVIEW`)
- ❌ SQL lineage 자동 추출 (OpenLineage)
- ❌ Pipeline 버전 diff 뷰
- ❌ Backfill UI (Airflow CLI 사용으로 대체)
- ❌ 템플릿 라이브러리 고도화
- ❌ Crowd 정식 검수 UI
- ❌ 외부 공개 API
- ❌ CDC 통합
- ❌ 커스텀 Python 코드 노드 (영구 제외 — 보안)

---

## 3.2 작업 단위 체크리스트

### 3.2.0 의존성 사전점검 (Phase 2 완료 시점 — 2026-04-25 확인)

Phase 2 의 chassis 위에 얹는 항목이라 신규 의존성보단 *위치 결정* 위주.

**필요 마이그레이션 (예약 번호)** — 0014 까지 사용했고, 다음 가용 번호는 `0015`.

| 번호 | 파일 | 책임 |
|---|---|---|
| 0015 | `migrations/versions/0015_workflow_definition.py` | `wf` schema 신설 + `wf.workflow_definition` (PUBLISHED 버전) + `wf.node_definition` + `wf.edge_definition` (`from_node_id`, `to_node_id`, `condition_expr` JSON) |
| 0016 | `migrations/versions/0016_pipeline_run.py` | `run.pipeline_run` (RANGE 파티션 by run_date) + `run.node_run` (FK pipeline_run + node_definition_id, 상태머신 PENDING/READY/RUNNING/SUCCESS/FAILED/SKIPPED) |
| 0017 | `migrations/versions/0017_sql_studio.py` | `wf.sql_query` (사용자 작성 쿼리) + `wf.sql_query_version` (immutable) + `wf.sql_run` (sandbox 실행 이력) |

**ORM 모델 추가 위치**

| 파일 | 추가할 클래스 |
|---|---|
| `backend/app/models/wf.py` (신규) | `WorkflowDefinition`, `NodeDefinition`, `EdgeDefinition`, `SqlQuery`, `SqlQueryVersion`, `SqlRun` |
| `backend/app/models/run.py` (확장) | `PipelineRun`, `NodeRun` (기존 `IngestJob`/`EventOutbox`/`ProcessedEvent`/`DeadLetter`/`CrowdTask` 와 같은 schema) |

**도메인 / API / Frontend 추가 위치 (CURRENT.md 의 "Phase 3 대상 모듈" 표 참조)**

- `backend/app/domain/pipeline_runtime.py` — DAG 실행기 (위상 정렬 + 노드 actor 디스패치 + node_run 상태 갱신)
- `backend/app/domain/nodes/` — 노드 6종 구현 (`source_api.py`, `sql_transform.py`, `dq_check.py`, `dedup.py`, `load_master.py`, `notify.py`). 각 파일은 `Node Protocol` 을 만족하는 단일 클래스/함수.
- `backend/app/api/v1/pipelines.py` + `sql_studio.py`
- `backend/app/integrations/sqlglot_validator.py` — sqlglot 으로 SQL AST 분석. 참조 schema 화이트리스트(`mart`, `stg`) + 위험 함수(`pg_read_*`, `COPY`) 차단.
- `frontend/src/pages/{PipelineDesigner,SqlStudio,PipelineRunDetail}.tsx`

**기존 자산 재사용 (Phase 1·2 chassis)**

| Phase 3 사용 | Phase 1·2 자산 |
|---|---|
| 노드 actor 트리거 | `app/workers/pipeline_actor` 데코레이터 (Phase 2.2.1) |
| 노드 상태 SSE | Redis Pub/Sub — `app/core/events.py` 의 `RedisStreamPublisher` 패턴 (Phase 2.2.2) |
| sqlglot sandbox 실행 권한 | `require_roles("ADMIN", "APPROVER")` (Phase 1.2.4) |
| node_run 실행 이력 → mart 반영 | `app/domain/price_fact.py` 의 upsert 헬퍼 (Phase 2.2.6) 재사용 |
| 노드 실패 → DLQ 자동 격리 | `DeadLetterMiddleware` (Phase 2.2.1) — 노드 actor 도 같은 broker 위에서 동작 |

**신규 의존성**

- `sqlglot>=25.x` (SQL 정적 분석)
- React Flow 는 frontend 에 추가 (`@xyflow/react`)

다른 외부 SDK / DB 익스텐션은 추가 없음. ADR-0007 (sqlglot vs PostgreSQL EXPLAIN-only)
은 Phase 3.2.4 SQL Studio 진입 시 작성.

### 3.2.1 Pipeline Runtime [W1~W2]

**기반 (이번 commit) — DAG 메타 + 실행 이력 + 토폴로지 dispatcher + NOOP 노드**
- [x] Migration 0015 — `wf.workflow_definition` (status DRAFT/PUBLISHED/ARCHIVED, UNIQUE(name,version)) + `wf.node_definition` (UNIQUE(workflow_id,node_key)) + `wf.edge_definition` (UNIQUE(workflow_id,from,to), `condition_expr JSONB`, no-self-loop CHECK) ✅ 2026-04-25
- [x] Migration 0016 — `run.pipeline_run` (RANGE 파티션 by run_date, 2026-04~2026-12 9개월, PK 합성 (run_id, run_date)) + `run.node_run` (status PENDING/READY/RUNNING/SUCCESS/FAILED/SKIPPED/CANCELLED, 합성 FK to pipeline_run, output_json) + BRIN(started_at) + partial idx(PENDING/READY/RUNNING) ✅ 2026-04-25
- [x] ORM — `app/models/wf.py` 신규 (`WorkflowDefinition` / `NodeDefinition` / `EdgeDefinition` + relationships, cascade="all, delete-orphan"). `app/models/run.py` 에 `PipelineRun` / `NodeRun` 추가 (합성 FK는 `ForeignKeyConstraint`) ✅ 2026-04-25
- [x] `app/domain/pipeline_runtime.py` ✅ 2026-04-25
  - `start_pipeline_run` — Kahn 토폴로지 정렬 (cycle 시 ValueError → 422), pipeline_run + node_run 일괄 INSERT, entry 노드들 READY 마킹
  - `complete_node` — SUCCESS/FAILED/SKIPPED 종결 + Pub/Sub 발행 + 후속 노드 입력 모두 SUCCESS 시 READY 전이 + 자가 fan-out 시 다음 dispatch. FAILED 시 도달 가능한 모든 PENDING/READY 후속 노드를 SKIPPED 마킹
  - `mark_node_running` — actor 가 시작 시 호출 (idempotent — 이미 진행 중이면 그대로 반환)
  - `cancel_pipeline_run` — RUNNING/PENDING node 들을 CANCELLED 일괄 마킹
- [x] `app/workers/pipeline_node_worker.py::process_node_event(event_id, node_run_id, run_date_iso)` actor (queue=pipeline_node, max_retries=3, time_limit=120s, idempotent consumer="pipeline-node-worker"). NOOP 노드만 즉시 SUCCESS 처리, 다른 type 은 `NotImplementedError` (3.2.2 후속) ✅ 2026-04-25
- [x] `app/core/events.py::RedisPubSub` — `publish(channel, payload)` 동기/`apublish` 비동기. `pipeline:{pipeline_run_id}` 채널에 노드 상태 전이 JSON 발행 ✅ 2026-04-25
- [x] `event_topics`: `EventTopic.PIPELINE_NODE_STATE` + `PipelineNodeStateChangedPayload` ✅ 2026-04-25
- [x] 메트릭 — `pipeline_runs_total{status}` Counter, `pipeline_node_runs_total{node_type,status}` Counter, `pipeline_run_duration_seconds` Histogram ✅ 2026-04-25
- [x] `app/api/v1/pipelines.py` — `POST /v1/pipelines` (nodes/edges 일괄, ADMIN/APPROVER), `GET` 목록·`GET /{id}` 상세 (OPERATOR+), `PATCH /{id}` (DRAFT 만, replace_graph), `PATCH /{id}/status` (전이 검증), `POST /{id}/runs` (PUBLISHED 만, 202), `GET /runs/{run_id}` (node_runs 포함). `app/schemas/pipelines.py` + `app/repositories/pipelines.py`. `main.py` 라우터 등록 ✅ 2026-04-25
- [x] 통합 테스트 ✅ 2026-04-25 — `tests/integration/test_pipeline_runtime.py` (5건):
  - DRAFT 생성 → PATCH (DRAFT) → PUBLISH 전이 → PUBLISHED 상태 PATCH 차단
  - cycle 워크플로 → POST /runs 시 422
  - NOOP 3-노드 직선 DAG → API 트리거 → entry 1 READY 확인 → 도메인 직접 SUCCESS 마킹 3회 → pipeline 종결 SUCCESS + Pub/Sub 메시지 SUCCESS 수신
  - cancel_pipeline_run → 모든 비종결 node CANCELLED 마킹
  - VIEWER 403 차단

**다음 sub-phase (3.2.2~) 로 분리**
- [ ] 노드 단위 재시도/타임아웃 (현재는 actor max_retries=3 + time_limit=120s)
- [ ] 조건부 엣지 (`condition_expr` 평가) — Phase 3.2.2 노드 구현 시 도입
- [ ] 병렬 노드 실행 — actor enqueue 패턴이 자체적으로 병렬화 (현재도 동작), 동시성 제한 옵션은 후속
- [ ] 장기 실행 노드 (HUMAN_REVIEW async wait) — Phase 4 정식 Crowd 와 결합
- [ ] 노드 종료를 Redis Streams 로도 발행 (현재 Pub/Sub 만) — SSE bridge 필요시 추가

### 3.2.2 노드 실행자 구현 [W2~W4]

각 노드 타입별 executor 클래스:

| 노드 | 입력 | 동작 | 출력 |
|---|---|---|---|
| SOURCE_API | config.source_code, since | 수집 job 시작 | raw_object ids |
| SOURCE_DB | config.connector_id, mode | snapshot/incremental | staging rows |
| OCR | config.engine, confidence_threshold | raw image → ocr_result | ocr_result_ids |
| CRAWLER | config.crawler_id | 크롤러 실행 | raw_web_page_ids |
| SQL_TRANSFORM | config.sql_id (또는 inline sql) | sandbox → 검증 → 실제 실행 | rows affected |
| DEDUP | config.key, strategy | stg/mart dedup | kept/removed count |
| DQ_CHECK | config.rule_ids | 규칙 실행 | pass/fail, 샘플 |
| LOAD_MASTER | config.target_table | staging → mart upsert | upserted count |
| HUMAN_REVIEW | config.task_kind | crowd_task 생성 후 wait | 검수 결과 반영 |
| NOTIFY | config.channel, template | 알림 전송 | ok/err |

- [ ] 각 executor는 `input_count/output_count/error_count/metrics_json` 기록.
- [ ] 실패 시 `error_message` + stack trace → `run.dead_letter` 옵션.

### 3.2.3 실시간 상태 반영 [W4]

- [ ] `GET /v1/pipeline-runs/{id}/stream` (SSE)
  - Redis `SUBSCRIBE pipeline:{id}` → 이벤트 플러시
- [ ] 초기 스냅샷: 현재 상태 + 이후 diff 이벤트
- [ ] 브라우저 재연결 시 last-event-id 기반 이어받기
- [ ] WebSocket 대신 SSE 채택 (프록시 친화 + 단방향)

### 3.2.4 Visual Designer 프론트 [W4~W6]

- [ ] `frontend/src/pages/PipelineDesigner.tsx`
- [ ] React Flow 기반 캔버스
  - 좌측 팔레트: 노드 카드 (type별 아이콘)
  - 중앙 캔버스: 노드 드래그/엣지 연결
  - 우측 속성 패널: 선택된 노드의 config_json 편집 (스키마별 JSON Form)
- [ ] 노드 색상:
  `PENDING(회색)/READY(파랑)/RUNNING(노랑)/SUCCESS(초록)/FAILED(빨강)/SKIPPED(회색 점선)/RETRYING(주황)`
- [ ] 상단 툴바: 저장 / 검증 / 실행 / 예약 / 배포(PUBLISHED 승격)
- [ ] 저장 시 서버측 validation (토폴로지 사이클 금지, 필수 config 체크)
- [ ] 실행 중에는 캔버스를 읽기 전용으로 전환, 실시간 상태 반영
- [ ] 하단 로그 패널: SSE 실시간 메시지 스트림

### 3.2.5 SQL Studio [W6~W8]

- [ ] `app/domain/sql_studio.py`:
  - sqlglot 파싱 (dialect=postgres)
  - 금지 연산: `DROP/TRUNCATE/ALTER/GRANT/REVOKE/CREATE ROLE/COPY TO`
  - 대상 스키마 제한: VIEWER/OPERATOR → `stg/mart` 읽기만; APPROVER → mart 쓰기 승인 가능
  - sandbox: `sql_sandbox_{user_id}_{uuid}` 스키마 임시 생성 → `CREATE TABLE AS SELECT` → 결과 미리보기 → 세션 종료 후 DROP
  - 실행 계획: `EXPLAIN (FORMAT JSON)` 결과 UI 표시
  - lineage: sqlglot AST → 테이블 의존성 그래프 추출 → OpenLineage RunEvent 생성
- [ ] API:
  - `POST /v1/sql/validate` — 정적 검증만
  - `POST /v1/sql/preview` — sandbox 실행 (row limit 1,000)
  - `POST /v1/sql/explain`
  - `POST /v1/sql/submit` — 승인 요청 생성
  - `POST /v1/sql/approvals/{id}/approve` (APPROVER)
  - `POST /v1/sql/approvals/{id}/reject`
  - 승인된 SQL을 Visual Pipeline의 `SQL_TRANSFORM` 노드에 연결 가능
- [ ] 모든 실행은 `audit.sql_execution_log` 기록
- [ ] 프론트: Monaco Editor + 결과 테이블 + EXPLAIN 뷰

### 3.2.6 파이프라인 버전/배포 [W8]

- [ ] DRAFT → PUBLISHED 승격 시 새 `version_no` 할당
- [ ] 실행은 PUBLISHED 버전만 (또는 개발자가 DRAFT 수동 실행 허용)
- [ ] 배포 이력(`wf.pipeline_release`) 테이블 추가 (Phase 3에서 도입)
- [ ] PUBLISHED 버전 간 diff 뷰 (노드 추가/삭제/config 변경 표시)

### 3.2.7 배치 스케줄 관리 [W8~W9]

- [ ] `pipeline.schedule_cron` 편집 UI
- [ ] Backfill: 시작/종료 기간 입력 → 일자별 run 생성
- [ ] 실행 이력 검색 (status, 기간, 소스)
- [ ] 수동 재실행 / 특정 노드부터 재실행

### 3.2.8 문서/템플릿 [W9~W10]

- [ ] `docs/pipelines/` 에 샘플 파이프라인 YAML 3종:
  - `retail_api_price.yaml` — API 수집 → 검증 → 표준화 → mart
  - `receipt_ocr.yaml` — 영수증 → OCR → 검수 큐 → mart
  - `online_crawl.yaml` — 크롤 → 파싱 → dedup → mart
- [ ] 시스템 기본 pipeline seed: `scripts/seed_default_pipelines.py`
- [ ] SQL 템플릿 라이브러리 10개 이상 (표준화 확인 쿼리, 이상치 탐지 등)

---

## 3.3 샘플 시나리오

1. 운영자가 Visual Designer에서 "주간 이마트 가격 통합" 파이프라인을 설계.
2. `SOURCE_API(EMART)` → `DQ_CHECK(필수필드)` → `SQL_TRANSFORM(정규화)` → `DEDUP(business_key=sku)` → `LOAD_MASTER(price_fact)` → `NOTIFY(slack)` 연결.
3. SQL 노드의 쿼리는 SQL Studio에서 sandbox 실행 + 승인 완료한 것.
4. `매일 05:00` cron 설정 후 "배포" → PUBLISHED.
5. 즉시 실행 버튼으로 실행 → 노드가 순서대로 색 변화 (파랑 → 노랑 → 초록).
6. 중간 실패 시 빨강 표시 + 하단 로그 패널에 에러 + "재실행" 버튼 활성.
7. 스케줄러가 다음날 05:00에 자동 실행.

---

## 3.4 비기능 기준

- [ ] 노드 100개 규모 파이프라인도 UI 렌더 1초 이내.
- [ ] 상태 변경 → SSE 화면 반영 < 500ms.
- [ ] sandbox SQL 실행은 read-only replica 사용 (mart 부하 영향 방지) — dev 환경부터 적용.
- [ ] sqlglot 검증: 금지 연산 100% 차단 테스트.
- [ ] lineage 자동 추출 성공률 ≥ 95% (테스트 SQL 100개 기준).

---

## 3.5 보안 체크

- [ ] SQL sandbox 스키마는 사용자 자기 스키마만 생성/drop 가능.
- [ ] sandbox SQL 실행은 statement_timeout 30초 강제.
- [ ] sandbox connection은 read-only role + 쓰기는 `sql_sandbox_*` 스키마만.
- [ ] 모든 SQL 실행은 audit에 원문 전체 기록 (개행 포함).
- [ ] API Approver ≠ Submitter 체크 (self-approve 금지).
