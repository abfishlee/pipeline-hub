# Phase 4 — Enterprise & External Service

**기간 목표:** 10~12주
**성공 기준 (DoD):**
1. 영수증 OCR 검수 등 Crowd 워크플로우가 정식 운영 가능.
2. 데이터 품질 실패가 Mart 반영을 자동 차단한다 (승인 시 해제).
3. 외부 소비자가 API Key로 가격 조회 API를 호출할 수 있다.
4. 다중 소스 상품 매칭이 자동으로 머지되어 마스터가 정합한다.
5. **NKS 이관 완료** — 운영팀 6~7명이 Argo CD/Grafana/kubectl 로 독립 배포/관제 가능.

---

## 4.0 Phase 4 진입 게이트 (2026-04-26 기록)

본 섹션은 Phase 4 wrap-up (2026-04-26) 시점에 정리한 진입 조건 + 첫 sub-phase task +
운영팀 onboarding 계획. Phase 1~3 가 모두 같은 날(2026-04-26) 완료된 상태에서 4개월+
의 마진을 활용한 사전 준비.

### 4.0.1 필수 선결 항목 (Phase 3 의존성)

Phase 4 진입 전 모두 확인해야 하는 Phase 3 산출물:

- [x] `wf.workflow_definition.schedule_cron` + `schedule_enabled` 필드 (Phase 3.2.7)
  → Phase 4.0.4 Airflow DAG 이 polling 대상으로 활용.
- [x] `wf.pipeline_release` 이력 (Phase 3.2.6) → Phase 4.0.5 RBAC 의 release-level
  권한 분리에 사용.
- [x] `audit.sql_execution_log` (Phase 3.2.5) → Phase 4 Public API 의 사용량 로깅
  패턴과 동일한 구조로 확장.
- [x] ADR 0007/0008/0009 (Phase 3 wrap-up) → Phase 4 NKS manifest / RBAC 의 의사결정
  근거 인용.
- [ ] 비기능 baseline 측정 (PHASE_3 3.4 표) — `PERF=1` 환경에서 1회 측정 → Phase 4
  회귀 비교 기준.

### 4.0.2 인프라 / 운영 게이트

- [ ] NCP 환경 프로비저닝 — 운영팀 합류 후 첫 주에 진행. `infra/terraform/ncp/` 의
  skeleton 작성 (실 apply 는 운영팀과).
- [ ] Container Registry 에 backend / frontend / worker 이미지 push 자동화 (CI 확장).
- [ ] NCP Cloud DB for PostgreSQL replica 검토 — ADR-0008 의 sandbox 마이그 트리거가
  발생하면 활성화.
- [ ] Secret Manager 연동 — Phase 1.2.2 의 env 기반 설정이 NKS 에서 ExternalSecrets
  로 자연 확장.

### 4.0.3 운영팀 6~7명 onboarding (첫 주 실습)

#### 필수 읽을 docs (Day 0 — 합류 전 1주 안에)

| 우선순위 | 문서 | 분량 | 목적 |
|---|---|---|---|
| P0 | `CLAUDE.md` | 5분 | 프로젝트 한 문장 정의 + Phase 순서 |
| P0 | `docs/00_PROJECT_CONTEXT.md` | 15분 | 도메인 / 규모 / SLA |
| P0 | `docs/04_DOMAIN_MODEL.md` | 20분 | 채널 7종 + 표준화 흐름 |
| P0 | `docs/phases/CURRENT.md` | 5분 | 현재 Phase + 진행 상태 |
| P1 | `docs/02_ARCHITECTURE.md` | 30분 | 모듈 경계 |
| P1 | ADR 0001~0009 | 60분 | 주요 의사결정 + 트레이드오프 |
| P2 | `docs/06_DATA_FLOW.md` | 30분 | 10단계 데이터 흐름 |
| P2 | `docs/07_CORE_TECHNOLOGIES.md` | 30분 | K8s / Airflow / Kafka 개념 |

#### 첫 주 실습 일정

| 일차 | 실습 | 산출물 | 멘토 |
|---|---|---|---|
| Day 1 | 로컬 docker-compose 기동 + admin 로그인 + Designer 첫 워크플로 | 7명 모두 워크플로 1개 | abfishlee |
| Day 2 | SQL Studio 템플릿 실행 + DRAFT→PENDING→APPROVED lifecycle | 각자 SQL 자산 1개 APPROVED | abfishlee |
| Day 3 | Backfill 7일치 + 특정 노드부터 재실행 | runs 검색 화면 익숙 | abfishlee |
| Day 4 | 운영자 화면 (Crowd 큐 / Dead Letter / Runtime 모니터) | Phase 2.2.10 화면 익힘 | abfishlee |
| Day 5 | NKS 환경 첫 진단 + 본인 owner 후보 영역 선정 | Phase 4 task 분배 초안 | 합류 운영자 6~7명 |

#### Owner 후보 영역 (Phase 4 6 sub-phase + NKS 이관 분배)

| 영역 | 연관 4.x sub-phase | 추천 인원 | 핵심 산출물 |
|---|---|---|---|
| Airflow DAG 통합 | 4.0.4 (이 ADR 항목) | 1명 | scheduled_pipelines.py + internal trigger 토큰 |
| NKS 이관 | 4.2.8b | 2명 | Terraform / Helm / Argo CD / NetworkPolicy |
| Crowd 정식 | 4.2.1 | 1~2명 | crowd.* schema + 이중 검수 + SLA + 보상 |
| DQ 게이트 + 승인 | 4.2.2 | 1명 | ON_HOLD pipeline_run + 승인 UI |
| Public API + RBAC | 4.2.4 + 4.2.5 + 4.0.5 | 1명 | API Key + Rate Limit + RLS + 컬럼 마스킹 |
| CDC PoC | 4.2.3 | 1명 | wal2json (경로 A) 또는 Debezium (경로 B) |

### 4.0.4 첫 sub-phase: Airflow DAG 통합 (Phase 4 진입 직후 1주 내 완료 권장)

Phase 3.2.7 의 `schedule_cron` 필드가 시드되어 있지만 실제 cron 트리거가 미연결. 운영
팀 합류 후 **가장 빠르게 가치를 만드는** task. 본 sub-phase 완료 = Phase 4 본격 진입.

#### Task list

- [ ] `airflow/dags/scheduled_pipelines.py` — 매분(`*/1 * * * *`) 실행, 다음을 수행:
  1. `wf.workflow_definition` 에서 `status='PUBLISHED' AND schedule_enabled=TRUE` 인
     row 조회.
  2. 각 row 의 `schedule_cron` 으로 croniter 의 직전/다음 실행 시각 계산.
  3. 직전 1분 안에 trigger 시각이 들었으면 `POST /v1/pipelines/internal/runs` 호출
     (X-Internal-Token 헤더, body `{workflow_id}`).
  4. 응답 pipeline_run_id 를 XCom 에 저장.
- [ ] `backend/app/api/v1/internal.py` — Airflow 전용 trigger 엔드포인트 alias.
  - `X-Internal-Token` 헤더 검증 (settings.airflow_internal_token, 시드 시점에
    `.env.example` + Secret Manager 등록 안내).
  - 본문 흐름은 기존 trigger_run 과 동일 — 권한 dependency 만 internal token 으로 교체.
  - 같은 (workflow_id, today date) 가 이미 RUNNING 이면 새 run 안 만들고 기존 ID 반환
    (멱등 — 1분 내 cron 이 두 번 발화해도 안전).
- [x] `airflow/dags/scheduled_pipelines.py` — 매분 polling. PG (`postgres_datapipeline`
  Connection) 에서 schedule_enabled=TRUE PUBLISHED 워크플로 조회 → 각 cron 의 직전 1분
  안에 trigger 시각이 들었으면 internal endpoint 호출. 결과 XCom 저장. ✅ 2026-04-26
- [x] `airflow/plugins/operators/start_pipeline_op.py` — httpx + Variable 에서 token 로드,
  401/503/422 분기 처리. ✅ 2026-04-26
- [x] `backend/app/api/v1/internal.py` — POST /v1/pipelines/internal/runs (X-Internal-Token
  헤더 검증, settings.airflow_internal_token, 같은 (workflow_id, today) RUNNING/SUCCESS
  이면 기존 ID 반환 멱등, PUBLISHED 만 통과). main.py 의 router 등록 순서를 internal →
  pipelines 로 둬 JWT dep 충돌 회피. ✅ 2026-04-26
- [x] `backend/app/config.py` — airflow_internal_token SecretStr 추가 + .env.example
  갱신. ✅ 2026-04-26
- [x] `infra/docker-compose.airflow.override.yml` — 기존 Phase 2.2.3 Airflow stack 위에
  Variable (`BACKEND_INTERNAL_URL` / `BACKEND_INTERNAL_TOKEN`) + Connection (`postgres_
  datapipeline`) 만 추가하는 overlay 형태. ✅ 2026-04-26
- [x] `docs/airflow/INTEGRATION.md` 갱신 — scheduled_pipelines DAG 동작 + 권한 흐름 +
  디버깅 6 케이스 + 멱등성 검증. ✅ 2026-04-26
- [x] `tests/integration/test_airflow_trigger.py` — 7 케이스 (token 누락 401 / 오답 401
  / token 미설정 503 / DRAFT 거부 422 / unknown workflow 404 / PUBLISHED 신규 created=True
  / 같은 today 멱등 created=False) ✅ 2026-04-26
- [x] PHASE_4 의 다른 sub-phase 진입 전 본 task 동작 — Phase 1~3 자체 실행이 운영 환경
  에서 일관성 있게 흐르는 1차 검증. ✅ 2026-04-26

#### Acceptance criteria — 모두 ✅

- [x] 운영자가 Designer 에서 cron `*/5 * * * *` + enabled=TRUE 로 워크플로 PUBLISH 후
  5분 안에 첫 자동 run 트리거 (croniter polling 1분 lookback).
- [x] Airflow scheduler 재기동 후에도 다음 분 cron 부터 정상 발화 (DAG 가 stateless).
- [x] X-Internal-Token 누락 / 오답 시 401, 정상 시 200 + pipeline_run_id 반환.
- [x] 같은 분에 cron 이 두 번 발화해도 pipeline_run 은 1개 (DB 의 (workflow_id, run_date,
  status IN PENDING/RUNNING/SUCCESS) 검사로 멱등).

### 4.0.5 RBAC 확장 (Phase 4.2.4 와 결합) ✅ 2026-04-26

Phase 3 의 5-role (`ADMIN`/`APPROVER`/`OPERATOR`/`REVIEWER`/`VIEWER`) 위에 Phase 4 의
3 role 추가:

- [x] **`PUBLIC_READER`** — Public API 전용 외부 키. Phase 4.2.4 RLS + 4.2.5 Public API
  결합 후 `mart.product_price` / `mart.price_daily_agg` / `mart.standard_code` 만 SELECT.
- [x] **`MART_WRITER`** — LOAD_MASTER 노드 + 승인된 SQL 자산의 mart write 분리. 워크플로
  작성자가 mart write 권한 없이도 워크플로 등록 가능 (최소 권한 원칙).
- [x] **`SANDBOX_READER`** — SQL Studio sandbox 의 read-only role. Phase 4.x 의 NCP
  replica 도입 (ADR-0008 마이그 트리거) 후 본 role 이 replica 라우팅 받음.

#### 산출물 (2026-04-26 완료)
- [x] `migrations/versions/0021_phase4_roles.py` — `ctl.role` 에 3 row 추가, downgrade
  도 함께 (FK 정리 후 row 삭제).
- [x] `backend/app/api/v1/users.py` — `GET /v1/users/roles` 신설 (8 role 카탈로그) +
  하드코딩 회피.
- [x] `backend/app/schemas/users.py` — `RoleOut` Pydantic DTO 추가.
- [x] `backend/app/deps.py` — `require_roles` 변경 없음 (이미 generic, role string 만
  검증).
- [x] `frontend/src/api/users.ts` — `useRoles` hook + 5분 staleTime.
- [x] `frontend/src/pages/UsersPage.tsx` — RolePicker 컴포넌트 (description tooltip +
  Phase 4 role 의 v4 라벨).
- [x] ADR-0010 작성 — 8-role 채택 근거 + Phase 3 호환성 + Phase 5 도메인 분기 회수 조건
  + 대안 (Casbin / OAuth2 scope / PG SET ROLE) 비교.
- [x] `tests/integration/test_users_rbac.py` — 8 케이스 (카탈로그 / JWT claim 전파 /
  PUBLIC_READER 만 가진 사용자 ADMIN endpoint 403 / unknown role 404 / 기존 5 role 회귀
  / Phase 4 의 3 role 각각 단독 grantable parametrize).

#### Acceptance — 모두 ✅
- [x] admin 이 사용자에게 PUBLIC_READER role 부여 → JWT claim `roles` 에 포함.
- [x] PUBLIC_READER 만 가진 사용자가 `/v1/users` (ADMIN 가드) 호출 → 403.
- [x] 기존 5 role (ADMIN/APPROVER/OPERATOR/REVIEWER/VIEWER) 동작 동일 — 회귀 0.

---

## 4.1 Phase 4 범위

**포함:**
- ✅ Crowd 검수 워크플로우 정식 운영
  - OCR_REVIEW / PRODUCT_MATCHING / RECEIPT_VALIDATION / ANOMALY_CHECK
  - 이중 검수 + 충돌 해결
  - 작업자별 품질 점수
- ✅ 데이터 품질 "게이트" (severity=ERROR면 pipeline_run ON_HOLD)
- ✅ 승인자 해제 플로우
- ✅ CDC 통합 (소스 DB 하나에 대해 PoC)
- ✅ RLS (Row Level Security) + 컬럼 마스킹 (내부 민감 필드 대비)
- ✅ 외부 서비스용 Public API
  - API Key 발급/관리
  - Rate Limit + Quota
  - `/public/v1/prices/*`, `/public/v1/products/*`, `/public/v1/standard-codes/*`
- ✅ API Gateway 역할 (FastAPI 경로 분리 + NCP API Gateway 검토)
- ✅ partition archive 자동화
  - raw 13개월+ → Object Storage archive 등급 이동
  - 운영 DB에서 DETACH
- ✅ Multi-source 상품 매칭 머지 (동일 상품이 여러 유통사에서 관찰될 때 canonical 통합)
- ✅ 대시보드: 외부 API 사용량, 비용, SLA
- ✅ 장애 복구 (RPO 1시간 / RTO 4시간) 테스트
- ✅ **NKS(Naver Kubernetes Service) 이관**: Terraform + Helm + Argo CD + 운영팀 온보딩

**제외 (추후):**
- ❌ 개인화 추천
- ❌ 모바일 SDK
- ❌ 다국어

---

## 4.2 작업 단위 체크리스트

### 4.2.1 Crowd 검수 워크플로우 [W1~W3] ✅ 2026-04-26

- [x] migration 0022_crowd_schema.py — crowd schema 6 table + run.crowd_task → view 호환
  - crowd.task / task_assignment / review / task_decision / payout / skill_tag
  - run.crowd_task placeholder row 자동 마이그 (task / assignment / review / decision 4 종)
- [x] backend/app/models/crowd.py — 7 ORM (Task / TaskAssignment / Review / TaskDecision /
  Payout / SkillTag + ctl.ReviewerStats)
- [x] backend/app/domain/crowd_review.py — 이중 검수 상태머신 (priority>=8 또는
  requires_double_review=TRUE → 2명 review 필수). 단일=SINGLE, 이중일치=DOUBLE_AGREED,
  불일치=CONFLICT → ADMIN/APPROVER resolve = CONFLICT_RESOLVED. outbox `crowd.task.decided`
  발행 (Phase 4.2.2 mart 반영 worker 가 consume).
- [x] backend/app/api/v1/crowd.py — legacy_router (Phase 2.2.10 호환, PATCH 위임) +
  router (Phase 4.2.1 정식: list/detail/assign/review/resolve/stats/reviewers).
- [x] frontend/src/pages/CrowdTaskQueue.tsx — V4 탭 신설:
  - 5 status 탭 (PENDING/REVIEWING/CONFLICT/APPROVED/REJECTED)
  - V4DetailPanel: priority/이중 검수 표시, assignments, reviews 리스트, decision 패널,
    APPROVE/REJECT/SKIP 버튼, CONFLICT resolve UI (관리자 한정), 검수자 30일 통계 표
- [x] ADR-0011 — crowd schema 마이그 정책 + 이중 검수 + outbox + 회수 조건 4종.
- [x] tests/integration/test_crowd_review.py — 6 케이스 (단일 lifecycle / 이중 일치 /
  CONFLICT resolve / legacy PATCH 위임 / 같은 reviewer 두번 차단 / priority>=8 단일 거부).
  모두 통과.

#### Acceptance — 모두 ✅
- [x] run.crowd_task 의 모든 row 가 crowd.task 로 마이그 + view 호환 (legacy GET / PATCH
  모두 정상 동작).
- [x] priority=9 task — 2명 검수 + 일치 시 자동 task_decision (DOUBLE_AGREED) + outbox 발행.
- [x] 충돌 시 CONFLICT 상태 + 관리자 resolve → CONFLICT_RESOLVED + outbox 발행.

### 4.2.2 DQ 게이트 [W3~W4] ✅ 완료 (2026-04-26)

- [x] `app/domain/nodes/dq_check.py` 확장:
  - row_count_min / null_pct_max / unique_columns / custom_sql 4 종 어서션
  - 실패 시 최대 10 행 sample 캡처 (`dq.quality_result.sample_json`)
  - `dq.quality_result.status` = PASS/WARN/FAIL
  - severity=ERROR/BLOCK 실패 시 NodeOutput.payload['dq_hold']=True
- [x] `app/domain/pipeline_runtime.py::complete_node` ON_HOLD 분기:
  - dq_hold=True 면 후속 노드 SKIPPED cascade 차단 (PENDING 보존)
  - `pipeline_run.status = ON_HOLD` + outbox `pipeline_run.on_hold` 발행
- [x] `app/domain/dq_gate.py`:
  - `approve_hold(pipeline_run_id, signer_user_id, reason)` — RUNNING 복귀
    + 실패 DQ 직접 후속 READY + outbox `pipeline_run.hold_approved`
  - `reject_hold(pipeline_run_id, signer_user_id, reason)` — CANCELLED
    + 잔여 노드 CANCELLED + `stg.standard_record/price_observation`
    `WHERE load_batch_id = pipeline_run_id` DELETE rollback
    + outbox `pipeline_run.hold_rejected`
- [x] 승인 UI (`PipelineRunsList.tsx`):
  - ON_HOLD 목록 카드 + 실패 노드 키
  - HoldDecisionModal: 실패 규칙 + sample 행 확인 + 승인/반려 + 사유
  - APPROVER/ADMIN 만 승인/반려 버튼 노출
- [x] `migrations/versions/0023_dq_gate_hold.py`:
  - `pipeline_run.status` CHECK 에 ON_HOLD 추가
  - `dq.quality_result` 에 status + sample_json 컬럼 + index
  - `run.hold_decision` 신설 (signer FK, reason, decision, quality_result_ids, occurred_at)
- [x] API: `GET /v1/pipelines/runs/on_hold` + `POST /runs/{id}/hold/{approve,reject}`
  (APPROVER/ADMIN 권한)
- [x] `app/workers/notify_worker.py` — outbox NOTIFY 이벤트 1배치 처리:
  - `pipeline_run.on_hold` / `hold_approved` / `hold_rejected` / `notify.requested`
  - Slack webhook (URL stdlib urllib) + email stub
  - 실패 시 attempt_no++; max_attempts 초과 시 dead_letter
- [x] `tests/integration/test_dq_gate.py` 6 케이스: ERROR → ON_HOLD / list /
  APPROVE → RUNNING + READY / REJECT → CANCELLED + stg rollback / notify worker
  PUBLISHED 마킹 / not-on-hold 거부.

### 4.2.3 CDC PoC [W4~W5] ✅ 경로 A 완료 (2026-04-26)

**채택 경로:** 경로 A — wal2json + logical replication slot 직접 구독.
경로 B (Kafka + Debezium) 는 ADR-0013 § 6 회수 조건 만족 시 재평가.

- [x] migration `0025_cdc_poc.py`:
  - `raw.db_cdc_event` (`(source_id, lsn) UNIQUE` — idempotency 1차 방어)
  - `ctl.cdc_subscription` (slot_name UNIQUE, plugin='wal2json', enabled, last_lsn,
    last_lag_bytes, last_polled_at, snapshot_lsn)
  - `ctl.data_source.cdc_enabled BOOLEAN`
- [x] `app/integrations/cdc/wal2json_consumer.py`:
  - `parse_wal2json_change` — format-version=2 의 I/U/D + identity/columns 파싱
    (BEGIN/COMMIT/M 메타는 None 반환)
  - `persist_cdc_changes` — ON CONFLICT DO NOTHING + outbox `cdc.event` 발행 +
    `last_committed_lsn` 갱신
  - `get_replication_lag_bytes` / `update_lag_metric` — 임계 초과 시 NOTIFY outbox
  - `stream_slot` — psycopg replication 모드 (라이브 환경)
- [x] `app/workers/cdc_consumer_worker.py` — `dispatch_cdc_batch(source_id)` actor
  (queue=cdc_consumer, time_limit 60s).
- [x] `scripts/setup_cdc_slot.sql` — superuser 1회 실행, slot+publication 생성
  (idempotent — 존재 시 NOTICE).
- [x] `infra/airflow/dags/cdc_lag_monitor.py` — 5분 간격 enabled subscription 의 lag
  측정 + 임계 (10MB) 초과 시 outbox NOTIFY → notify_worker → Slack.
- [x] `app/domain/cdc_merge.py` — snapshot+CDC 머지 (PG `pg_lsn` 캐스팅 비교 +
  business_key INSERT ... ON CONFLICT DO UPDATE / DELETE).
- [x] frontend `SourcesPage.tsx` — `CdcCell` 컴포넌트 (slot ON/OFF 뱃지 + lag
  human-readable, 10MB 초과 시 빨강).
- [x] `docs/adr/0013-cdc-poc-wal2json.md` — 경로 A 채택 + 회수 조건.
- [x] `tests/integration/test_cdc_consumer.py` 5 케이스: parser I/U/D + boundary
  skip / batch filter / persist + idempotency + outbox / lag NOTIFY 분기 / merge
  LSN 비교 / upsert_from_change roundtrip.

**Acceptance 충족 확인**:
- ctl.data_source.cdc_enabled=true 토글 후 setup_cdc_slot.sql 실행 → slot 생성 ✅
- wal2json change 메시지 → 30초 내 raw.db_cdc_event 적재 (worker 폴링 주기 의존) ✅
- 같은 LSN 재처리 시 중복 INSERT 없음 (UNIQUE(source_id, lsn) + ON CONFLICT) ✅
- snapshot_lsn 이후 이벤트만 적용되어 mart 마스터 일관성 유지 ✅
- pg_replication_slots lag 10MB 초과 시 NOTIFY outbox 1건 발행 ✅

### 4.2.4 RLS + 컬럼 마스킹 [W5] ✅ 완료 (2026-04-26)

- [x] **Masking VIEW** (security_invoker=true, PG 15+):
  - `mart.retailer_master_view` — `current_role IN (app_public, app_readonly)` 시
    `business_no` 마스킹 (`regexp_replace(.., \\d, *)`) + `head_office_addr` NULL
  - `mart.seller_master_view` — 동일 조건에서 `address` NULL (sido/sigungu 는 노출)
- [x] **RLS 정책** (FORCE ROW LEVEL SECURITY):
  - `mart.seller_master`, `mart.product_mapping` — retailer_id 컬럼 보유 테이블만
  - `rls_*_full` (app_rw, app_mart_write) — USING true (모든 row 통과)
  - `rls_*_allowlist` (app_public, app_readonly) — `retailer_id = ANY(NULLIF(
    current_setting('app.retailer_allowlist', true), '')::bigint[])`
  - **빈 allowlist = 0 row** (deny by default — "미포함 시 보이지 않음")
- [x] **4 PG role 분리** (NOLOGIN, connection user `app` 의 멤버 — SET LOCAL ROLE):
  - `app_rw` — 모든 schema CRUD (기존 동작 유지)
  - `app_mart_write` — mart.* CRUD + 시퀀스 (LOAD_MASTER + APPROVED SQL)
  - `app_readonly` — mart/wf/stg SELECT (SQL Studio sandbox)
  - `app_public` — masking view + RLS 제한 SELECT
- [x] **`ctl.api_key.retailer_allowlist BIGINT[]`** 컬럼 추가 — Public API 가
  SET LOCAL `app.retailer_allowlist` 로 GUC 주입 → RLS 정책이 읽음.
- [x] `backend/app/db/session.py` — `set_session_role(session, role)` /
  `set_retailer_allowlist(session, ids)` / `reset_session_role` helper.
- [x] `backend/app/api/v1/public.py` (Phase 4.2.5 정식 구현 전 stub):
  - `GET /public/v1/retailers` / `/sellers` — `X-API-Key` 헤더 → SET LOCAL ROLE
    app_public + allowlist GUC → masking view SELECT
- [x] `migrations/versions/0024_rls_column_masking.py` (PG role + RLS + view 일괄)
- [x] `docs/adr/0012-rls-column-masking-phase4.md` — 4 role 분리 + masking VIEW vs
  컬럼 GRANT 의 트레이드오프 + 회수 조건
- [x] `tests/integration/test_rls.py` 6 케이스: ADMIN 평문 / app_public 마스킹 /
  빈 allowlist 0 row / 부분 매칭 / RESET ROLE 복귀 / `/public/v1/sellers` E2E

**Acceptance 충족 확인**:
- ADMIN/connection user — `mart.retailer_master_view` 의 business_no 평문 노출 ✅
- `app_public` SET LOCAL ROLE — business_no `***-**-*****` (숫자 마스킹), address NULL ✅
- api_key.retailer_allowlist 미포함 retailer 의 seller row 조회 시 0 row ✅

### 4.2.5 Public API (외부 서비스) [W5~W8]

- [ ] API Key 관리 (이미 3.2에 테이블 생성됨)
  - 발급: 최초 1회만 full key 평문 노출, 이후 prefix + hash 저장
  - 스코프: `prices.read`, `products.read`, `aggregates.read`
- [ ] Rate Limit: slowapi + Redis, key별 `rate_limit_per_min`
- [ ] Public 엔드포인트:
  - `GET /public/v1/standard-codes` — 표준코드 목록/검색
  - `GET /public/v1/products` — 마스터 상품 검색 (std_code, 이름)
  - `GET /public/v1/prices/latest?std_code=&retailer_id=&region=` — 최신 가격
  - `GET /public/v1/prices/daily?std_code=&from=&to=&retailer_id=&region=` — 일별 집계
  - `GET /public/v1/prices/series?product_id=&from=&to=` — 시계열
- [ ] OpenAPI 별도 문서 (`/public/docs`)
- [ ] 응답 캐시 (Redis, 60~300초) — std_code/daily 같은 조회에 적용
- [ ] 사용량 로깅: `audit.public_api_usage` (일별 집계)

### 4.2.6 Gateway / 보안 [W7]

- [ ] 옵션 1: NCP API Gateway에 docs + 인증 위임
- [ ] 옵션 2: nginx 단에서 /public/ 만 별도 도메인 (`api.datapipeline.co.kr`)
- [ ] HTTPS + HSTS
- [ ] 1개 키당 동시 연결 제한
- [ ] 악용 탐지: 동일 IP 여러 키 사용 시 알람

### 4.2.7 Partition Archive 자동화 [W8]

- [ ] 매월 1일 04:00 배치:
  - `raw.raw_object_YYYY_MM` 중 13개월 이상 경과 파티션 detect
  - 내용 Object Storage archive 등급으로 복제 (`archive/{YYYY}/{MM}/`)
  - 검증 (row count, checksum) → DETACH → DROP 또는 보존
  - 작업 이력 `ctl.partition_archive_log`
- [ ] 복원 스크립트: archive key → 임시 테이블로 복원

### 4.2.8 Multi-source 머지 [W8~W9]

- [ ] 동일 상품이 여러 유통사에서 관찰될 때 `mart.product_master` 에 하나로 수렴.
- [ ] 머지 규칙:
  - canonical_name 은 가장 빈도 높은 표현
  - weight_g/grade/package_type 다수결
  - 분쟁 시 crowd_task(PRODUCT_MATCHING) 자동 생성
- [ ] 머지 이력: `mart.master_entity_history`

### 4.2.8b NKS 이관 (운영팀 6~7명 합류 대비) [W1~W8, Phase 4 전반에 걸쳐 병행]

상세 가이드: `docs/ops/NKS_DEPLOYMENT.md`

- [ ] **Terraform 베이스라인** (`infra/terraform/ncp/`)
  - VPC/Subnet/ACG
  - NKS 클러스터 (Worker node pool: `s2-g3` 3대 시작)
  - Cloud DB PG (prod + staging), Cloud DB Redis
  - Object Storage 버킷
  - Container Registry
- [ ] **staging 네임스페이스 먼저 구축**: NKS `datapipeline-staging`
- [ ] **Helm Chart 작성** (`infra/k8s/helm/datapipeline/`):
  - `backend-api`, `worker-transform`, `worker-ocr`, `worker-crawler`, `frontend`, `scheduler`
  - `airflow-webserver`, `airflow-scheduler`, `airflow-worker`(Celery)
  - Kustomize overlays: `base/`, `overlays/staging/`, `overlays/prod/`
- [ ] **Argo CD 설치 + Application 등록**: Git repo `infra/k8s/` 와 sync
- [ ] **External Secrets Operator** 설치 + NCP Secret Manager 연동
- [ ] **ingress-nginx + cert-manager** (Let's Encrypt)
- [ ] **HPA 정책** 등록:
  - backend-api: CPU 70%
  - worker-ocr: 커스텀 메트릭 `dramatiq_queue_lag{queue="ocr"}`
  - worker-transform: 동일
- [ ] **NetworkPolicy**:
  - `backend-api` → DB, Redis, Object Storage 엔드포인트만
  - `worker-*` → Redis, DB만
  - `frontend` → `backend-api` 만
- [ ] **PodDisruptionBudget**:
  - `backend-api` minAvailable: 2
  - 기타 Deployment도 최소 1 유지
- [ ] **Observability 네임스페이스**:
  - kube-prometheus-stack
  - Loki + Promtail
  - 기존 Grafana 대시보드 JSON 이관
- [ ] **Velero 백업** (클러스터 리소스 + PV, Object Storage 대상)
- [ ] **DB Migration Job 패턴**: Alembic은 pre-install/pre-upgrade Helm hook으로
- [ ] **병행 운영 2주** — 기존 VM 환경과 NKS 동시 가동, 트래픽 점진 이전
- [ ] **폐기 절차** — VM docker compose 환경 종료, 모니터링 확인 1주
- [ ] **운영 런북 작성** (`docs/runbooks/`):
  - 배포 / 롤백 / 장애 대응 / 백업-복구 / 스케일링
- [ ] **운영팀 온보딩 자료** 3종:
  - Kubernetes 기본 개념 (1시간)
  - 이 프로젝트 NKS 구조 투어 (2시간)
  - 장애 대응 시뮬레이션 (실습 1회)

### 4.2.9 장애 복구/HA [W9~W10]

- [ ] NCP Cloud DB PG 백업 정책: 일 단위 자동 + WAL 기반 PITR
- [ ] Object Storage cross-region replication 검토
- [ ] 애플리케이션 VM 2대 + Load Balancer (읽기 scale-out)
- [ ] Worker VM 2대로 분리 (ocr 전용 / transform+crawler)
- [ ] RTO/RPO 테스트 리허설 (실제 재해 가정 시나리오 실행)

### 4.2.10 관제/비용 대시보드 [W10~W12]

- [ ] Grafana "Enterprise" 대시보드:
  - 외부 API qps, 에러율, top 키
  - CLOVA OCR 사용량/비용 (월 예산 기준 bar)
  - pgvector 인덱스 크기/쿼리 성능
  - DLQ/ON_HOLD 누적 추세
- [ ] 월간 비용 리포트 스크립트 (NCP 빌링 API 연동 검토)

---

## 4.3 샘플 시나리오

**시나리오 A — 영수증 대량 유입 및 검수**
1. 소비자 100명이 동시에 영수증 업로드 → 100개 raw_object.
2. OCR worker 5개가 병렬 처리 → 80건 자동 반영, 20건 crowd_task.
3. 내부 검수자 3명이 작업함에서 병렬 처리.
4. 2인 검수 결과 일치한 18건 자동 승인 → mart 반영.
5. 2건 충돌 → 관리자 검토 후 결론.
6. 전체 시간: 5분 이내.

**시나리오 B — DQ 게이트로 잘못된 배치 차단**
1. 크롤러 파서 버그로 가격 단위가 100배 부풀려진 데이터 수집.
2. DQ rule "가격 범위 체크" (severity=ERROR) 실패.
3. pipeline_run 자동 ON_HOLD.
4. 승인자 UI에서 샘플 확인 후 REJECT → 관련 stg row rollback.
5. 파서 수정 후 재실행.

**시나리오 C — 외부 API 사용**
1. 외부 소비자 "FoodTech Inc"에 API Key 발급 (scope=prices.read, 60 req/min).
2. curl `GET /public/v1/prices/daily?std_code=FRT-CHAMOE&from=2026-04-01&to=2026-04-25` → 200 OK.
3. rate limit 초과 시 429.
4. 운영자가 월별 사용량/비용 대시보드 확인.

---

## 4.4 보안 점검 (Phase 4 종료 전 필수)

- [ ] 외부 API endpoint에는 내부 소스 정보(raw_object_id, source_code 등) 노출 금지
- [ ] Public API 응답은 RLS 통과 후 결과만
- [ ] API Key 리크 감지 (로그 패턴) 자동 알람
- [ ] 침입 탐지 (비정상 쿼리 패턴, 초당 수집량 급증 등)
- [ ] 개인정보 비식별 검증 (영수증 원본은 암호화 저장, 외부 API 응답에 절대 포함 안 됨)

---

## 4.5 오픈 이슈 (Phase 5 이상에서 검토)

- 한국 공공데이터 표준 변화 시 표준코드 정기 sync
- pgvector 성능 한계 시 외부 벡터 DB (Qdrant/Milvus) 도입
- Kafka 도입 시점 (실측 500K/일 초과 시)
- NKS(Kubernetes) 전환 시점 (VM 5대 이상 운영 필요 시)
- 다국어 상품명 지원 (수입 농산물 확대 시)
