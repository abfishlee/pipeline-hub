# 06. 데이터 흐름 — 10단계별 기능과 기술

수집된 농축산물 가격 데이터가 **"수집 → Mart → 외부 서비스"** 까지 가는 10단계 전체를 한눈에.

## 전체 흐름 다이어그램

```
 (1) Ingestion       →  (2) Raw 보존   →  (3) Event 발행
  수집 API/파일           PG + Object Storage    Outbox + Redis Streams
       │                       │                       │
       └───────────────────────┴───────────────────────┘
                                 ▼
 (4) Processing (OCR / 표준화 / 파싱)
       │                                                
       ▼                                                
 (5) Staging                                           
  stg.price_observation                                
       │                                                
       ▼                                                
 (6) Data Quality Gate                                 
       │                                                
       ▼                                                
 (7) Mart Load                                         
  mart.price_fact / master                             
       │                                                
       ▼                                                
 (8) Serving / Aggregation                             
  price_daily_agg, Public API                          
       │                                                
       ▼                                                
 (9) Observability  ←→  (10) Orchestration           
  Prom/Grafana/SSE          Airflow/Dramatiq/Visual ETL
```

---

## Stage 1 — Ingestion (수집)

**무엇을 하나:** 농축산물 가격 정보가 **플랫폼에 들어오는 입구**. 5개 채널.

| 채널 | 입력 | 빈도 | 담당 컴포넌트 |
|---|---|---|---|
| 대형마트/SSM **Open API** | JSON POST | 실시간/정시 | FastAPI `/v1/ingest/api/{source}` |
| 마트 **DB 증분 수집** | PG/MySQL 테이블 | 10분 간격 | Airflow DAG + DB Connector |
| 할인 전단 / **영수증 OCR** | 이미지 multipart | 소비자 업로드 | FastAPI `/v1/ingest/receipt` |
| 온라인몰 **크롤링** | HTML 페이지 | 30분 간격 | Playwright + Crawler Worker |
| aT KAMIS / 여기고기 **연계** | API pull | 일 1회 | Airflow DAG |

**핵심 기능:**
- Idempotency-Key 헤더 검증
- 요청 크기 제한 (20MB max)
- robots.txt / 약관 준수 (크롤링)
- Schema validation (JSON)

**핵심 기술:**
- **FastAPI** + **Pydantic v2** — HTTP 경계
- **httpx** — 외부 API pull
- **Playwright** — 브라우저 기반 크롤링
- **wal2json** — DB CDC (Phase 4)

---

## Stage 2 — Raw 보존 (Preservation)

**무엇을 하나:** 들어온 데이터를 **원형 그대로** 저장. 나중에 언제든 재처리 가능하게.

**핵심 원칙:**
- **PostgreSQL** = 메타데이터 / 작은 JSON / 참조
- **Object Storage** = 큰 파일 / 이미지 / HTML

| 대상 | 저장소 | 이유 |
|---|---|---|
| raw_object 메타 | `raw.raw_object` (PG) | 인덱스 조회 필요 |
| 작은 JSON (<64KB) | PG `payload_json` | 추가 조회 불필요 |
| 큰 JSON / 파일 / 이미지 | NCP Object Storage | DB 공간 절약 |
| 중복 감지 | `raw.content_hash_index` (SHA256) | 전역 유일성 보장 |
| OCR 결과 | `raw.ocr_result` | 텍스트 + 좌표 |
| 크롤링 페이지 | `raw.raw_web_page` + OS | HTML 원본 보존 |

**핵심 기능:**
- `content_hash` 계산 → 전역 dedup
- `idempotency_key` → 재시도 안전
- 파일은 presigned URL 방식 (업로드/다운로드)

**핵심 기술:**
- **PostgreSQL 16** (파티션 + GIN jsonb_path_ops)
- **NCP Object Storage** (S3 호환, boto3)
- **hashlib / SHA256** — content_hash
- **SQLAlchemy 2.0** (async) — 트랜잭션

---

## Stage 3 — Event 발행 (Event Publishing)

**무엇을 하나:** 수집된 데이터를 **"다른 서비스가 반응할 수 있는 신호"로 변환**.

### 왜 이벤트가 필요한가?
수집 API가 직접 OCR/표준화까지 다 하면 응답이 느려지고 실패 복구도 어려움. **수집(1)과 처리(4)를 이벤트로 분리**하면 독립적으로 스케일/재시도 가능.

### Outbox Pattern
```sql
-- 단일 트랜잭션 안에서
INSERT INTO raw.raw_object ...          -- 원천 저장
INSERT INTO run.event_outbox (...)       -- 이벤트 큐에 넣기 (아직 발행 안 됨)
COMMIT;                                  -- 둘 다 성공해야 commit
```

```
별도 프로세스(outbox_publisher)가 1초 주기로:
  SELECT * FROM run.event_outbox WHERE status='PENDING' FOR UPDATE SKIP LOCKED
  → Redis Streams XADD
  → UPDATE status='PUBLISHED'
```

**이벤트 타입 예시:**
```
ingest.api.received          ocr.completed
ingest.receipt.received      standardization.completed
crawler.page.fetched         staging.ready
ocr.requested                dq.checked / dq.failed
                             master.updated
```

**핵심 기술:**
- **PostgreSQL Outbox 테이블** — 트랜잭션 정합성
- **PostgreSQL LISTEN/NOTIFY** — DB 변경 알림
- **Redis Streams** — 고속 이벤트 버스 (consumer group)
- **Idempotent Consumer** — `run.processed_event` 로 중복 처리 방지

---

## Stage 4 — Processing (실시간 처리)

**무엇을 하나:** 이벤트를 받아 **실제 변환 작업** 수행. OCR, 표준화, 파싱.

### 4-a. OCR (영수증/전단 이미지)

```
이미지 수신 (Redis Streams: ocr.requested)
  ↓
CLOVA OCR General/Receipt 모드 호출
  ↓
confidence 점수 평가
  ├─ ≥ 0.85 → 자동 stg 적재
  └─ < 0.85 → crowd_task 생성 (OCR_REVIEW)
```

**핵심 기술:** CLOVA OCR / Upstage (폴백), Dramatiq worker.

### 4-b. 표준화 (상품명 → 표준코드)

```
"국산 참외 특품 10kg 박스"
  ↓ (정규화: 공백/괄호 제거)
"참외 특품 10kg 박스"
  ↓ (추출: 등급='특', 중량=10000g, 포장='박스')
  ↓
[1차] 사전 alias 매칭 ──→ std_code='FRT-CHAMOE', confidence 1.0
[2차] trigram 유사도 (pg_trgm)
[3차] 임베딩 cosine 유사도 (pgvector + HyperCLOVA X)
  ↓
confidence ≥ 0.95 → price_fact insert
0.70~0.95 → crowd_task (PRODUCT_MATCHING)
< 0.70 → staging hold
```

**핵심 기술:**
- **pg_trgm** — 유사도 검색 GIN 인덱스
- **pgvector** — 임베딩 기반 매칭
- **HyperCLOVA X 임베딩 API** — 한국어 상품명 벡터화
- **Dramatiq worker-transform**

### 4-c. 크롤링 결과 파싱
HTML → 상품명/가격 추출. 파서 버전 기록.

### 4-d. DB 증분 수집 변환
원천 DB row → stg standard record.

---

## Stage 5 — Staging (표준화 저장)

**무엇을 하나:** 모든 채널의 데이터를 **공통 스키마**로 맞춤.

**핵심 테이블:**
- `stg.standard_record` — 공통 JSONB body (entity_type 기반 일반화)
- `stg.price_observation` — 가격 관찰 전용 (자주 쓰는 컬럼화)

**왜 staging이 필요?**
- 각 채널마다 필드/단위/등급 표현이 달라서 **한 번 평평하게 만들어야** mart에 일관되게 넣을 수 있음.
- staging은 **되돌리기 가능한 영역** — mart에 쏟기 전 최종 검증.

**business_key** 으로 중복 제거:
- PRODUCT: `(retailer_id, retailer_product_code)` 또는 `(retailer_id, raw_name_hash)`
- PRICE: `(product_id, seller_id, observed_at to minute, source_id)`

---

## Stage 6 — Data Quality Gate (품질 게이트)

**무엇을 하나:** mart 적재 **직전**에 품질 규칙 검사. 실패 시 **자동 HOLD**.

### 예시 규칙

| 유형 | 예 | severity |
|---|---|---|
| NOT_NULL | `std_code IS NOT NULL` | ERROR |
| RANGE | `price_krw BETWEEN 10 AND 10000000` | ERROR |
| FORMAT | 사업자번호 형식 `\d{3}-\d{2}-\d{5}` | WARN |
| REFERENCE | `std_code` 가 `mart.standard_code` 존재 | ERROR |
| DISTRIBUTION | 전일 대비 건수 ±50% 벗어남 | WARN |
| OCR_CONF | `confidence_score ≥ 0.7` | WARN |
| CONSISTENCY | `valid_from ≤ valid_to` | ERROR |
| UNIQUE | `business_key` 중복 없음 | WARN |

### 게이트 동작
```
rule SQL 실행 → 실패 row count 집계
  ↓
severity=ERROR & failed_count > 0
  ↓
pipeline_run.status = 'ON_HOLD'
승인자 알림 (Slack)
Airflow Sensor DAG가 감시 → 승인 시 재개
```

**핵심 기술:**
- `dq.quality_rule` / `dq.quality_result` — 규칙/결과
- Airflow **SqlSensor** — HOLD 감시
- Dramatiq — rule SQL 비동기 실행

---

## Stage 7 — Mart Load (마스터 적재)

**무엇을 하나:** 검증 통과한 데이터를 **서비스용 최종 테이블**에 반영.

### 주요 적재 대상

| 테이블 | 성격 | 적재 방식 |
|---|---|---|
| `mart.price_fact` | 시계열 append (월 파티션) | INSERT (중복은 dedup에서) |
| `mart.product_master` | 마스터 | UPSERT (business_key) |
| `mart.product_mapping` | 유통사 상품 ↔ 마스터 연결 | UPSERT |
| `mart.retailer_master` | 유통사 마스터 | UPSERT |
| `mart.seller_master` | 매장 마스터 | UPSERT |
| `mart.master_entity_history` | SCD Type 2 이력 | INSERT + `is_current` 업데이트 |

### 핵심 계산
- `unit_price_per_kg = price_krw / weight_g * 1000` (정규화 단가)
- `canonical_name` 자동 조립

**핵심 기술:**
- PostgreSQL **ON CONFLICT DO UPDATE** (UPSERT)
- 파티션 자동 관리 (Airflow 월별 생성)
- **BRIN 인덱스** on `observed_at` (append-heavy에 적합)

---

## Stage 8 — Serving (집계 + 외부 API)

**무엇을 하나:** mart 데이터를 **사용자/외부 소비자가 쓰기 좋은 모양**으로 가공·제공.

### 8-a. 일별 집계
- `mart.price_daily_agg` — `(agg_date, std_code, retailer_id, region_sido)` 그룹
- 매일 00:30 Airflow DAG가 전일+당일 UPSERT (지연 수집 커버)
- `min/avg/max/median/count` 계산

### 8-b. Public API (Phase 4)
```
GET /public/v1/standard-codes
GET /public/v1/products?query=참외
GET /public/v1/prices/latest?std_code=FRT-CHAMOE
GET /public/v1/prices/daily?std_code=FRT-CHAMOE&from=2026-04-01&to=2026-04-25
GET /public/v1/prices/series?product_id=123
```

### 8-c. 내부 Web Portal
- 원천 조회 / Visual ETL / SQL Studio / 크라우드 작업함 / 관제 대시보드

**핵심 기술:**
- **Airflow DAG** — 일별 집계
- **FastAPI** — Public API + 내부 API
- **slowapi + Redis** — API Key 기반 rate limit
- **Redis cache** — 자주 조회 응답 60~300초 캐시
- **NCP API Gateway** (Phase 4 검토)

---

## Stage 9 — Observability (관제)

**무엇을 하나:** 시스템이 **건강한지 눈으로 볼 수 있게** 하고, 문제 시 **알린다**.

| 영역 | 도구 | 수집 대상 |
|---|---|---|
| 메트릭 | **Prometheus** | 수집 qps, 큐 lag, DB pool, HPA 메트릭 |
| 대시보드 | **Grafana** | 수집/처리/mart 반영 latency |
| 로그 | **Loki + Promtail** | JSON 구조화 로그 |
| 트레이싱 | OpenTelemetry + Tempo (Phase 4 옵션) | 요청 분산 추적 |
| 에러 | **Sentry** | unhandled exception |
| 실시간 상태 | **SSE (Server-Sent Events)** | Visual ETL 노드 상태 |
| 감사 | `audit.access_log`, `audit.sql_execution_log` | 접근/SQL/다운로드 |
| 알람 | Alertmanager → **Slack** | 5xx, 큐 backlog, DQ FAIL, 비용 |

**왜 SSE?** — Visual ETL 화면에서 "중복 제거 노드가 지금 돌고 있다"를 실시간 표시. WebSocket 대신 SSE로 단방향 push (프록시 친화).

---

## Stage 10 — Orchestration (오케스트레이션)

**무엇을 하나:** 위 9개 단계를 **언제/어떻게 실행할지 조정**.

### 세 갈래로 책임 분리

| 오케스트레이터 | 역할 | 트리거 |
|---|---|---|
| **Dramatiq** | 실시간 단건 처리 (이벤트 1건 < 60초) | Redis Streams 메시지 |
| **Airflow** | 시간 기반 / Backfill / Sensor | cron / 수동 |
| **Visual ETL Designer** | 사용자 정의 비즈니스 파이프라인 | 사용자 or Airflow trigger |

자세한 역할 분담은 `docs/airflow/INTEGRATION.md`.

---

## 각 Stage가 어느 Phase에 구축되는가

| Stage | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| 1. Ingestion | ✅ (API/파일/영수증) | ✅ (크롤링/DB 증분) | | ✅ (CDC) |
| 2. Raw 보존 | ✅ | | | ✅ (archive 자동화) |
| 3. Event 발행 | ✅ (Outbox 생성만) | ✅ (Publisher 가동) | | |
| 4. Processing | | ✅ (OCR/표준화) | | |
| 5. Staging | (스키마만) | ✅ (실제 변환) | | |
| 6. DQ Gate | | (rule 실행) | | ✅ (게이트/HOLD) |
| 7. Mart Load | (스키마만) | ✅ | | ✅ (multi-source 머지) |
| 8. Serving | (내부 조회 UI) | ✅ (일별 집계) | | ✅ (Public API) |
| 9. Observability | ✅ (기초) | ✅ (Loki/Sentry) | ✅ (SSE) | ✅ (Public API 사용량) |
| 10. Orchestration | | ✅ (Airflow) | ✅ (Visual ETL) | ✅ (CDC 연동) |

---

## 한 장 요약

> **수집(API/파일/크롤링/DB) → PG+Object Storage 원천 보존 → Outbox→Redis Streams 이벤트 → Dramatiq가 OCR/표준화 → stg → DQ 게이트 → mart → Airflow가 매일 집계 → FastAPI가 외부에 제공. 전 과정은 Prometheus/Grafana로 관측.**
