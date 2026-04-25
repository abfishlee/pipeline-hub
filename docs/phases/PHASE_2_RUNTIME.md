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

**기반 인프라 (이번 commit)** — 운영팀 9월 합류 시 그대로 켜고 쓸 수 있는 chassis.
- [x] `infra/airflow/` 디렉토리 (`dags/`, `plugins/`, `requirements/`, `logs/.gitignore`) ✅ 2026-04-25
- [x] `docker-compose.yml` 에 Airflow 2.10.4 LocalExecutor 4종 추가 ✅ 2026-04-25
  - `airflow-init` (1회 db migrate + admin 생성 + connections add, restart=no)
  - `airflow-webserver` (포트 8080, `/health` healthcheck)
  - `airflow-scheduler` (`airflow jobs check` healthcheck)
  - `airflow-worker` 는 **LocalExecutor** 라 생략 — CeleryExecutor 전환은 Phase 4 NKS
- [x] Airflow metadata DB = `postgres/airflow` (메인 DB 와 같은 클러스터, 다른 데이터베이스). `infra/postgres/init/01_create_airflow_db.sql` 가 첫 기동 시 자동 생성 ✅ 2026-04-25
- [x] `AIRFLOW__CORE__DAGS_FOLDER` → `/opt/airflow/dags` (호스트 `./infra/airflow/dags` 마운트) ✅ 2026-04-25
- [x] Connection 등록 (compose env + airflow connections add) ✅ 2026-04-25
  - `postgres_default` — 메인 애플리케이션 DB (`datapipeline`)
  - `redis_default` — Redis Streams / Dramatiq 같은 인스턴스
  - `datapipeline_os` (NCP/MinIO Object Storage, S3 호환) — Phase 2.2.6 archive DAG 도입 시 추가
  - `clova_ocr` (HTTP) — Phase 2.2.4 OCR DAG 도입 시 추가
- [x] Hello smoke test DAG: `system_hello_pipeline` (BashOperator + PythonOperator, @daily) — Airflow 기동/스케줄/오퍼레이터 동작 확인용 ✅ 2026-04-25
- [x] `Makefile` `airflow-up/down/logs/dag-list/cli` 타겟 ✅ 2026-04-25
- [x] `docs/airflow/INTEGRATION.md` 6.5 — 로컬 기동 절차 + connection 표 + DAG 작성 규칙(`system_*`) ✅ 2026-04-25

**시스템 DAG (Phase 2.2.4~2.2.6 에서 분할 작성)** — 위 chassis 위에 얹는다.
- [ ] `daily_price_aggregation.py` — 매일 00:30, `price_daily_agg` UPSERT (Phase 2.2.5 transform 도입 후)
- [ ] `monthly_partition_create.py` — 매월 1일 03:00, 다음 달 파티션 생성
- [ ] `hourly_outbox_watchdog.py` — 매시간, PENDING > 1000 시 Slack 알림
- [ ] `daily_raw_archive.py` — 매일 04:00, 30일 경과 raw 파일 archive 이동 (Phase 2.2.6)
- [ ] 수집 관련 DAG (`backend/airflow_dags/ingest/`):
  - `ingest_kamis.py` — aT KAMIS 일별 가격 Pull (매일 06:00)
  - `ingest_db_incremental.py` — DB-to-DB 증분 (매 10분)
  - `receipt_backfill.py` — Backfill 전용 (수동 trigger)
- [ ] **Sensor 활용**:
  - `RawDataArrivalSensor` (custom) — `run.event_outbox` 에 특정 이벤트 도착 감시
  - `DQHoldSensor` — `run.pipeline_run.status='ON_HOLD'` 관찰, 승인 시 다음 태스크 진행
- [ ] Airflow Variables: `APP_ENV`, `slack_alert_webhook`, `budget_threshold_ocr_krw`
- [ ] Airflow UI 권한: admin 1명 + OPERATOR role 읽기 계정
- [ ] DAG 단위 테스트: `pytest` + `airflow dags test` 명령어 활용
- [ ] 운영 문서: `docs/airflow/` 에 DAG 카탈로그 유지

### 2.2.4 OCR 파이프라인 [W3~W4]

**기반 (이번 commit) — 이미지 → ocr_result + crowd_task placeholder + outbox**
- [x] `app/integrations/ocr/types.py` — `OcrProvider` Protocol + `OcrPage`/`OcrResponse` ✅ 2026-04-25
- [x] `app/integrations/ocr/circuit_breaker.py` — in-memory 회로차단(5fail / 30s cooldown / half-open) ✅ 2026-04-25
- [x] `app/integrations/clova/client.py` — NCP CLOVA OCR Document V2 (httpx.AsyncClient, X-OCR-SECRET 헤더, base64 image, retry 3회 + 4xx 즉시 실패) ✅ 2026-04-25
- [x] `app/integrations/upstage/client.py` — Upstage Document OCR 폴백 (multipart/form-data, retry 2회) ✅ 2026-04-25
- [x] `app/domain/ocr.py::process_receipt` — Object Storage 다운로드 → provider 폴백 시도 → `raw.ocr_result` per-page INSERT → confidence ≥ threshold 면 `ocr.completed` outbox, 미달이면 `run.crowd_task` placeholder + `crowd.task.created` outbox. `raw_object.status=PROCESSED` ✅ 2026-04-25
- [x] `app/workers/ocr_worker.py::process_ocr_event` actor (queue=ocr, max_retries=3, time_limit=120s) — `consume_idempotent(consumer_name="ocr-worker")` 로 멱등 ✅ 2026-04-25
- [x] Migration `0011_crowd_task` — `run.crowd_task` (PENDING/REVIEWING/APPROVED/REJECTED, BRIN created_at, partial idx PENDING) + `CrowdTask` ORM ✅ 2026-04-25
- [x] `event_topics`: `EventTopic.OCR_RESULT` / `CROWD_TASK` + `OcrCompletedPayload` / `CrowdTaskCreatedPayload` ✅ 2026-04-25
- [x] 메트릭 — `ocr_requests_total{provider,status}`, `ocr_duration_seconds{provider}`, `ocr_confidence{provider}`, `crowd_task_created_total{reason}` ✅ 2026-04-25
- [x] Settings — `clova_ocr_url/secret`, `upstage_ocr_url/upstage_api_key`, `ocr_confidence_threshold` (.env / .env.example) ✅ 2026-04-25
- [x] `docker-compose` `worker-ocr` 서비스 추가 (queue=ocr, threads=8) — `x-worker-common` 앵커 공유 ✅ 2026-04-25
- [x] `ObjectStorage.get_bytes(key)` — 영수증 다운로드 어댑터 ✅ 2026-04-25
- [x] 단위 테스트 `tests/test_clova_signed_request.py` — httpx.MockTransport 기반 ✅ 2026-04-25
  - 헤더 X-OCR-SECRET / Content-Type, 본문 JSON shape, base64 image, lang=ko 검증
  - 4xx → 영구 실패 (재시도 X), 5xx → 재시도 후 성공, breaker 5회 후 OPEN 시 즉시 OcrError
- [x] 통합 테스트 `tests/integration/test_ocr_pipeline.py` ✅ 2026-04-25
  - 0.95 confidence → `ocr.completed` 단일 outbox + crowd_task 미발급
  - 0.50 confidence → ocr_result + crowd_task PENDING + 두 종 outbox
  - CLOVA 실패 stub → Upstage 폴백 성공 (provider="upstage")

**다음 sub-phase 로 분리 (2.2.4.x 또는 2.2.5)**
- [ ] 영수증 전처리 (회전/크롭/디스큐) — Phase 2.2.4.1
- [ ] 영수증 파서 (매장명/일시/품목 라인 추출, 카드번호 마스킹) → `stg.price_observation` 변환 — Phase 2.2.4.2 (Upstage Information Extraction or HyperCLOVA)
- [ ] 정식 검수 워크플로 (`run.crowd_task` REVIEWING → APPROVED 전이) — Phase 4 정식 Crowd
- [ ] 고정 샘플 영수증 10종 회귀 — 샘플 확보 후 (`tests/fixtures/receipts/`)

### 2.2.5 표준화 파이프라인 [W4~W5]

**기반 (이번 commit) — raw_object → standard_record + price_observation + std_code 매핑 + outbox(staging.ready)**
- [x] Migration `0012_std_code_embedding` — `CREATE EXTENSION vector` + `mart.standard_code.embedding vector(1536)` + IVFFLAT cosine 인덱스 ✅ 2026-04-25
- [x] `pgvector>=0.3` deps + `app/models/mart.py::StandardCode.embedding` (Vector(1536) nullable) ✅ 2026-04-25
- [x] `app/integrations/hyperclova/client.py` — `EmbeddingClient` Protocol + `HyperClovaEmbeddingClient` (httpx async, Bearer + X-NCP-CLOVASTUDIO-REQUEST-ID, retry 3회 + 4xx 즉시 실패 + CircuitBreaker) ✅ 2026-04-25
- [x] `app/domain/standardization.py::resolve_std_code` — 3단계 매칭 (pg_trgm `similarity()` + aliases → cosine `<=>` top-1 → crowd) ✅ 2026-04-25
- [x] `app/domain/transform.py::process_record` — payload_json items → `stg.standard_record` + `stg.price_observation` 적재 + std_code 매핑 + `crowd_task("std_low_confidence")` placeholder + outbox(`staging.ready`) ✅ 2026-04-25
- [x] `app/workers/transform_worker.py::process_transform_event` actor (queue=transform, max_retries=3, time_limit=120s, idempotent) ✅ 2026-04-25
- [x] `event_topics`: `EventTopic.PRICE_OBSERVATION/STAGING` + `StagingReadyPayload` ✅ 2026-04-25
- [x] 메트릭 — `standardization_requests_total{outcome}`, `standardization_confidence{strategy}`, `hyperclova_embedding_duration_seconds` ✅ 2026-04-25
- [x] Settings — `hyperclova_api_url/embedding_app`, `std_trigram_threshold`(0.7), `std_embedding_threshold`(0.85), `embedding_dim`(1536). `.env`/`.env.example` 동기화 ✅ 2026-04-25
- [x] `docker-compose worker-transform` 서비스 추가 (queue=transform, threads=8) ✅ 2026-04-25
- [x] 통합 테스트 ✅ 2026-04-25
  - `tests/integration/test_standardization.py` (5건): trigram_hit (embedding 미호출 회귀), embedding_hit, crowd, embedding_client=None → crowd, pg_trgm extension 정합
  - `tests/integration/test_transform_pipeline.py` (2건): trigram_hit 다중 라인 매핑 + outbox staging.ready, 매칭 미달 → crowd_task 적재 + 두 종 outbox

**다음 sub-phase 로 분리 (Phase 2.2.5.x / 2.2.6)**
- [ ] `scripts/seed_standard_codes.py` — 농림축산식품부/aT 기반 표준코드 + aliases 초기 적재
- [ ] `scripts/precompute_std_embeddings.py` — 시드 후 표준코드 모든 row 의 `embedding` 채우기 (HyperCLOVA 임베딩 일괄 호출 + REINDEX ivfflat)
- [ ] 이름 정규화 (공백/괄호/산지 태그 제거), 중량/단위/등급 정규식 파싱
- [ ] confidence 게이트 세분화 (≥0.95 즉시, 0.80~0.95 5% 샘플링 crowd, 0.70~0.80 보류, <0.70 FAIL) — 현재는 단일 임계
- [ ] `mart.product_master` / `mart.product_mapping` upsert (현재는 std_code 만 채움)
- [ ] price_fact 자동 반영 — Phase 2.2.6 분리

### 2.2.6 가격 팩트 자동 반영 [W5]

**기반 (이번 commit) — staging.ready → mart.price_fact + confidence 게이트 + crowd_task placeholder**
- [x] Migration `0013_price_fact_monthly_partitions` — `mart.price_fact_2026_05 ~ 2026_12` 8개 월 RANGE 파티션 (BRIN/product/seller 인덱스 부모로부터 자동 상속) ✅ 2026-04-25
- [x] `app/domain/price_fact.py::propagate_price_fact` — `stg.price_observation`(raw_object_id) → `mart.{retailer,seller,product}_master` manual upsert (NULLS DISTINCT 회피, IS NOT DISTINCT FROM 매칭) → `mart.price_fact` INSERT ✅ 2026-04-25
- [x] Confidence 게이트 ✅ 2026-04-25
  - ≥ 95 → 즉시 INSERT (outcome=`insert`)
  - 80~95 → INSERT + `_is_sampled(obs_id, sample_rate)` 결정적 5% 샘플링 → `crowd_task("price_fact_sample_review")` (outcome=`sampled`)
  - < 80 → 미적재 + `crowd_task("price_fact_low_confidence")` (outcome=`held`)
  - std_code NULL → skip (transform 단계에서 이미 crowd_task 발급됨, outcome=`skipped`)
- [x] `app/workers/price_fact_worker.py::process_price_fact_event` actor (queue=price_fact, max_retries=3, time_limit=120s, idempotent consumer="price-fact-worker") ✅ 2026-04-25
- [x] `event_topics`: `EventTopic.PRICE_FACT` + `PriceFactReadyPayload`(inserted/sampled/held/skipped + price_fact_ids 배열) ✅ 2026-04-25
- [x] 메트릭 — `price_fact_inserts_total{outcome}`, `price_fact_observed_to_inserted_seconds` histogram (수집 → mart 반영 latency, SLA 60s 추적) ✅ 2026-04-25
- [x] Settings — `price_fact_sample_rate`(0.05). `.env`/`.env.example` 동기화 ✅ 2026-04-25
- [x] `docker-compose worker-price-fact` 서비스 (queue=price_fact, threads=8) ✅ 2026-04-25
- [x] 통합 테스트 ✅ 2026-04-25 — `tests/integration/test_price_fact_pipeline.py` 4건
  - 98% confidence 2건 동일 retailer/seller/std_code → product_master/seller/retailer 각 1행만 (upsert idempotent), price_fact 2건, outbox `price_fact.ready` 1건
  - 85% confidence + sample_rate=1.0 → INSERT + `crowd_task("price_fact_sample_review")` + crowd outbox
  - 70% confidence → 미적재 + `crowd_task("price_fact_low_confidence")` (PENDING)
  - std_code NULL → skipped, price_fact 미적재, price_fact.ready outbox 만 발행

**다음 sub-phase 로 분리**
- [ ] `unit_price_per_kg` 계산 (weight_g 가 있는 row 만) — Phase 2.2.6.1
- [ ] 일별 집계 배치: `mart.price_daily_agg` UPSERT — Phase 2.2.3 의 시스템 DAG `system_daily_agg` 와 결합 (Phase 2.2.6.2)
- [ ] 이상치 탐지 (median ± 5σ) → `dq.quality_result` 기록 + 집계 제외 — Phase 2.2.8 (DQ)
- [ ] `mart.product_mapping` 적재 (확정 매핑 → 다음 같은 raw 라벨 캐시) — Phase 2.2.6.3
- [ ] retailer/seller 의 retailer_type 자동 분류 (현재 기본값 'ONLINE') — Phase 4 운영팀 보정 단계

### 2.2.7 DB-to-DB 커넥터 [W5~W6]

**기반 (이번 commit) — 외부 DB cursor 기반 incremental fetch + raw_object 적재**
- [x] Migration `0014_data_source_watermark` — `ctl.data_source.watermark JSONB` (last_cursor / last_run_at / last_count) ✅ 2026-04-25
- [x] `app/integrations/sourcedb/{__init__,types,client}.py` — `SourceDbConnector` Protocol + `SqlAlchemySourceDb` 단일 구현. `postgresql+psycopg` / `mysql+pymysql` URL 자동 매칭, identifier 인용(double-quote/backtick), parameterized cursor 비교 ✅ 2026-04-25
- [x] pyproject `pymysql>=1.1` 추가 (PostgreSQL 은 기존 psycopg) ✅ 2026-04-25
- [x] `app/domain/db_incremental.py::pull_incremental` — `data_source` 로드 → connector.fetch_incremental → 단일 트랜잭션에 ingest_job + raw_object(DB_ROW) + content_hash_index + outbox(`ingest.api.received`, kind="db") + watermark UPDATE ✅ 2026-04-25
- [x] `app/workers/db_incremental_worker.py::process_db_incremental_event(source_code, batch_size)` actor (queue=db_incremental, max_retries=3, time_limit=300s) ✅ 2026-04-25
- [x] 메트릭 — `db_incremental_pulled_total{source_code,outcome=fetched/dedup/empty/error}` Counter, `db_incremental_lag_seconds{source_code}` Gauge ✅ 2026-04-25
- [x] `docker-compose worker-db-incremental` 서비스 (queue=db_incremental, threads=4, host-gateway 노출) ✅ 2026-04-25
- [x] `ctl.data_source` ORM 에 watermark 컬럼 + `app/integrations/connectors/base.py` 의 표준 인터페이스 책임을 `sourcedb/types.py` 가 수행 ✅ 2026-04-25
- [x] 통합 테스트 — `tests/integration/test_db_incremental.py` 4건 ✅ 2026-04-25
  - `ext_test_db_incremental.<table>` 시뮬 → 첫 fetch 3건 INSERT + watermark `last_cursor=3` 전진
  - 두 번째 호출 (새 row 없음) → 0 fetch (멱등)
  - 외부 INSERT 후 세 번째 호출 → 신규만 가져옴, watermark 전진
  - `SqlAlchemySourceDb.fetch_incremental(cursor_value=None, batch_size=3)` adapter 단독 회귀

**다음 sub-phase 로 분리**
- [ ] MSSQL/Oracle 드라이버 (필요 시점에 `mssql+pyodbc`, `oracle+oracledb` 추가)
- [ ] 스냅샷 테이블 자동 생성 (`stg.<source>_<table>_snapshot`) — 외부 schema 의 컬럼을 DDL 자동 변환 (Phase 3 SQL Studio sqlglot 검증과 결합)
- [ ] 외부 DB row → `stg.price_observation` 변환 (도메인 별 매핑 — Phase 3 Visual ETL 의 SQL_TRANSFORM 노드로 표현 권장)
- [ ] secret_ref → NCP Secret Manager 연동 (현재는 `password` 평문 — Phase 4 NKS 이관 시점)
- [ ] Airflow DAG `system_ingest_db_incremental` (Phase 2.2.3 후속) — 매 10분 활성 DB source 전수 enqueue

### 2.2.8 크롤링 프레임워크 [W6]

**기반 (이번 commit) — httpx 기반 정적 HTML 크롤러 + raw_web_page 적재 + content_hash dedup**
- [x] `app/integrations/crawler/types.py` — `CrawlerConfig` + `CrawlPage` + `CrawlerSpider` Protocol + `CrawlerError` / `RobotsBlocked` ✅ 2026-04-25
- [x] `app/integrations/crawler/httpx_spider.py` — `HttpxSpider` 구현. User-Agent 강제, `urllib.robotparser` 로 robots.txt 검사 (per-host TTL 캐시), retry 3회 + 4xx 즉시 실패, `CircuitBreaker` 재사용 ✅ 2026-04-25
- [x] `app/domain/crawl.py::fetch_and_store` — source(type=CRAWLER) 검증 → spider.fetch → content_hash 계산 → 같은 (source_id, content_hash) 의 raw_web_page 존재 시 dedup → Object Storage 업로드(`crawl/<source>/<yyyy>/<mm>/<dd>/<hash>.html`) → `raw.raw_web_page` INSERT (parser_version = spider.name) → outbox(`crawler.page.fetched`, kind="crawl") ✅ 2026-04-25
- [x] `app/workers/crawler_worker.py::process_crawl_event(source_code, url)` actor (queue=crawler, max_retries=3, time_limit=300s) ✅ 2026-04-25
- [x] `event_topics`: `EventTopic.CRAWLER_PAGE` + `CrawlerPageFetchedPayload` (page_id/url/content_hash/http_status/html_object_uri/bytes_size) ✅ 2026-04-25
- [x] 메트릭 — `crawler_pages_fetched_total{source_code,outcome=fetched/dedup/error/blocked_by_robots}` Counter, `crawler_fetch_duration_seconds{source_code}` Histogram ✅ 2026-04-25
- [x] Settings — `crawler_user_agent`, `crawler_timeout_sec`(15), `crawler_respect_robots`(true). `.env`/`.env.example` 동기화. `data_source.config_json` 의 spider_kind/seed_urls/respect_robots/fetch_interval_sec 키 사용 ✅ 2026-04-25
- [x] `docker-compose worker-crawler` 서비스 (queue=crawler, threads=4, robots/timeout/UA env 노출) ✅ 2026-04-25
- [x] 테스트 ✅ 2026-04-25
  - `tests/test_httpx_spider.py` (5건, httpx.MockTransport): 200 정상 / 4xx 영구 실패 (재시도 X) / 5xx 재시도 후 성공 / robots.txt Disallow → `RobotsBlocked` (다른 path 는 허용) / robots 404 → 모든 path 허용
  - `tests/integration/test_crawler.py` (3건, 실 PG + stub spider/storage): fetch → raw_web_page INSERT + html_object_uri + outbox / 같은 content_hash 재요청 → dedup outcome (storage put 1번만) / robots 차단 → outcome="blocked_by_robots" 반환 (DB 무영향)

**다음 sub-phase 로 분리**
- [ ] Playwright 런타임 — 동적 페이지 렌더링이 필요한 사이트용 spider 추가 (compose 에 브라우저 이미지 필요)
- [ ] Rate limit 정책 — per-host 토큰 버킷 (현재는 단순 retry/breaker만)
- [ ] 샘플 크롤러 구현 (aT KAMIS 공공 데이터) — Phase 2.2.3 후속 Airflow `system_ingest_kamis` DAG 와 결합
- [ ] HTML → 구조화 파서 (`stg.standard_record` 변환) — 사이트별 스크래퍼 plugin (Phase 3 Visual ETL 의 SOURCE_HTML 노드로 표현 권장)
- [ ] 사이트맵 / RSS 따라가기 (현재는 단일 URL 호출)

### 2.2.9 관제 고도화 [W7]

**기반 (이번 commit) — Loki + Promtail + Sentry + 백로그 게이지 + Runtime 대시보드**
- [x] `docker-compose` 에 `grafana/loki:3.3.2` (single-binary) + `grafana/promtail:3.3.2` 추가 (`/var/run/docker.sock:ro` 마운트로 컨테이너 stdout 자동 수집) ✅ 2026-04-25
- [x] `infra/loki/config.yml` — filesystem chunks (`/var/loki`), retention 7d, ingestion rate 8MB/s, schema v13/tsdb, compactor retention 자동 ✅ 2026-04-25
- [x] `infra/loki/promtail.yml` — `dp_*` 컨테이너만 필터, `service`(컨테이너명)/`env=local`/`stream` 라벨 + structlog JSON pipeline_stages 로 `level/event/source_code/request_id/pipeline_run_id/event_id/timestamp` 추출 ✅ 2026-04-25
- [x] `infra/grafana/provisioning/datasources/loki.yml` — Grafana 자동 등록 + derivedFields 로 `request_id` 클릭 점프 ✅ 2026-04-25
- [x] `app/core/sentry.py::configure_sentry(settings)` + `main.py` lifespan 시작 시 호출. DSN 빈 값이면 no-op. FastAPI/Starlette/SQLAlchemy integration. `before_send` PII 스크럽 (`Authorization`/`Cookie`/`X-OCR-SECRET`/`X-API-Key`/`X-NCP-CLOVASTUDIO-API-KEY` 헤더 + `password`/`secret`/`api_key`/`token`/`dsn`/`access_key` body 키 → `[Filtered]`, 대소문자 무관, 중첩 dict 재귀) ✅ 2026-04-25
- [x] Settings — `sentry_dsn`(SecretStr), `sentry_env`, `sentry_sample_rate`(0.1), `sentry_traces_sample_rate`(0.0). `.env`/`.env.example` 동기화. `pyproject` 에 `sentry-sdk[fastapi]>=2.18` ✅ 2026-04-25
- [x] 백로그 메트릭 ✅ 2026-04-25
  - `outbox_pending_total` Gauge — `run.event_outbox WHERE status='PENDING'` count
  - `dead_letter_pending_total` Gauge — `run.dead_letter WHERE replayed_at IS NULL` count
  - `dramatiq_queue_lag_seconds{topic}` Gauge — Redis Streams `<prefix>:<topic>` 별 XLEN
  - `outbox_publisher.publish_outbox_batch` 가 매 호출 마지막에 일괄 갱신 (publish 시점이 정확)
- [x] `infra/grafana/dashboards/runtime.json` — Phase 2 Runtime 대시보드 신규 (10 패널) ✅ 2026-04-25
  - Workers throughput (OCR / 표준화 outcome / price_fact outcome / db_incremental + crawler)
  - 단계별 latency p95 (ocr / embedding / observed→price_fact / crawler)
  - 백로그 stat (Outbox PENDING / Dead Letter 미처리 / Streams 길이)
  - Loki 로그 패널 2종 (worker stdout / 에러·경고 전 서비스)
- [x] 단위 테스트 `tests/test_sentry_scrubbing.py` (6건) — 헤더/body/extra/case-insensitive/no-request/string-body 6개 케이스 ✅ 2026-04-25

**다음 sub-phase 로 분리**
- [ ] Sentry Release / Source Map 자동 업로드 — Phase 4 NKS GitOps
- [ ] DLQ 운영 도구 (수동 replay UI / replayed_at 마킹) — Phase 3 어드민 화면
- [ ] Alertmanager 룰 (5xx_rate > 1% / outbox_pending > 1000 / ocr 월예산 80%) — Phase 4 NKS
- [ ] Streams group lag 정밀 추적 (`XINFO GROUPS` PEL count) — 현재 XLEN 기반 추정
- [ ] SLO 정의 문서화 (수집→mart p95 < 60s) → Grafana SLO 패널 — `docs/ops/MONITORING.md` 후속 갱신

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
