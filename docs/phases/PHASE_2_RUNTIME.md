# Phase 2 — Pipeline Runtime (Worker + OCR + 표준화)

**기간 목표:** **6주 (2026-06-01 ~ 2026-07-11)**
**성공 기준 (DoD):** 수집된 raw가 자동으로 처리되어 staging → mart까지 실시간으로 흐른다. OCR 1,000페이지/일을 처리하고, 상품명이 AI로 표준코드에 매핑된다. Airflow 시스템 DAG 5종이 운영된다.

---

## 2.1 Phase 2 범위

**포함:**
- ✅ Dramatiq Worker (OCR / Transform / Crawler / Outbox publisher) — 실시간 경로
- ✅ Redis Streams 이벤트 버스
- ✅ Outbox Publisher (PENDING → Redis Streams)
- ✅ Idempotent Consumer 패턴
- ✅ Dead Letter Queue + 재시도 (exponential backoff)
- ✅ **Apache Airflow 2.9+ 도입** — 정기 배치/시스템 DAG 전담 (학습 포함)
- ✅ OCR 파이프라인 (CLOVA OCR + 폴백 Upstage)
- ✅ 상품 표준화 (규칙 + trigram + 임베딩)
- ✅ price_observation → price_fact 자동 반영
- ✅ price_daily_agg 일별 집계 배치
- ✅ DB-to-DB Incremental 커넥터 1개
- ✅ 크롤링 프레임워크 + 샘플 1개 (예: aT KAMIS)
- ✅ OCR 결과 확인 화면 (이미지 + 추출 텍스트 대조)
- ✅ 관제 고도화 (Loki 로그 집계, Sentry 에러, 큐 lag 대시보드)

**제외 (Phase 3):**
- ❌ Visual ETL Designer (Phase 3)
- ❌ SQL Studio 실행 파이프라인 (Phase 3)
- ❌ Crowd 정식 검수 UI (Phase 4, 기본 task 생성만 Phase 2)
- ❌ CDC (Phase 4)

---

## 2.2 작업 단위 체크리스트

### 2.2.1 Worker 기반 [W1~W2]

- [x] `backend/app/workers/__init__.py` — Dramatiq RedisBroker 설정 (`APP_REDIS_URL`, queue prefix `dp:`) ✅ 2026-04-25
- [x] 공통 `pipeline_actor` 데코레이터: max_retries=3, exponential backoff(1s→30s), time_limit=60s, DLQ 훅 ✅ 2026-04-25
- [x] `app/workers/outbox_publisher.py` — `publish_outbox_batch` actor (얇음 — domain 함수만 호출) ✅ 2026-04-25
- [x] `app/domain/outbox.py` — `publish_pending_events` (SELECT FOR UPDATE SKIP LOCKED → XADD → status=PUBLISHED, 실패 시 attempt_no++ / max 도달 FAILED) ✅ 2026-04-25
- [x] `app/core/events.py` — Redis Streams XADD wrapper (sync + asyncio.to_thread async) ✅ 2026-04-25
- [x] `app/db/sync_session.py` — Worker 전용 sync SQLAlchemy session (psycopg sync, 같은 ORM 모델 공유) ✅ 2026-04-25
- [x] 로컬 실행: `make worker-local` 또는 `uv run dramatiq app.workers --processes 1 --threads 4` ✅ 2026-04-25
- [x] `docker-compose` 에 `worker-outbox` 서비스 추가 (backend 이미지 재사용, `tini` PID 1) ✅ 2026-04-25 — `worker-ocr` / `worker-transform` / `worker-crawler` 는 2.2.3~2.2.5 에서 추가
- [x] `DeadLetterMiddleware` — retries == max_retries 시 `run.dead_letter` INSERT (origin / args / kwargs / message_id / stack_trace 8KB cap) ✅ 2026-04-25
- [x] 통합 테스트 ✅ 2026-04-25
  - `tests/integration/test_outbox_publisher.py` — 실 PG + 실 Redis 시드 3건 → drain → `XLEN=3`, `status=PUBLISHED`. 실패 stub → attempt 증가 + max 도달 시 `FAILED`
  - `tests/integration/test_dlq.py` — StubBroker 환경에서 `after_process_message` 직접 호출 → `run.dead_letter` INSERT 검증 + retries 잔여/성공 시 미적재 회귀

### 2.2.2 이벤트 버스 [W2]

- [x] Redis Streams 토픽 정의 — `docs/02_ARCHITECTURE.md` 2.9.1 표 + `app/core/event_topics.py` (`EventTopic.RAW_OBJECT`, `RawObjectCreatedPayload`, `StreamEnvelope`, `parse_message`) ✅ 2026-04-25
- [x] Consumer Group 이름 규칙 `<worker_type>-<env>` — `consumer_group_name(worker_type, env)` helper ✅ 2026-04-25
- [x] `RedisStreamConsumer` — `ensure_group`(BUSYGROUP suppress + MKSTREAM), `read`(XREADGROUP, `>` vs `0` for pending replay), `ack`(XACK), `pending_count`(XPENDING), `claim_stale`(XAUTOCLAIM) ✅ 2026-04-25
- [x] Idempotent consumer — `consume_idempotent(session, event_id, consumer_name, handler)`: `INSERT ... ON CONFLICT DO NOTHING` 으로 (event_id, consumer_name) 마킹 → 신규면 handler 실행 + commit, 기존이면 skip + rollback ✅ 2026-04-25
- [x] Migration 0010 — `run.processed_event` PK 를 `(event_id, consumer_name)` 합성으로 변경 (multi-consumer fan-out 지원) ✅ 2026-04-25
- [x] 통합 테스트 ✅ 2026-04-25
  - `tests/integration/test_event_bus.py::test_idempotent_consume_skips_on_redelivery` — XADD → XREADGROUP → 처리 + 재배달 시 handler skip
  - `::test_two_consumers_same_event_distinct_markers` — 같은 event_id 를 ocr/transform 두 consumer 가 각자 마킹 (합성 PK 회귀)
  - `::test_claim_stale_transfers_pending_to_alive_consumer` — A 가 read 후 ack 안 함 → B 가 XAUTOCLAIM 으로 인계
  - `::test_reset_processed_marker_allows_reprocessing` — 운영자 replay 도구

### 2.2.3 Apache Airflow 도입 [W2~W3] ★학습 과제

사용자가 처음 Airflow를 쓰는 경우, 먼저 `docs/airflow/LEARNING_GUIDE.md` 를 함께 읽으며 실습.

- [ ] `infra/airflow/` 디렉토리 생성
- [ ] `docker-compose.yml` 에 Airflow 서비스 추가:
  - `airflow-init` (최초 1회 DB 초기화, admin user 생성)
  - `airflow-webserver` (포트 8080)
  - `airflow-scheduler`
  - `airflow-worker` (Phase 2는 **LocalExecutor**로 시작)
- [ ] Airflow metadata DB는 기존 PostgreSQL의 별도 스키마 `airflow_meta` 또는 별도 DB `airflow` 사용
- [ ] `AIRFLOW__CORE__DAGS_FOLDER` → `/opt/airflow/dags` 볼륨 마운트 (`backend/airflow_dags/`)
- [ ] Airflow connection 등록 스크립트:
  - `datapipeline_pg` (운영 PG)
  - `datapipeline_redis`
  - `datapipeline_os` (NCP Object Storage, S3 호환)
  - `clova_ocr` (HTTP connection)
- [ ] Airflow Variables (환경별 설정):
  - `APP_ENV`, `slack_alert_webhook`, `budget_threshold_ocr_krw`
- [ ] 기본 시스템 DAG 작성 (`backend/airflow_dags/system/`):
  - `daily_price_aggregation.py` — 매일 00:30, `price_daily_agg` UPSERT
  - `monthly_partition_create.py` — 매월 1일 03:00, 다음 달 파티션 생성
  - `hourly_outbox_watchdog.py` — 매시간, PENDING > 1000 시 Slack 알림
  - `daily_raw_archive.py` — 매일 04:00, 30일 경과 raw 파일 archive 이동
- [ ] 수집 관련 DAG (`backend/airflow_dags/ingest/`):
  - `ingest_kamis.py` — aT KAMIS 일별 가격 Pull (매일 06:00)
  - `ingest_db_incremental.py` — DB-to-DB 증분 (매 10분)
  - `receipt_backfill.py` — Backfill 전용 (수동 trigger)
- [ ] **Sensor 활용**:
  - `RawDataArrivalSensor` (custom) — `run.event_outbox` 에 특정 이벤트 도착 감시
  - `DQHoldSensor` — `run.pipeline_run.status='ON_HOLD'` 관찰, 승인 시 다음 태스크 진행
- [ ] Airflow UI 권한: admin 1명 + OPERATOR role 읽기 계정
- [ ] DAG 단위 테스트: `pytest` + `airflow dags test` 명령어 활용
- [ ] 운영 문서: `docs/airflow/` 에 DAG 카탈로그 유지

### 2.2.4 OCR 파이프라인 [W3~W4]

- [ ] `app/integrations/clova_ocr.py` — NCP CLOVA OCR 클라이언트
  - 영수증 모드, 일반 문서 모드 분리
  - 재시도 + 타임아웃
- [ ] `app/integrations/upstage_ocr.py` — 폴백
- [ ] `app/domain/ocr.py` — 이미지 전처리(회전/크롭), 엔진 호출, 결과 정규화
- [ ] Dramatiq actor: `ocr.process(raw_object_id, partition_date)`
  - raw → 이미지 로드 → CLOVA 호출 → `raw.ocr_result` 저장
  - confidence < 0.85 → `wf.crowd_task(OCR_REVIEW)` 생성
- [ ] 영수증 파서:
  - 매장명/일시/품목별 라인 추출
  - 개인정보(카드번호/회원번호) 마스킹
  - `stg.price_observation` 로 변환
- [ ] 테스트: 고정 샘플 이미지 10종 회귀 테스트

### 2.2.5 표준화 파이프라인 [W4~W5]

- [ ] `scripts/seed_standard_codes.py` — 표준코드 + aliases 초기 적재
- [ ] 임베딩 사전 계산: `scripts/precompute_std_embeddings.py` → 별도 벡터 테이블 (`mart.standard_code_embedding`) 또는 pgvector 확장 도입
- [ ] `app/domain/standardization.py`:
  1. 이름 정규화 (공백/괄호/산지 태그 제거)
  2. 중량/단위/등급 파싱 (정규식 + 사전)
  3. alias 매칭
  4. trigram 유사도 상위 5개
  5. 임베딩 유사도 top-1
  6. 종합 점수 → std_code + confidence 결정
  7. product_master upsert
  8. product_mapping upsert
- [ ] Dramatiq actor: `standardization.process(price_obs_id)`
- [ ] confidence 게이트 반영:
  - ≥0.95: 즉시 price_fact insert
  - 0.80~0.95: price_fact insert + 5% 샘플링 crowd
  - 0.70~0.80: crowd_task(PRODUCT_MATCHING) 생성, price_fact 보류
  - <0.70: FAIL, staging 유지
- [ ] **pgvector 도입 여부 사용자 확인** (권장: pgvector 도입, NCP PG에서 지원 확인 필요)

### 2.2.6 가격 팩트 자동 반영 [W5]

- [ ] `app/domain/price_ingest.py`:
  - `stg.price_observation` → `mart.price_fact` 변환
  - `unit_price_per_kg` 계산
  - `seller_master` 없으면 자동 생성 or UNMAPPED 처리
- [ ] Outbox 이벤트 `staging.ready` → transform worker 처리
- [ ] 일별 집계 배치: `mart.price_daily_agg` 재계산 (UPSERT)
- [ ] 이상치 탐지: median ± 5σ 초과 시 `dq.quality_result` 기록 + 집계 제외

### 2.2.7 DB-to-DB 커넥터 [W5~W6]

- [ ] `app/integrations/connectors/base.py` — 표준 인터페이스 (snapshot/incremental)
- [ ] PG/MySQL/MSSQL 드라이버 고려 (Phase 2는 PG만 필수)
- [ ] `IncrementalConnector`: `updated_at` 워터마크 저장 후 delta 추출
- [ ] 스냅샷 테이블 자동 생성(`stg.<source>_<table>_staging`) → 커스텀 변환 로직 → `stg.price_observation`
- [ ] 테스트용 가짜 PG 소스

### 2.2.8 크롤링 프레임워크 [W6]

- [ ] `app/integrations/crawler/base.py` — Crawler 인터페이스
- [ ] Playwright 런타임 (docker-compose에 브라우저 이미지)
- [ ] robots.txt 준수 가드, rate limit 설정
- [ ] 한 개 샘플 크롤러 구현 (예: aT KAMIS 공공 데이터 조회)
- [ ] HTML 원본은 Object Storage 저장, raw.raw_web_page 메타만 DB
- [ ] 파서 버전 기록

### 2.2.9 관제 고도화 [W7]

- [ ] Loki 도입 (docker-compose + promtail)
- [ ] 로그 라벨: `env, service, request_id, source_code, pipeline_run_id`
- [ ] Grafana "Pipeline Runtime" 대시보드:
  - OCR 처리량/실패율/엔진별 latency
  - Outbox backlog, Redis Streams lag
  - DLQ 증가 알람
  - 표준화 confidence 분포
- [ ] Sentry 통합 (FastAPI + Dramatiq actor)
- [ ] SLO 정의: 수집→mart 반영 p95 < 60초

### 2.2.10 Frontend 추가 [W7~W8]

- [ ] "OCR 결과 검수" 페이지 — 원본 이미지 + 추출 라인 대조, 신뢰도 표시
- [ ] "크롤러 관리" 페이지 — 실행/중지, 최근 페이지 목록
- [ ] 대시보드 고도화 — 파이프라인 단계별 건수 sankey (간단 버전)
- [ ] "크라우드 작업함" 리스트(열람 only, 처리는 Phase 4)

---

## 2.3 샘플 시나리오 (E2E)

1. 새 소스 `RECEIPT_MOBILE` 등록 (type=RECEIPT).
2. 모바일(또는 curl)로 영수증 이미지 업로드 → raw_object 생성.
3. `ocr.requested` 이벤트 → OCR worker가 CLOVA OCR 호출.
4. 이미지에서 "참외 1.5kg 9,800원 / 이마트 용산점 / 2026-04-25 14:22" 추출.
5. standardization worker가 `FRT-CHAMOE` 표준코드에 confidence 0.92로 매핑.
6. `stg.price_observation` → `mart.price_fact` 자동 insert.
7. 대시보드에 "참외" 가격 그래프에 신규 관찰 1건 반영 (수집 후 60초 이내).
8. confidence 0.75였다면 `wf.crowd_task` 자동 생성.

---

## 2.4 Phase 2 비기능 기준

- [ ] Mart 반영 시간 p95 < 60초.
- [ ] OCR worker는 동시성 5, CLOVA rate limit 초과 안 함.
- [ ] Dramatiq actor는 모두 멱등성 보장 (재실행해도 중복 insert 없음).
- [ ] DLQ에 들어간 메시지는 UI에서 재실행 가능.

---

## 2.5 이월/대체 의사결정 로그 (Phase 2에서 확정)

Phase 2 진입 시점에 다음 중 하나로 확정하고 ADR 기록:

1. **임베딩 공급자**: HyperCLOVA X vs OpenAI vs 로컬 모델.
   - 기본 권장: **HyperCLOVA X** (NCP 통합, 한국어 특화, 비용 안정).
2. **벡터 검색**: **pgvector** vs 외부 벡터 DB.
   - NCP PG의 pgvector 지원 확인 후 가능하면 pgvector.
3. **OCR 기본 엔진**: CLOVA 우선 확정.
4. **Orchestrator**: **Apache Airflow 2.9+ 확정.** Executor는 Phase 2는 LocalExecutor, Phase 4에서 CeleryExecutor로 전환 검토.
