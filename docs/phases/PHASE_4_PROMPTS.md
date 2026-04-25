# Phase 4 — 13단계 진행 프롬프트 모음

각 sub-phase 의 trigger 프롬프트를 그대로 **복사 → 새 대화창에 붙여넣기** 하면 자동
모드로 진행됩니다. 패턴은 일관:

> 자동 모드. 계획 보여주지 말고 시작. 의사결정은 [지정된 가이드 / 보수적 기본값] 에 따라
> 임의 선택. 단일 commit + push 후 다음 페이즈 명령어 제안.

---

## 진행 순서 (의존성 기반)

```
4.0.4 Airflow 통합 (1주)        ← 가장 빠른 가치
   ↓
4.0.5 RBAC 확장 (0.5주)         ← Public API + Crowd 정식 의 선결
   ↓
┌──────┬────────┬──────┬─────────┐
4.2.1  4.2.2    4.2.4  4.2.7
Crowd  DQ게이트 RLS    Archive
정식   (3w)    (1w)   (1w)
(3w)
   │       │       │      │
   └───────┴───────┴──────┘
              ↓
        4.2.5 Public API (3w)
              ↓
        4.2.6 Gateway/보안 (1w)
              ↓
        4.2.3 CDC PoC (2w)
              ↓
        4.2.8 Multi-source 머지 (2w)
              ↓
        4.2.8b NKS 이관 (6~8w 병행)
              ↓
        4.2.9 장애복구 (1.5w)
              ↓
        4.2.10 관제/비용 (1w)
```

총 25주+ 추정. 매일 30분~1시간씩 복붙 + 검토면 3개월 안에 완료 가능.

---

## STEP 1 / 13 — 4.0.4 Airflow DAG 통합 (1주)

**선결조건**: 없음 (Phase 3 완료가 전제)

```
PHASE_4_ENTERPRISE.md 4.0.4 'Airflow DAG 통합' 전체를 구현해.

기능:
- airflow/dags/scheduled_pipelines.py — 매분 polling. wf.workflow_definition 의
  status='PUBLISHED' AND schedule_enabled=TRUE 인 row 조회 → 각 cron 의 직전 1분 안에
  trigger 시각이 들었으면 internal endpoint 호출. 응답 pipeline_run_id 를 XCom 저장.
- backend/app/api/v1/internal.py — POST /v1/pipelines/internal/runs (X-Internal-Token
  헤더 + settings.airflow_internal_token, 같은 (workflow_id, today date) RUNNING 이면
  기존 ID 반환 멱등)
- backend/app/config.py — airflow_internal_token 추가 + .env.example 갱신
- docker-compose.airflow.yml — Airflow standalone 1개 컨테이너 (Phase 3 docker-compose
  와 nest 가능한 별도 파일)
- airflow/operators/start_pipeline_op.py — PythonOperator wrapping (httpx + Variable
  에서 token 로드)
- docs/airflow/INTEGRATION.md 갱신 — DAG 동작 / 권한 흐름 / 디버깅
- tests/integration/test_airflow_trigger.py — internal token 401/200, (workflow_id,
  run_date) 멱등, PUBLISHED 만 통과, schedule_enabled=FALSE 거름

Acceptance criteria:
- cron */5 * * * * + enabled=TRUE 워크플로 PUBLISH 후 5분 이내 첫 자동 run
- Airflow standalone 재기동 후에도 다음 분 cron 정상 발화
- 같은 분 cron 두 번 발화해도 pipeline_run 1개

자동 모드. 계획 보여주지 말고 시작. 의사결정 (예: croniter polling 방식 vs Airflow
sensor) 은 보수적 기본값 (croniter polling — 단순) 선택. 단일 commit + push 후 다음
페이즈 명령어 제안.
```

---

## STEP 2 / 13 — 4.0.5 RBAC 확장 (0.5주)

**선결조건**: 4.0.4 완료 (internal endpoint 패턴 활용)

```
PHASE_4_ENTERPRISE.md 4.0.5 'RBAC 확장' 전체를 구현해.

기능:
- migration: ctl.role 에 3 row 추가:
  - PUBLIC_READER (외부 API 키용)
  - MART_WRITER (LOAD_MASTER 노드 전용)
  - SANDBOX_READER (SQL Studio sandbox 전용)
- backend/app/deps.py: require_roles 의 검증 로직은 그대로, 새 role 만 사용 가능하게
- backend/app/api/v1/users.py: role 부여/회수 API 가 새 3 role 도 지원
- frontend/src/pages/UsersPage.tsx: role 드롭다운에 3종 추가
- ADR-0010 작성 — 권한 분리 근거 + Phase 3 의 require_roles dependency 호환성 + Phase
  5 generic 화 시 role 확장 패턴
- tests/integration/test_users_rbac.py — 새 role 부여/회수 + JWT claim 정합성

Acceptance:
- admin 이 사용자에게 PUBLIC_READER role 부여 → JWT claim 에 들어감
- 일반 endpoint 에서 PUBLIC_READER 만 가진 사용자는 403
- 기존 4 role (ADMIN/APPROVER/OPERATOR/REVIEWER/VIEWER) 동작 동일

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 3 / 13 — 4.2.1 Crowd 검수 정식 운영 (3주)

**선결조건**: 4.0.5 완료 (REVIEWER role 활용)

```
PHASE_4_ENTERPRISE.md 4.2.1 'Crowd 검수 워크플로우 정식' 전체를 구현해.

기능 (3주 추정 — 큰 변경, 단일 commit 1개로 부담스러우면 sub-step 으로 쪼개도 됨):
- migration: crowd schema 신설 (run.crowd_task placeholder 와 별도)
  - crowd.task: run.crowd_task row 마이그 + task_kind (OCR_REVIEW/PRODUCT_MATCHING/...)
  - crowd.task_assignment: 다중 검수자 배정 + due_at
  - crowd.review: 검수자 1인의 결정 (이중 검수 row)
  - crowd.task_decision: 합의 결과 + 비즈니스 효과 (alias 추가, std_code 변경)
  - crowd.payout: 검수 보상 (외주 사용 시)
  - crowd.skill_tag: 검수자 전문 분야 (식품/POS/IoT)
- backend/app/domain/crowd_review.py: 이중 검수 정책 (priority>=8 = 2인 필수 / 충돌 시
  CONFLICT 상태 + 관리자 지명)
- backend/app/api/v1/crowd.py: 작업함 list/detail/decision + 통계 (REVIEWER+/관리자)
- frontend/src/pages/CrowdTaskQueue.tsx: 정식 UI — OCR_REVIEW 의 원본 이미지 + 추출 라인
  편집 / PRODUCT_MATCHING 의 후보 top-5 선택
- ctl.reviewer_stats: 건수/평균 처리 시간/충돌률/회귀 오류율
- 검수 완료 → run.event_outbox (crowd.task.decided) → mart 자동 반영
- 재처리 흐름: REJECTED 결과는 stg 로 되돌리고 재표준화
- ADR-0011: crowd.* schema 마이그 정책 (run.crowd_task 6개월 view 호환 → drop)
- tests/integration/test_crowd_review.py — lifecycle, 이중 검수, 충돌, 마이그

Acceptance:
- run.crowd_task 의 모든 row 가 crowd.task 로 마이그 + view 호환 (Phase 4.2.1 종료 시
  run.crowd_task 는 view)
- priority=9 OCR_REVIEW 작업 — 2인 검수 + 일치 시 자동 mart 반영
- 충돌 시 CONFLICT → 관리자가 결론 → 양 검수자에게 알림

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 4 / 13 — 4.2.2 DQ 게이트 + 승인 (1.5주)

**선결조건**: 4.2.1 완료 (Crowd 정식 — 승인자 패턴 재사용)

```
PHASE_4_ENTERPRISE.md 4.2.2 'DQ 게이트 + 승인' 전체를 구현해.

기능:
- migration: run.hold_decision 테이블 (signer FK, reason, decision APPROVE/REJECT,
  occurred_at)
- backend/app/domain/quality.py 확장:
  - severity=ERROR/BLOCK 실패 시 pipeline_run.status = ON_HOLD (RUNNING 도 PENDING 도
    아닌 신규 상태)
  - dq.quality_result.status='FAIL' + sample_json 저장 (실패 row 샘플)
- backend/app/api/v1/pipelines.py: ON_HOLD pipeline_run list + decision endpoint
  (POST /v1/pipelines/runs/{id}/hold/{approve|reject}, APPROVER 만)
- frontend/src/pages/PipelineRunsList.tsx: status 필터에 ON_HOLD 추가 + ON_HOLD 전용
  탭 + 승인 모달 (실패 규칙 + 샘플 row 미리보기)
- 자동 알림: ON_HOLD 발생 시 NOTIFY 노드 outbox + Slack 발송 (Phase 4 notify_worker
  구현 함께)
- backend/app/workers/notify_worker.py: outbox 의 NOTIFY 이벤트 → Slack/Email 실 발송
- migration: run.pipeline_run.status CHECK 에 ON_HOLD 추가
- tests/integration/test_dq_gate.py: ERROR 실패 → ON_HOLD / APPROVE → RESUMED /
  REJECT → CANCELLED + stg rollback

Acceptance:
- DQ_CHECK severity=ERROR 위반 시 pipeline_run = ON_HOLD + 다음 노드 진행 안 함
- APPROVER 가 승인 → RUNNING 으로 복귀 + 후속 노드 actor 재 enqueue
- REJECT → CANCELLED + 관련 stg row 자동 rollback (TRUNCATE 가 아닌 DELETE WHERE
  run_id)

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 5 / 13 — 4.2.4 RLS + 컬럼 마스킹 (1주)

**선결조건**: 4.0.5 완료 (PUBLIC_READER role)

```
PHASE_4_ENTERPRISE.md 4.2.4 'RLS + 컬럼 마스킹' 전체를 구현해.

기능:
- migration: PG RLS 정책 활성화
  - mart.retailer_master: ADMIN 외 사업자번호 컬럼 마스킹 (***-**-****)
  - mart.seller_master: 내부 주소는 APPROVER/OPERATOR 만 raw 접근, 외부는 시/구 단위
  - mart.product_price: retailer_allowlist (api_key 별 허용 retailer_id 셋) 기반 RLS
- 운영 DB 유저 분리 (alembic migration + .env.example):
  - app_rw — 일반 API
  - app_mart_write — Mart upsert 전용 (LOAD_MASTER 노드)
  - app_readonly — SQL sandbox
  - app_public — 외부 API 조회 전용 (RLS 적용)
- backend/app/db/session.py: role 별 SET ROLE 분기 (Phase 1.2.3 single role 에서 4 role
  로 확장)
- backend/app/api/v1/public.py 임시 stub: api_key 인증 → SET ROLE app_public → SELECT
- ADR-0012: RLS 정책 + 4 role 분리 근거
- tests/integration/test_rls.py: VIEWER/PUBLIC_READER/ADMIN 별 같은 SELECT 결과 다름

Acceptance:
- ADMIN: mart.retailer_master 의 사업자번호 평문 노출
- VIEWER/PUBLIC_READER: 마스킹 (***-**-****)
- 다른 retailer_id 의 row 는 PUBLIC_READER 의 api_key 가 retailer_allowlist 미포함 시
  보이지 않음

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 6 / 13 — 4.2.5 Public API (3주)

**선결조건**: 4.2.4 완료 (RLS), 4.0.5 완료 (PUBLIC_READER role)

```
PHASE_4_ENTERPRISE.md 4.2.5 'Public API (외부 서비스)' 전체를 구현해.

기능:
- ctl.api_key 확장: scope (prices.read/products.read/aggregates.read), rate_limit_per_min,
  retailer_allowlist (jsonb)
- 발급 흐름: 최초 1회만 full key 평문 노출 (SK-XXXX), 이후 prefix + hash 저장
- backend/app/api/v1/public.py: 본 sub-phase 에서 stub 을 정식으로
  - GET /public/v1/standard-codes — 표준코드 목록/검색 (q + category 필터)
  - GET /public/v1/products — 마스터 상품 검색 (std_code, 이름)
  - GET /public/v1/prices/latest?std_code=&retailer_id=&region= — 최신 가격
  - GET /public/v1/prices/daily?std_code=&from=&to=&retailer_id=&region= — 일별 집계
  - GET /public/v1/prices/series?product_id=&from=&to= — 시계열
- backend/app/core/rate_limit.py: slowapi + Redis, key 별 rate_limit_per_min
- 응답 캐시: Redis 60~300초 (std_code/daily 같은 조회)
- audit.public_api_usage: 일별 집계 (api_key_id, endpoint, count, byte_count)
- backend/app/api/v1/api_keys.py: ADMIN 의 발급/회수/통계 endpoint
- frontend/src/pages/ApiKeysPage.tsx: ADMIN 화면 + 사용량 차트
- OpenAPI 별도 docs: /public/docs (FastAPI 라우터 분리)
- tests/integration/test_public_api.py: 키 발급 / rate limit 429 / RLS / scope 차단

Acceptance:
- API key 발급 → 최초 1회만 평문 응답에 (이후 prefix + hash 만)
- 60 req/min 초과 시 429 + Retry-After
- prices.read scope 만 있는 키로 /public/v1/products 호출 → 403
- 같은 std_code 를 여러 번 조회 → 첫 호출 외에는 cache hit (응답 시간 < 50ms)

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 7 / 13 — 4.2.6 Gateway / 보안 (1주)

**선결조건**: 4.2.5 완료 (Public API endpoint)

```
PHASE_4_ENTERPRISE.md 4.2.6 'Gateway / 보안' 전체를 구현해.

기능:
- nginx config 갱신: /public/ 만 별도 domain (api.<도메인>) 또는 path 분리
  - HTTPS + HSTS (max-age=31536000; includeSubDomains; preload)
  - 보안 헤더 풀 (CSP, X-Frame, Referrer-Policy, Permissions-Policy)
- backend/app/core/middleware.py: 1개 키당 동시 연결 제한 (Redis lock + 60s TTL)
- backend/app/core/abuse_detection.py: 동일 IP 가 여러 api_key 사용 시 알람 outbox →
  Slack
- 운영자 화면: /v1/api-keys/abuse 의 의심 키 목록 + 강제 비활성 버튼
- ADR-0013: NCP API Gateway vs nginx 직접 — 본 phase 는 nginx (단순), Phase 5 에서
  트래픽 100K/day 초과 시 NCP API Gateway 로 이전
- tests/integration/test_abuse_detection.py: 같은 IP 에서 3 키 사용 → 알람 + 로그 기록

Acceptance:
- 외부 API 도메인은 https 만 응답 (HTTP → 301 to https)
- 1 키 당 동시 연결 5개 초과 시 429
- 의심 IP 패턴 발생 시 Slack 알림 + audit.access_log 에 마킹

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 8 / 13 — 4.2.3 CDC PoC (2주)

**선결조건**: 4.2.5 완료 (Public API 가 트래픽 측정 후 CDC 결정 분기)

```
PHASE_4_ENTERPRISE.md 4.2.3 'CDC PoC' 전체를 구현해.

ADR-0014 작성 — 경로 A (wal2json 경량) vs 경로 B (Kafka+Debezium) 결정. 본 phase 는
경로 A (소스 1~2개) 로 진행.

기능 (경로 A):
- migration: raw.db_cdc_event (event_id PK, source_id FK, lsn, before/after jsonb,
  op_kind, captured_at)
- backend/app/workers/cdc_consumer.py: wal2json + logical replication slot 직접 구독
- 첫 외부 PG 1개 — 그 DB 에 미리 logical replication slot 생성 (운영자 수동) →
  consumer 가 polling
- Airflow DAG: cdc_lag_monitor (replication slot lag > 10s 면 알람) +
  cdc_snapshot_merge (snapshot + CDC 결합 시 business_key 기준 머지)
- backend/app/domain/cdc_merge.py: snapshot row 가 들어오는 동안 들어온 CDC event 의
  before/after 를 비교해 conflict 해결 (last-write-wins by op_at)
- backend/app/api/v1/cdc.py: ADMIN 의 slot 생성/삭제, lag 조회
- tests/integration/test_cdc_lag.py: slot 생성 → INSERT 1만 row → lag < 5s 보장

Acceptance:
- 외부 PG 의 INSERT 가 raw.db_cdc_event 에 5초 안에 적재
- lag > 10s 면 Slack 알림
- 경로 B (Kafka+Debezium) 으로의 마이그 트리거 명문화 (소스 3+ 또는 트래픽 500K/일)

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 9 / 13 — 4.2.7 Partition Archive 자동화 (1주)

**선결조건**: 4.0.4 완료 (Airflow DAG 인프라)

```
PHASE_4_ENTERPRISE.md 4.2.7 'Partition Archive 자동화' 전체를 구현해.

기능:
- migration: ctl.partition_archive_log (archive_id PK, schema/table_name, partition_name,
  row_count, checksum, archived_at, restored_at, restored_by FK, status
  PENDING/ARCHIVED/RESTORED)
- airflow/dags/partition_archive_monthly.py: 매월 1일 04:00 KST 배치
  - raw.raw_object_*, run.pipeline_run_*, mart.price_fact_*, audit.access_log_* 중
    13개월 이상 경과 partition detect
  - Object Storage archive 등급 (NCP 의 cold storage 비슷한 tier) 으로 복제 +
    checksum 기록
  - 검증 통과 → DETACH PARTITION → DROP (또는 보존)
  - ctl.partition_archive_log 에 1행 INSERT
- backend/app/cli/restore_partition.py: archive_id 받아 Object Storage → 임시 테이블
  로 복원 + ctl.partition_archive_log.restored_at 갱신
- frontend/src/pages/AdminPartitionsPage.tsx: ADMIN 화면 — 아카이브된 partition 목록
  + 복원 버튼 + log
- tests/integration/test_partition_archive.py: 가짜 13개월+ partition 만들고 → archive
  → drop → restore 라운드트립

Acceptance:
- 운영 DB 에서 13개월+ raw 파티션이 매월 1일 cold storage 로 자동 이전 + DB DROP
- 운영자가 복원 버튼 → 임시 테이블 (raw.raw_object_2024_05_restored) 로 복원

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 10 / 13 — 4.2.8 Multi-source 머지 (2주)

**선결조건**: 4.2.1 완료 (Crowd 정식)

```
PHASE_4_ENTERPRISE.md 4.2.8 'Multi-source 머지' 전체를 구현해.

기능:
- backend/app/domain/master_merge.py: 동일 상품이 여러 유통사에서 관찰될 때 mart.
  product_master 에 하나로 수렴
  - canonical_name = 가장 빈도 높은 표현 (각 retailer 의 product_name 빈도 + 임베딩
    cosine 유사도 가중)
  - weight_g/grade/package_type = 다수결
  - 분쟁 시 crowd_task(PRODUCT_MATCHING) 자동 생성
- migration: mart.master_entity_history 에 merge 이력 컬럼 추가 (merge_op_id PK,
  source_product_ids jsonb, target_product_id, merged_at, merged_by)
- airflow/dags/master_merge_daily.py: 매일 03:00 KST 배치 — 같은 std_code + 동일/유사
  weight_g 인 product 들을 머지 시도
- frontend/src/pages/MasterMergePage.tsx: PRODUCT_MATCHING crowd 작업의 후보 top-5 +
  각 후보의 retailer 분포 + 통계
- ADR-0015: 머지 정책 + 수동 분리 (un-merge) 절차
- tests/integration/test_master_merge.py: 동일 std_code 의 3 product → 자동 머지 + 1개
  남음 + history 1행

Acceptance:
- 같은 std_code (FRT-APPLE-CHS) 를 가진 product 3개 → 자동 머지 → 1개만 남음
- product_mapping 의 retailer_product_code 는 모두 보존
- 잘못된 머지 발견 시 ADMIN 의 unmerge 버튼 → master_entity_history 에 unmerge 이력

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 11 / 13 — 4.2.8b NKS 이관 (6~8주, 본 phase 의 백본)

**선결조건**: 4.2.5 완료 (Public API 가 동작 — staging 검증 가능)

```
PHASE_4_ENTERPRISE.md 4.2.8b 'NKS 이관' 전체를 구현해. (운영팀 합류 후 가장 큰 인프라
변경 — 6~8주 작업, 단일 commit 1개로 못 끝나면 sub-step 으로 쪼개도 OK)

기능 (Phase 4.2.8b 의 task list 그대로):
- infra/terraform/ncp/ — VPC/Subnet/ACG, NKS 클러스터 (s2-g3 3대 시작), Cloud DB PG
  (prod + staging), Cloud DB Redis, Object Storage, Container Registry
- staging 네임스페이스 datapipeline-staging 먼저 구축
- infra/k8s/helm/datapipeline/ — backend-api, worker-{transform,ocr,crawler}, frontend,
  scheduler, airflow-{webserver,scheduler,worker(Celery)}
- Kustomize overlays: base/, overlays/staging/, overlays/prod/
- Argo CD 설치 + Application 등록 (Git repo infra/k8s/ sync)
- ExternalSecrets Operator + NCP Secret Manager 연동
- ingress-nginx + cert-manager (Let's Encrypt)
- HPA: backend-api CPU 70%, worker-ocr 커스텀 메트릭 dramatiq_queue_lag{queue='ocr'}
- NetworkPolicy: backend-api → DB/Redis/Object Storage 만, worker-* → Redis/DB 만,
  frontend → backend-api 만
- PodDisruptionBudget: backend-api minAvailable 2, 기타 1
- Observability namespace: kube-prometheus-stack + Loki + Promtail + 기존 Grafana
  대시보드 JSON 이관
- Velero 백업 (클러스터 리소스 + PV → Object Storage)
- DB Migration Job: Alembic 을 pre-install/pre-upgrade Helm hook 으로
- 병행 운영 2주 — 기존 Ubuntu staging + NKS 동시, 트래픽 점진 이전
- 폐기 절차 — Ubuntu staging docker compose 종료, 모니터링 1주 확인
- docs/runbooks/ — 배포/롤백/장애 대응/백업복구/스케일링

Acceptance:
- staging NKS 에서 모든 Phase 1~4 기능 동작 (실 도메인 + SSL)
- prod NKS 에 트래픽 100% 이전 + 1주 안정 가동 후 Ubuntu staging 폐기
- 운영팀 6~7명이 Argo CD + Grafana + kubectl 로 독립 배포/관제

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 12 / 13 — 4.2.9 장애 복구 / HA (1.5주)

**선결조건**: 4.2.8b 완료 (NKS 이관 — 인프라 위에서 HA 검증)

```
PHASE_4_ENTERPRISE.md 4.2.9 '장애 복구 / HA' 전체를 구현해.

기능:
- NCP Cloud DB PG: 일 단위 자동 백업 + WAL 기반 PITR (Point-in-Time Recovery) 정책 등록
- Object Storage: cross-region replication 검토 → ADR-0016 (현재는 단일 region, 비용
  대비 가치 평가)
- 애플리케이션 — backend-api Deployment replicas=3 + Load Balancer (NCP)
- Worker — ocr 전용 1대 + transform/crawler 1대 분리 (HPA)
- RTO/RPO 시뮬레이션 리허설:
  - "실수로 mart.price_fact 의 한 파티션 DROP" 시나리오 → PITR 로 30분 안에 복원 검증
  - "ocr worker pod 모두 죽음" 시나리오 → HPA 가 5분 안에 복구 검증
  - 결과를 docs/runbooks/disaster_recovery.md 에 기록
- backend/app/domain/health_extra.py: liveness/readiness 외에 startup probe 추가 (긴
  마이그 시간 대비)
- tests/integration/test_db_failover.py: PITR 시뮬레이션 (테스트 DB 한정)

Acceptance:
- RPO 1시간 / RTO 4시간 — 실 시나리오 1회 검증 + runbook 작성
- backend-api 3 replica 중 1대 죽어도 503 응답 비율 < 0.1%

자동 모드. 단일 commit + push 후 다음 페이즈 명령어 제안.
```

---

## STEP 13 / 13 — 4.2.10 관제 / 비용 대시보드 + Phase 4 wrap-up (1주)

**선결조건**: 4.2.8b + 4.2.9 완료

```
PHASE_4_ENTERPRISE.md 4.2.10 + Phase 4 wrap-up 전체를 구현해.

기능:
- Grafana "Enterprise" 대시보드 (infra/grafana/dashboards/enterprise.json):
  - 외부 API qps + 에러율 + top 키 by 사용량
  - CLOVA OCR 사용량/비용 (월 예산 기준 bar)
  - pgvector 인덱스 크기/쿼리 성능
  - DLQ + ON_HOLD 누적 추세
- backend/app/cli/billing_report.py: 월간 비용 리포트 — NCP 빌링 API 연동 (검토
  단계 — 자격 증명 부족 시 stub) + Excel/CSV export
- frontend/src/pages/BillingDashboard.tsx: ADMIN 화면 — 월 비용 + 항목별 분석
- ADR-0017: Phase 4 종료 회고 + Phase 5 (v2 generic platform) 진입 게이트
- docs/phases/CURRENT.md 갱신: Phase 4 완료 + Phase 5 진입 준비
- docs/phases/PHASE_5_GENERIC_PLATFORM.md 와 연결 (v2 마이그)
- 비기능 baseline 재측정 (PHASE_3 3.4 표) — NKS 환경에서 1회

Acceptance:
- Grafana 대시보드 1장에서 외부 API 활동 한눈에
- 월 비용 리포트 1회 생성 + Excel 다운로드
- Phase 4 DoD 5종 모두 충족:
  1. ✅ Crowd 검수 워크플로우 정식 운영
  2. ✅ DQ 실패 → mart 자동 차단 + 승인 시 해제
  3. ✅ 외부 소비자 API Key 로 가격 조회 가능
  4. ✅ 다중 소스 상품 매칭 자동 머지
  5. ✅ NKS 이관 완료 — 운영팀 독립 운영

자동 모드. 단일 commit + push 후 Phase 5 (v2 generic platform) 진입 명령어 제안.
```

---

## 부록 A — 진행 시 팁

### 한 sub-phase 가 너무 커서 단일 commit 으로 못 끝낼 때

각 step 에서 "단일 commit 못 끝나면 sub-step 으로 쪼개도 OK" 라고 명시한 항목 (4.2.1
Crowd, 4.2.5 Public API, 4.2.8b NKS) 은 다음 패턴:

```
[step 의 원래 프롬프트] + 다음 한 줄 추가:

본 sub-phase 가 단일 commit 으로 부담스러우면 sub-step 으로 쪼개. 첫 commit 은 schema
+ migration + ORM 만, 두 번째는 domain + API, 세 번째는 frontend, 네 번째는 tests +
ADR. 각 sub-step 마다 commit + push.
```

### 진행 중 막혔을 때

```
[현재 sub-phase 명] 진행 중인데 [구체적 에러 / 의문점] 막혔어. 우선 해결 후 다시
원래 trigger 프롬프트 그대로 진행해.
```

### 중간 검증

```
지금까지 진행한 [phase 4.X] 의 기능을 demo 시나리오로 5개 만들어줘. 각 시나리오마다
어느 메뉴 → 어떤 액션 → 기대 결과 형식으로.
```

---

## 부록 B — 작업 시간 추정 (현실적)

| Step | sub-phase | 추정 (정상 페이스) | 빠르면 | 느리면 |
|---|---|---|---|---|
| 1 | 4.0.4 Airflow | 1주 | 3일 | 2주 |
| 2 | 4.0.5 RBAC | 0.5주 | 1일 | 1주 |
| 3 | 4.2.1 Crowd | 3주 | 2주 | 5주 |
| 4 | 4.2.2 DQ 게이트 | 1.5주 | 1주 | 2주 |
| 5 | 4.2.4 RLS | 1주 | 3일 | 2주 |
| 6 | 4.2.5 Public API | 3주 | 2주 | 5주 |
| 7 | 4.2.6 Gateway | 1주 | 3일 | 2주 |
| 8 | 4.2.3 CDC | 2주 | 1주 | 4주 |
| 9 | 4.2.7 Archive | 1주 | 3일 | 2주 |
| 10 | 4.2.8 Merge | 2주 | 1주 | 4주 |
| 11 | 4.2.8b NKS | 6주 | 4주 | 10주 |
| 12 | 4.2.9 HA | 1.5주 | 1주 | 3주 |
| 13 | 4.2.10 wrap | 1주 | 3일 | 2주 |
| **합계** | | **~25주** | **~16주** | **~44주** |

운영팀 6~7명이 Owner 영역별로 병렬 진행하면 <strong>3~4개월</strong> 안에 완료 가능
(CURRENT.md 의 owner 매트릭스 참조).
