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

**기반 (이번 commit) — 6 노드 + sqlglot 검증 + dq schema + dispatcher**
- [x] `app/integrations/sqlglot_validator.py` — sqlglot.parse_one + AST 분석. SELECT 만 허용 (CTE/UNION/INTERSECT/EXCEPT 포함), 참조 schema 화이트리스트 mart/stg/wf, 함수 블랙리스트 (pg_read_*/lo_*/dblink/current_setting/set_config + 명시 함수 7건), 키워드 정규식(COPY/VACUUM/ANALYZE/...), AST 깊이 100 한도, multi-statement 거부 ✅ 2026-04-25
- [x] `app/domain/nodes/__init__.py` — `NodeProtocol(run(context, config) → NodeOutput)` (sync), `NodeContext(session, pipeline_run_id, node_run_id, node_key, user_id, upstream_outputs)`, `NodeOutput(status='success'|'failed', row_count, payload, error_message)`, `NodeError`. `get_node_runner(node_type)` 가 7종 디스패치 (NOOP 포함) ✅ 2026-04-25
- [x] 6 노드 구현 ✅ 2026-04-25
  - `source_api.py` — `raw.raw_object` SELECT (limit/since_partition_date/include_payload), payload.rows 에 dict list
  - `sql_transform.py` — sqlglot 검증 → `CREATE TABLE wf.tmp_run_<id>_<key> AS (sql)` (또는 dry-run COUNT). 출력 테이블 정규식 `wf.[a-zA-Z_][a-zA-Z0-9_]{0,62}` 강제
  - `dedup.py` — `SELECT DISTINCT ON (keys) * FROM input ORDER BY keys, ctid ASC|DESC` 로 keep first/last
  - `dq_check.py` — 4종 assertion (row_count_min / null_pct_max / unique_columns / custom_sql) → `dq.quality_result` 적재. severity ERROR/BLOCK 위반 시 NodeOutput.status='failed', WARN 은 success 유지
  - `load_master.py` — sandbox(`wf`/`stg`) → mart `INSERT ON CONFLICT (key_columns) DO UPDATE`. update_columns 자동 추출(공통 non-key) 또는 명시
  - `notify.py` — `EventOutbox(notify.requested)` 적재만 (실 webhook 호출은 Phase 4)
- [x] Migration 0017 + ORM `app/models/dq.py` — `dq.quality_result` (check_kind 4종 CHECK, severity 4종 CHECK, partial idx passed=FALSE, BRIN created_at 대신 일반 idx) ✅ 2026-04-25
- [x] `app/workers/pipeline_node_worker._execute_node` — `get_node_runner(node_type).run(context, config)` 호출. NodeError → 노드 FAILED + downstream SKIP. NodeOutput.status='failed' → 동일 처리 + payload 보존. 비즈니스 실패와 인프라 예외 분리 ✅ 2026-04-25
- [x] 의존성 — `pyproject.toml` `sqlglot>=25,<27` ✅ 2026-04-25
- [x] 테스트 ✅ 2026-04-25
  - `tests/test_sqlglot_validator.py` (12건) — SELECT 통과 / JOIN / 비허용 schema 거부 / unqualified 거부 / INSERT/UPDATE/DELETE/DROP 거부 / pg_read_file 거부 / COPY 키워드 거부 / multi-statement 거부 / 빈 SQL 거부 / FROM 없는 SELECT 거부
  - `tests/integration/test_nodes.py` (8건) — SOURCE_API 3건 시드 → 3건 반환, SQL_TRANSFORM happy + sandbox table 생성, 위험 SQL 5종 parametrized 거부, DEDUP 3-key, DQ_CHECK 통과(3 assertion 모두) + 실패 분기(row_count_min 위반), LOAD_MASTER mart.standard_code UPSERT, NOTIFY outbox 적재, NOOP 회귀
- [x] `input_count/output_count/error_count/metrics_json` — `node_run.output_json` 에 NodeOutput.payload 저장 (메트릭 JSON 역할) ✅ 2026-04-25 (전용 컬럼은 후속 sub-phase 에서 필요 시 추가)

**다음 sub-phase 로 분리**
- [ ] `SOURCE_DB`, `OCR`, `CRAWLER`, `HUMAN_REVIEW` 노드 — Phase 4 (각 도메인이 이미 구현되어 있어 노드 wrapper 만 추가하면 됨)
- [ ] sandbox 테이블 cleanup — pipeline_run 종결 시 `wf.tmp_run_<id>_*` 일괄 DROP (현재는 누적)
- [ ] error_message + stack trace → `run.dead_letter` 자동 적재 옵션 (현재는 NodeError 만 actor retry)
- [ ] DQ rule library — `dq.rule` 테이블 + UI 에서 rule 등록 후 `rule_ids` 로 참조 (현재는 inline assertions)

### 3.2.3 실시간 상태 반영 [W4]

**기반 (이번 commit) — SSE 라우터 + async Pub/Sub + React Flow read-only + 실행 이력 페이지**
- [x] `GET /v1/pipelines/runs/{run_id}/events` (SSE) — `app/api/v1/sse.py`. ADMIN/APPROVER/OPERATOR 만, pipeline_run 미존재 시 404, opening event + Redis `pipeline:{run_id}` Pub/Sub forward + 30s heartbeat ✅ 2026-04-25
- [x] `app/core/sse.py` — `format_event(event, data, event_id)`, `heartbeat_event`, `merged_with_heartbeat(source, interval)` (asyncio.Queue 기반 동시성), `SSE_HEADERS`(no-cache, no-transform, X-Accel-Buffering: no, keep-alive) ✅ 2026-04-25
- [x] `app/integrations/redis_pubsub_async.py::AsyncRedisPubSub` — `redis.asyncio.from_url`, async context manager, `subscribe(channel) → AsyncIterator[str]`, control 메시지(subscribe/unsubscribe/pong) 무시, finally 에서 unsubscribe + connection close ✅ 2026-04-25
- [x] WebSocket 대신 SSE 채택 — proxy 친화 (`X-Accel-Buffering: no`), 단방향 stream 충분, EventSource API 표준 ✅ 2026-04-25
- [x] Frontend `usePipelineRunSSE` 훅 — `@microsoft/fetch-event-source` 로 Authorization Bearer 헤더 지원 (브라우저 EventSource 한계 회피). `node.state.changed` 수신 시 React Query cache 무효화 + `lastEvent` state 노출 + 인증 만료 시 재시도 중단. cleanup on unmount via AbortController ✅ 2026-04-25
- [x] Frontend `pages/PipelineRunDetail.tsx` — `@xyflow/react` read-only 캔버스 (workflow nodes/edges) + 노드 상태 색상 (PENDING 회색 / READY 파랑 / RUNNING 주황 / SUCCESS 녹 / FAILED 빨 / SKIPPED 회) + SSE 실시간 갱신 + 폴링 fallback (5s) ✅ 2026-04-25
- [x] Frontend `pages/PipelineRunsList.tsx` — workflow 별 필터 + 표 + 상세 진입 ✅ 2026-04-25
- [x] Sidebar "파이프라인 실행" 메뉴 + Routes 등록 (`/pipelines/runs`, `/pipelines/runs/:runId`) + `currentTitle` 갱신 + `frontend/src/api/pipelines.ts` (TanStack Query hooks). `pnpm add @xyflow/react @microsoft/fetch-event-source` ✅ 2026-04-25
- [x] 테스트 ✅ 2026-04-25
  - `tests/test_sse_format.py` (7건, 단위) — JSON dict / string / multi-line / event_id / None data / heartbeat / 한글 unicode
  - `tests/integration/test_sse.py` (5건, 실 PG + 실 Redis) — 미인증 401-403 / VIEWER 403 / unknown run 404 / 정상 stream (별도 thread 에서 publish 시 `event: open` + `event: node.state.changed` + data 라인 수신) / SSE 헤더 정합

**다음 sub-phase 로 분리 (3.2.4 또는 후속)**
- [ ] 초기 스냅샷 — connect 직후 현재 node_run 상태 일괄 발행 (현재는 폴링 fallback 으로 보충)
- [ ] last-event-id 기반 재연결 이어받기 — Redis Streams `XRANGE` 로 갈음 가능 (현재는 fetch-event-source 의 자동 reconnect 만)
- [ ] SSE 멀티 채널 (다른 도메인 — Crowd 검수 큐 변경, DLQ 신규) — 현재는 pipeline 만

### 3.2.4 Visual Designer 프론트 [W4~W6]

- [x] `frontend/src/pages/PipelineDesigner.tsx` ✅ 2026-04-25
- [x] React Flow 기반 편집 캔버스 ✅ 2026-04-25
  - 좌측 팔레트: 7종 노드 카드 (type별 lucide 아이콘 — NOOP/SOURCE_API/SQL_TRANSFORM/DEDUP/DQ_CHECK/LOAD_MASTER/NOTIFY)
  - 중앙 캔버스: drag-and-drop 추가 / `onConnect` 엣지 연결 / `onPaneClick` 선택 해제 / `screenToFlowPosition` 좌표 변환
  - 우측 속성 패널: 선택된 노드의 `node_key`/`position_{x,y}`/`config_json` 편집 (textarea + JSON parse on blur + type별 hint snippet)
  - 하단: SQL Studio dry-run validate (선택된 SQL_TRANSFORM 노드의 `config_json.sql` 로 자동 반영)
- [x] 노드 색상 (PENDING/READY/RUNNING/SUCCESS/FAILED/SKIPPED) — Phase 3.2.3 `PipelineRunDetail` 에서 이미 구현. Designer 페이지는 편집 전용이므로 status 색상 미적용 ✅ 2026-04-25
- [x] 상단 툴바: 저장 (POST 신규 / PATCH 기존 자동 분기) / PUBLISH (DRAFT→PUBLISHED) / 실행 (PUBLISHED 한정) ✅ 2026-04-25
- [x] 저장 시 서버측 validation 활용 — 백엔드 `pipelines.replace_graph` 가 cycle/엣지 키 매칭 검증 ✅ 2026-04-25
- [x] PUBLISHED/ARCHIVED 진입 시 캔버스 readonly 자동 전환 (`nodesDraggable={false}`/`nodesConnectable={false}`) ✅ 2026-04-25
- [x] SQL Studio dry-run API + UI ✅ 2026-04-25
  - `app/api/v1/sql_studio.py`: `POST /v1/sql-studio/validate` (ADMIN/APPROVER/OPERATOR) — sqlglot AST 정적 분석 결과 반환
  - `app/schemas/sql_studio.py`: `SqlValidateRequest`/`SqlValidateResponse`
  - `frontend/src/api/sql_studio.ts`: `useValidateSql` mutation
  - `frontend/src/components/designer/SqlEditor.tsx`: textarea + 검증 버튼 + 통과/실패 배너 + 참조 테이블 노출
- [x] Frontend API mutations (`createWorkflow` / `updateWorkflow` / `transitionStatus` / `triggerRun`) — `frontend/src/api/pipelines.ts` ✅ 2026-04-25
- [x] Sidebar "Visual ETL Designer" 메뉴 (ADMIN/APPROVER 전용 `approverOk` flag 추가) + Routes (`/pipelines/designer`, `/pipelines/designer/:workflowId`) ✅ 2026-04-25
- [x] `PipelineRunsList` 에 워크플로 표 + "신규 디자이너" 버튼 + 워크플로별 "편집/보기" 진입 ✅ 2026-04-25
- [x] 통합 테스트 ✅ 2026-04-25
  - `tests/integration/test_sql_studio.py` — happy + 7개 차단 케이스 (DROP/pg_read_*/pg_catalog/DELETE/COPY/disallowed schema/whitespace) + 권한 (미인증 401, VIEWER 403, OPERATOR 200)

**다음 sub-phase 로 이연**
- 노드 색상 RETRYING (현재 NodeRunStatus 에 미정의 — Phase 3.2.6 retry 정책과 함께 도입)
- 하단 SSE 로그 패널 (Designer 페이지) — 현재는 `/pipelines/runs/:runId` 상세에서 노출
- JSON Schema 기반 polished form (현재는 textarea + hint) — Phase 3.2.5 SQL Studio sandbox 미리보기 합쳐서 도입 예정

### 3.2.5 SQL Studio [W6~W8]

- [x] `app/domain/sql_studio.py` ✅ 2026-04-25
  - sqlglot 파싱 (dialect=postgres) — Phase 3.2.4 의 `validate()` 그대로 재사용 + audit 기록 wrapper
  - 금지 연산: `DROP/TRUNCATE/ALTER/GRANT/REVOKE/COPY/VACUUM/...` (sqlglot 키워드 + statement-type + 함수 prefix 3중 차단)
  - 대상 스키마 제한: `mart` / `stg` / `wf` 만. VIEWER 는 API dependency 에서 차단(403)
  - sandbox: 별도 임시 스키마를 생성하지 않고 **read-only 트랜잭션 + LIMIT 자동 부착 + ROLLBACK** 으로 격리. `SET LOCAL transaction_read_only = ON` + `SET LOCAL statement_timeout = 30000ms`
  - LIMIT 정책: sqlglot AST 에 `LIMIT 1000` 자동 부착 (사용자가 더 작은 LIMIT 을 이미 걸었으면 보존). preview 결과 fetchmany(limit) 으로 메모리 보호
  - 실행 계획: `EXPLAIN (FORMAT JSON, COSTS OFF)` 결과 UI 노출
  - audit: `audit.sql_execution_log` 에 VALIDATE/PREVIEW/EXPLAIN 1행씩 (`_commit_audit` 가 별도 sub-tx 로 ROLLBACK 영향 차단)
  - **lineage 는 본 sub-phase 에서 제외** (Phase 3.2.5+) — 현재는 `referenced_tables` JSON 컬럼만 보존, OpenLineage RunEvent 발행 없음
- [x] DB ✅ 2026-04-25
  - `wf.sql_query` (이름/오너/`current_version_id` 자기참조 FK)
  - `wf.sql_query_version` (sql_text/version_no/parent_version_id/status: DRAFT/PENDING/APPROVED/REJECTED/SUPERSEDED + submitted_by/reviewed_by/review_comment)
  - `audit.sql_execution_log` 에 `sql_query_version_id` 컬럼 ADD + execution_kind CHECK 확장 (VALIDATE/EXPLAIN 추가)
  - migration `0018_wf_sql_query.py`
- [x] API ✅ 2026-04-25 (prefix 는 docs 의 `/v1/sql` 대신 기존 `/v1/sql-studio` 로 통일)
  - `POST /v1/sql-studio/validate` — sqlglot 정적 검증 (Phase 3.2.4 가 추가)
  - `POST /v1/sql-studio/preview` — read-only sandbox 실행 (LIMIT 1,000)
  - `POST /v1/sql-studio/explain` — EXPLAIN (FORMAT JSON)
  - `POST /v1/sql-studio/queries` — 새 SQL 자산 + DRAFT v1 (OPERATOR+)
  - `GET  /v1/sql-studio/queries` / `GET /v1/sql-studio/queries/{id}` — 목록/상세
  - `POST /v1/sql-studio/queries/{id}/versions` — 새 DRAFT 버전
  - `POST /v1/sql-studio/versions/{vid}/submit` — DRAFT → PENDING (소유자)
  - `POST /v1/sql-studio/versions/{vid}/approve` — PENDING → APPROVED (APPROVER, self-approval 차단)
  - `POST /v1/sql-studio/versions/{vid}/reject` — PENDING → REJECTED (APPROVER)
  - 승인된 SQL 을 `SQL_TRANSFORM` 노드 config 로 연결 — Phase 3.2.4 의 SqlEditor 가 통과 시 자동 반영, Phase 3.2.5 에서는 SqlStudio 페이지의 "DRAFT 저장" 으로 분기 가능
- [x] 모든 실행은 `audit.sql_execution_log` 기록 (VALIDATE/PREVIEW/EXPLAIN 별 row, BLOCKED/SUCCESS/FAILED 상태) ✅ 2026-04-25
- [x] 프론트 `pages/SqlStudio.tsx` — 좌측 query 트리 + 신규 생성, 중앙 SQL 편집기(textarea — Monaco 미도입, 의존성 무게 회피), 결과 탭(결과 테이블 / EXPLAIN JSON / 참조 테이블), 상단 툴바(Validate/Preview/EXPLAIN/제출/승인/반려) ✅ 2026-04-25
- [x] Sidebar "SQL Studio" 메뉴 (OPERATOR+) + 라우트 `/sql-studio` ✅ 2026-04-25
- [x] 통합 테스트 `tests/integration/test_sql_studio_sandbox.py` ✅ 2026-04-25
  - preview 결과/LIMIT 잘림, sqlglot 사전 차단, read-only 격리(INSERT 후 row 수 변경 없음), EXPLAIN JSON, VIEWER 403, lifecycle(create→submit→approve, current_version_id 갱신), self-approval 차단, reject 후 새 DRAFT version_no 증가, audit row 적재

**다음 sub-phase 로 이연**
- Monaco Editor 도입 (의존성 ≈3MB) — 사용자 트래픽이 본격화되면
- OpenLineage RunEvent 자동 발행 — Phase 3.2.6+ 에서 lineage UI 와 함께
- `sql_sandbox_{user_id}_{uuid}` 임시 스키마 생성 패턴 — 현재는 read-only 트랜잭션으로 충분, 실제 자료를 저장해야 하는 시나리오(승인 후 재실행 / large materialize) 도입 시

### 3.2.6 파이프라인 버전/배포 [W8]

- [x] DRAFT → PUBLISHED 승격 시 새 `version_no` 자동 할당 ✅ 2026-04-26
  - 기존 DRAFT 는 그대로 둠 (사용자가 다음 버전 편집 계속 가능). 새 PUBLISHED row 가 같은 name 안에서 max(version)+1 로 생성. (name, version) UNIQUE 가 안전장치.
  - 그래프 freeze: `node_definition`/`edge_definition` 을 PUBLISHED 워크플로로 복제해 향후 DRAFT 변경에 면역.
- [x] 실행은 PUBLISHED 버전만 (Phase 3.2.1 정책 유지) ✅ 2026-04-26 — Designer 가 PUBLISH 후 새 PUBLISHED 화면으로 자동 redirect 해 즉시 실행 가능.
- [x] 배포 이력 `wf.pipeline_release` ✅ 2026-04-26
  - migration `0019_pipeline_release.py`
  - `release_id / workflow_name / version_no / source_workflow_id (DRAFT) / released_workflow_id (PUBLISHED) / released_by / released_at / change_summary jsonb / nodes_snapshot jsonb / edges_snapshot jsonb`
  - PATCH `/v1/pipelines/{id}/status` (DRAFT→PUBLISHED) 가 release row + 새 PUBLISHED 워크플로 + diff 를 단일 sync session 트랜잭션으로 처리.
- [x] PUBLISHED 버전 간 diff 뷰 ✅ 2026-04-26
  - `app/domain/pipeline_release.compute_diff` — node_key 기준 added/removed/changed (config_json canonical JSON 비교) + edge pair 기준 added/removed
  - `GET /v1/pipelines/{id}/diff?against={other_id}` — 임의의 두 워크플로 비교
  - `GET /v1/pipelines/releases` (name 필터) + `GET /v1/pipelines/releases/{release_id}` (상세 + snapshot)
  - 프런트 `pages/PipelineReleases.tsx` — 이력 표 + 변경 요약 inline (`+N -M ~K`) + 상세에서 added/removed/changed 색상 블록 + nodes/edges 스냅샷 펼침
  - Sidebar "배포 이력" 메뉴 + `/pipelines/releases` 라우트
- [x] 통합 테스트 `tests/integration/test_pipeline_release.py` ✅ 2026-04-26
  - 첫 publish version=2 + 모든 노드 added, 두 번째 publish version=3 + 의미 있는 diff(노드 추가/config 변경/엣지 추가), 빈 워크플로 publish 409, diff API, 이력 list/detail snapshot

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
