# 02. 아키텍처 및 폴더 구조

## 2.1 논리 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│  외부 (External)                                                    │
│  - 대형마트 POS API  - 온라인몰  - SNS  - 영수증 업로드  - aT/여기고기 │
└───────────────┬─────────────────────────────────────────────────────┘
                │
         ┌──────▼──────┐
         │ API Gateway │  (Phase 4: rate limit / API Key)
         └──────┬──────┘
                │
┌───────────────▼────────────────────────────────────────────────────┐
│  Ingest Layer — FastAPI                                            │
│  /v1/ingest/api/{source}    /v1/ingest/file/{source}               │
│  /v1/ingest/receipt         /v1/crawlers/*                         │
└────┬──────────────────────────────────────────┬────────────────────┘
     │ raw 보존 (Object Storage)                │ metadata insert
     │                                          │
     ▼                                          ▼
┌──────────────────┐              ┌─────────────────────────────────┐
│ NCP Object Store │              │ PostgreSQL                      │
│ raw/             │              │  ctl  raw  stg  wf              │
│   api/ocr/crawl/ │              │  run  dq   mart audit           │
│ archive/         │              └──┬──────────────────────────────┘
└──────────────────┘                 │
                                     │ LISTEN/NOTIFY + Outbox
                                     ▼
                          ┌───────────────────────┐
                          │ Redis Streams         │
                          │ Dramatiq Queue        │
                          └──────────┬────────────┘
                                     │
                ┌────────────────────┼─────────────────────┐
                ▼                    ▼                     ▼
         ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
         │ OCR Worker  │      │ Transform   │      │ Crawler     │
         │ (CLOVA OCR) │      │ Worker      │      │ Worker      │
         └──────┬──────┘      │ (SQL+AI     │      └──────┬──────┘
                │             │  표준화)    │             │
                │             └──────┬──────┘             │
                └────────────────────┼────────────────────┘
                                     ▼
                          ┌───────────────────────┐
                          │ Staging → Mart        │
                          │ (DQ 게이트 통과 시)   │
                          └──────────┬────────────┘
                                     │
                ┌────────────────────┼─────────────────────┐
                ▼                    ▼                     ▼
         ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
         │ Web Portal  │      │ Crowd 검수  │      │ Public API  │
         │ (내부 운영) │      │ (내부 직원) │      │ (외부 소비자)│
         └─────────────┘      └─────────────┘      └─────────────┘
```

## 2.2 배포 아키텍처 (2-stage)

### 2.2.A Phase 1~3 — 단일 VM Docker Compose 배치

```
┌──────────────────── NCP VM (단일 Compute) ────────────────────┐
│                                                                │
│  Docker Compose:                                               │
│    ├─ nginx (reverse proxy, TLS termination)                   │
│    ├─ fastapi (gunicorn+uvicorn, N workers)                    │
│    ├─ worker-ocr        (dramatiq — 실시간 OCR)                │
│    ├─ worker-transform  (dramatiq — 실시간 표준화/mart 반영)    │
│    ├─ worker-crawler    (dramatiq — 별도 큐)                   │
│    ├─ airflow-webserver (정기 배치 UI + trigger)               │
│    ├─ airflow-scheduler (DAG 스케줄링)                         │
│    ├─ airflow-worker    (LocalExecutor → Phase 4에 CeleryExec) │
│    ├─ frontend (정적 빌드 산출물, nginx 서빙)                  │
│    ├─ prometheus                                               │
│    └─ grafana                                                  │
│                                                                │
│  외부:                                                          │
│    ├─ NCP Cloud DB for PostgreSQL (Airflow metadata도 동일 PG) │
│    ├─ NCP Cloud DB for Redis                                   │
│    └─ NCP Object Storage                                       │
└────────────────────────────────────────────────────────────────┘
```

수평 확장 시 워커 컨테이너만 별도 VM에서 띄우고 DB/Redis는 동일 매니지드 서비스 공유.

### 2.2.B Phase 4 — NKS 배치 (운영팀 6~7명 합류)

```
┌────────────────────── NKS Cluster (NCP 매니지드) ──────────────────────┐
│                                                                         │
│  Namespace: datapipeline-prod                                           │
│    ├─ ingress-nginx (Ingress Controller)                                │
│    │                                                                    │
│    ├─ Deployment: backend-api         (replicas: 3, HPA min3/max10)     │
│    ├─ Deployment: worker-transform    (replicas: 2, HPA min2/max8)      │
│    ├─ Deployment: worker-ocr          (replicas: 2, HPA min2/max6)      │
│    ├─ Deployment: worker-crawler      (replicas: 1)                     │
│    ├─ Deployment: frontend            (replicas: 2)                     │
│    │                                                                    │
│    ├─ StatefulSet: airflow-scheduler  (replicas: 1)                     │
│    ├─ Deployment:  airflow-webserver  (replicas: 2)                     │
│    ├─ Deployment:  airflow-worker     (CeleryExecutor, replicas: 2~6)   │
│    │                                                                    │
│    ├─ Job: db-migrate                 (배포 시 1회, Alembic upgrade)    │
│    ├─ ConfigMap: app-config                                             │
│    ├─ ExternalSecret: app-secrets     (→ NCP Secret Manager)            │
│    └─ ServiceAccount + RBAC                                             │
│                                                                         │
│  Namespace: datapipeline-staging                                        │
│    └─ (prod 미러, 축소 replica)                                         │
│                                                                         │
│  Namespace: observability                                               │
│    ├─ kube-prometheus-stack (Prometheus + Alertmanager + Grafana)       │
│    ├─ loki + promtail                                                   │
│    └─ tempo (선택, 트레이싱)                                            │
│                                                                         │
│  Namespace: argocd                                                      │
│    └─ Argo CD (GitOps)                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

외부 매니지드 서비스 (NKS 바깥):
   ├─ NCP Cloud DB for PostgreSQL (app + airflow metadata)
   ├─ NCP Cloud DB for Redis (Dramatiq broker + SSE pub/sub)
   ├─ NCP Object Storage (raw + archive 버킷)
   └─ NCP Secret Manager (External Secrets Operator로 동기화)
```

**핵심 원칙:**
- **Stateful 요소는 NKS 밖**(매니지드 DB/Redis/Object Storage). PVC 최소화.
- **네임스페이스 분리**: prod / staging / observability / argocd.
- **Argo CD로 GitOps**. `infra/k8s/` Git repo 가 선언적 원천.
- **Secret은 Git에 절대 금지**, External Secrets Operator로 런타임 주입.
- **HPA(수평 자동 스케일)** 는 CPU+커스텀 메트릭(큐 lag) 기반.
- **NetworkPolicy** 로 pod 간 접근 제한 (backend → DB만, worker는 Redis+DB).

### 2.2.C 마이그레이션 경로

```
Phase 1~3:  Dev local → NCP VM(docker compose)
                                  ↓
Phase 4 시작:  Staging NKS 환경 구축 (Terraform으로 새 클러스터)
                                  ↓
             Prod 데이터 유지한 채 앱만 NKS 전환 (Cloud DB/Object Storage는 그대로)
                                  ↓
             VM 환경 2주간 병행 운영 후 폐기
```

상세 절차: `docs/ops/NKS_DEPLOYMENT.md`.

## 2.3 저장 책임 분리 (중요)

| 저장소 | 담는 것 | 담지 않는 것 |
|---|---|---|
| **PostgreSQL** | 메타데이터, 구조화된 가격 레코드, 작업 이력, 상태, 감사 로그, 마스터 | 대용량 원본 파일(PDF/이미지/HTML), 장기 로그 |
| **Object Storage** | 원본 파일, 원본 JSON 대용량, HTML 스냅샷, OCR 이미지, 대형 CSV | 빠른 조회 필요 데이터 |
| **Redis** | 큐/스트림, 일시적 캐시, rate limit 카운터, SSE pub/sub | 영속 데이터 |
| **Loki (Phase 2+)** | 애플리케이션 로그 | 비즈니스 이벤트 |

## 2.4 프로젝트 폴더 구조

```
datapipeline/
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml               # 로컬 개발용
├── docker-compose.prod.yml          # 운영용
│
├── docs/                            # 설계 문서 (본 디렉토리)
│
├── backend/                         # FastAPI 애플리케이션
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app 생성
│   │   ├── config.py                # Pydantic Settings
│   │   ├── deps.py                  # 공통 DI (DB 세션, 현재 사용자)
│   │   │
│   │   ├── api/                     # 라우터 (HTTP 경계)
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── ingest.py
│   │   │   │   ├── sources.py
│   │   │   │   ├── jobs.py
│   │   │   │   ├── raw.py
│   │   │   │   ├── pipelines.py
│   │   │   │   ├── sql_studio.py
│   │   │   │   ├── quality.py
│   │   │   │   ├── crowd.py
│   │   │   │   └── monitoring.py
│   │   │   └── public/              # 외부 소비자용 (Phase 4)
│   │   │
│   │   ├── core/                    # 공통 유틸 (DB 경계 X)
│   │   │   ├── security.py          # JWT, Argon2
│   │   │   ├── logging.py           # structlog 설정
│   │   │   ├── errors.py            # 예외 클래스
│   │   │   ├── hashing.py           # content_hash 계산
│   │   │   └── idempotency.py
│   │   │
│   │   ├── domain/                  # 도메인 서비스 (비즈니스 로직)
│   │   │   ├── ingest.py
│   │   │   ├── standardization.py   # 상품명 → 표준코드
│   │   │   ├── matching.py          # 중복/매칭
│   │   │   ├── quality.py           # DQ 규칙 실행
│   │   │   ├── pipeline.py          # Visual Pipeline 실행기
│   │   │   └── sql_studio.py        # SQL 파싱/검증/샌드박스
│   │   │
│   │   ├── integrations/            # 외부 서비스 어댑터 (여기만 외부 호출 허용)
│   │   │   ├── clova_ocr.py
│   │   │   ├── upstage_ocr.py
│   │   │   ├── embedding.py
│   │   │   ├── object_storage.py    # NCP OS / MinIO 추상화
│   │   │   ├── crawler/
│   │   │   │   ├── base.py
│   │   │   │   ├── coupang.py
│   │   │   │   └── ...
│   │   │   └── connectors/
│   │   │       ├── kamis.py         # aT 연계
│   │   │       └── yeogigogi.py     # 여기고기 앱
│   │   │
│   │   ├── models/                  # SQLAlchemy ORM
│   │   │   ├── __init__.py
│   │   │   ├── ctl.py               # 스키마별 분리
│   │   │   ├── raw.py
│   │   │   ├── stg.py
│   │   │   ├── mart.py
│   │   │   ├── wf.py
│   │   │   ├── run.py
│   │   │   ├── dq.py
│   │   │   └── audit.py
│   │   │
│   │   ├── schemas/                 # Pydantic I/O DTO
│   │   │   ├── ingest.py
│   │   │   └── ...
│   │   │
│   │   ├── repositories/            # DB 쿼리 캡슐화
│   │   │   └── ...
│   │   │
│   │   └── workers/                 # Dramatiq actor 정의
│   │       ├── ocr.py
│   │       ├── transform.py
│   │       ├── crawler.py
│   │       ├── outbox_publisher.py
│   │       └── scheduler.py         # APScheduler 등록
│   │
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       ├── integration/
│       └── fixtures/
│
├── frontend/                        # React + Vite
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── Dockerfile
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Sources.tsx
│   │   │   ├── Jobs.tsx
│   │   │   ├── RawObjects.tsx
│   │   │   ├── OcrReview.tsx
│   │   │   ├── Crawlers.tsx
│   │   │   ├── CrowdTasks.tsx
│   │   │   ├── SqlStudio.tsx
│   │   │   ├── PipelineDesigner.tsx
│   │   │   ├── Schedule.tsx
│   │   │   ├── Quality.tsx
│   │   │   ├── MasterData.tsx
│   │   │   ├── Monitoring.tsx
│   │   │   ├── AuditLog.tsx
│   │   │   └── Users.tsx
│   │   ├── components/
│   │   │   ├── ui/                  # shadcn/ui 생성물
│   │   │   ├── designer/            # Visual ETL 노드/엣지
│   │   │   ├── sql/
│   │   │   └── common/
│   │   ├── api/                     # TanStack Query hooks
│   │   ├── store/                   # Zustand
│   │   ├── lib/
│   │   └── styles/
│   └── tests/
│
├── migrations/                      # Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── infra/
│   ├── docker-compose.yml           # symlink 또는 실제 파일
│   ├── nginx/
│   │   └── nginx.conf
│   ├── terraform/                   # Phase 4에서 생성
│   │   └── ncp/
│   └── scripts/
│       ├── deploy.sh
│       ├── backup_db.sh
│       └── ...
│
├── scripts/
│   ├── seed_data_sources.py
│   ├── seed_standard_codes.py
│   └── reindex_products.py
│
└── tests/                           # 레포 전체 레벨 통합 테스트
    └── e2e/
```

## 2.5 Backend 레이어 규칙

```
  api/  ─────▶  domain/  ─────▶  repositories/  ─────▶  models/
                  │
                  └────▶  integrations/
```

- **api/**: HTTP 요청/응답 변환만. 비즈니스 로직 금지. Pydantic DTO → domain 함수 호출.
- **domain/**: 비즈니스 규칙. DB 의존성은 repository를 통해서만. `requests`/`httpx` 직접 호출 금지.
- **repositories/**: SQLAlchemy 쿼리 한곳에 모음. ORM 객체 또는 Pydantic DTO 반환.
- **integrations/**: 외부 서비스 호출은 **여기만**. 재시도/서킷브레이커/타임아웃은 이 층에서.
- **models/**: ORM 정의만. 비즈니스 메서드 금지.
- **workers/**: Dramatiq actor는 `domain/` 함수를 호출하는 얇은 래퍼.

## 2.6 이벤트 흐름 (Outbox 패턴)

```
[1] FastAPI handler
    BEGIN
      INSERT INTO raw.raw_object ...
      INSERT INTO run.event_outbox (event_type='ingest.received', payload_json=...)
    COMMIT

[2] outbox_publisher worker
    - 1초 주기로 status='PENDING' 이벤트 조회 (FOR UPDATE SKIP LOCKED)
    - Redis Streams에 XADD
    - status='PUBLISHED' + published_at=now() 업데이트

[3] Worker (ocr/transform/crawler)
    - Redis Streams XREADGROUP
    - 처리 후 run.processed_event 에 event_id 기록 (idempotent consumer)
    - 결과 staging/mart insert + 새 outbox 이벤트 발행
```

## 2.6.1 Airflow 와 실시간 경로의 역할 분리

```
[실시간 경로]                      [정기/시스템 배치 경로]
수집 API                           Airflow Scheduler
   │                                    │
   │ outbox                             │ DAG trigger
   ▼                                    ▼
Redis Streams                       airflow-worker
   │                                    │
   │                                    │  (Python operator / BashOperator)
   ▼                                    ▼
Dramatiq Worker                     시스템 작업:
(<1분 내 완료)                        - daily aggregation
   │                                  - partition create/archive
   ▼                                  - DB-to-DB incremental
staging/mart                          - crawler rerun/backfill
                                      - Sensor: DQ HOLD 해제 감시
```

**분리 원칙:**
- 수집→OCR→표준화→mart 반영 같은 **실시간 단건 처리는 Dramatiq**가 수행.
- 시간대/주기성 있는 **배치/시스템 작업은 Airflow DAG**.
- Airflow DAG도 결과를 `run.event_outbox`에 기록 → 동일 이벤트 버스 유지.
- Visual ETL에서 "예약" 버튼 누르면 내부적으로 Airflow DAG가 생성된다 (Phase 3).

## 2.7 실시간 상태 반영 (SSE)

- Visual Pipeline Designer 화면의 노드 상태는 **Redis Pub/Sub → SSE**로 브라우저에 전달.
- `GET /v1/pipeline-runs/{id}/stream` (Server-Sent Events).
- WebSocket 안 쓴다 — 단방향이면 SSE로 충분하고 프록시 친화적.

## 2.8 설정/비밀 관리

- 로컬: `.env` (git 제외), `.env.example`(git 포함).
- 운영: NCP Secret Manager → 컨테이너 환경변수 주입.
- `app/config.py`는 Pydantic `BaseSettings`를 통해 읽는다. 직접 `os.getenv` 금지.

## 2.9 도메인 이벤트 종류 (`run.event_outbox.event_type`)

```
ingest.api.received
ingest.file.received
ingest.receipt.received
crawler.page.fetched
ocr.requested
ocr.completed
standardization.requested
standardization.completed
staging.ready
transform.requested
transform.completed
dq.checked
dq.failed
master.updated
crowd.task.created
crowd.task.reviewed
pipeline.run.started
pipeline.run.finished
pipeline.node.state.changed
dead.letter
```

### 2.9.1 Redis Streams 토픽 (Phase 2.2.2~)

`run.event_outbox` 의 행이 outbox publisher 에 의해 Redis Streams 로 옮겨진 형태.
**stream key = `<APP_REDIS_STREAMS_PREFIX>:<aggregate_type>`** (기본 prefix `dp:events`).
**consumer group = `<worker_type>-<env>`** (예: `outbox-local`, `ocr-prod`) — 같은 토픽을
여러 worker_type 이 fan-out 으로 받음. 같은 worker_type 의 다중 인스턴스는 group 을
공유하고 redis 가 자동 분산.

| Stream key | 발행자 | 소비자 (worker_type) | 도입 Phase | 페이로드 모델 |
|---|---|---|---|---|
| `dp:events:raw_object` | `outbox_publisher` (Phase 2.2.1) | `transform`, `ocr`, `standardization` | 2.2.2 | `RawObjectCreatedPayload` (`app/core/event_topics.py`) |
| `dp:events:ocr_result` | `worker-ocr` (Phase 2.2.4) | `standardization`, `crowd` | 2.2.4 | TBD — `OcrCompletedPayload` |
| `dp:events:standardization_result` | `worker-standardization` (Phase 2.2.5) | `transform` | 2.2.5 | TBD — `StandardizationCompletedPayload` |
| `dp:events:crawler_page` | `worker-crawler` (Phase 2.2.6) | `transform` | 2.2.6 | TBD |
| `dp:events:pipeline_node_state` | `pipeline-runtime` (Phase 3.x) | SSE bridge → 프론트 | 3.x | TBD |

**Streams message fields** (모든 토픽 공통):

| field | 타입 | 비고 |
|---|---|---|
| `event_id` | string | `run.event_outbox.event_id` 그대로. processed_event 마킹 키. |
| `aggregate_type` | string | stream key 의 suffix 와 같음 (예: `raw_object`). |
| `aggregate_id` | string | 도메인 식별자 (예: `<raw_object_id>:<partition_date>`). |
| `event_type` | string | `<aggregate_type>.<verb>` 규칙 (예: `raw_object.created`). |
| `occurred_at` | ISO-8601 | 발행 시각. |
| `payload` | JSON string | 토픽별 typed model — `parse_message()` 로 deserialize. |

**Idempotency** — at-least-once 라 같은 `event_id` 재배달 가능. 다운스트림은
`run.processed_event` 의 `(event_id, consumer_name)` 마킹으로 멱등 처리
(`app/domain/idempotent_consume.py::consume_idempotent`). 운영자 수동 replay 는
`reset_processed_marker(event_id, consumer_name)` 후 XCLAIM 또는 단일 XADD 재발행.

**Crash 복구** — consumer 가 read 후 ack 전 죽으면 메시지가 PEL(pending entries
list) 에 남는다. 살아 있는 consumer 가 `RedisStreamConsumer.claim_stale(min_idle_ms=...)`
(`XAUTOCLAIM`) 으로 인계받아 처리. 표준 idle 임계는 worker_type 별로 정의
(예: ocr=120s, transform=30s).

## 2.10 환경 분리

| 환경 | 목적 | DB | Object Storage |
|---|---|---|---|
| local | 개발 | Docker PG | MinIO |
| dev | 내부 테스트 (NCP) | NCP PG (dev) | NCP OS (dev bucket) |
| prod | 운영 | NCP PG (prod) | NCP OS (prod bucket) |

`APP_ENV=local|dev|prod` 환경변수로 구분.
