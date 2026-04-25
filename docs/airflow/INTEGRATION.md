# Airflow + Visual ETL + Dramatiq 역할 분담

**이 프로젝트는 오케스트레이션 도구 3가지를 섞어 쓴다. 각자의 영역이 겹치지 않도록 명확히 구분.**

## 1. 세 오케스트레이션 도구의 책임

| 도구 | 담당 영역 | 트리거 | 실행 단위 | 결과 저장 |
|---|---|---|---|---|
| **Dramatiq** | 실시간 이벤트 처리 | Redis Streams 메시지 도착 | 수 ms ~ 수 초 | `raw.*` / `stg.*` / `mart.*` 즉시 반영 |
| **Airflow** | 시간 기반 시스템 배치 | cron 스케줄 or 수동 | 수 초 ~ 수 분 | `mart.price_daily_agg` 등 집계 / 아카이브 |
| **Visual ETL** | 사용자 정의 변환 흐름 | 사용자가 UI에서 "실행" or 스케줄 | 수 초 ~ 수 분 | 각 노드 정의에 따라 |

## 2. 각 도구가 **만지지 않을** 영역

| 도구 | 하지 않는 것 |
|---|---|
| Dramatiq | 스케줄링 / Backfill / UI 조작 / 다단계 DAG 의존성 |
| Airflow | 수집 API 자체 / 이벤트당 즉시 처리 / 사용자 정의 노드 |
| Visual ETL | 시스템 내부 유지보수 (파티션 생성, 백업, 감시) |

## 3. 실제 흐름 예시

### 3.1 영수증 업로드 → Mart 반영 (실시간 경로)

```
사용자 영수증 업로드 (모바일)
  ↓ HTTP POST /v1/ingest/receipt
[FastAPI]  raw_object + outbox insert
  ↓ Redis Streams
[Dramatiq worker-ocr]  CLOVA OCR 호출
  ↓ ocr_result 저장 + outbox
[Dramatiq worker-transform]  표준화 (std_code 매핑)
  ↓ confidence >= 0.95
stg.price_observation → mart.price_fact INSERT
  ← 완료까지 < 60초
```

Airflow는 이 흐름에 개입하지 않는다.

### 3.2 일별 집계 (Airflow 영역)

```
[Airflow scheduler]  매일 00:30 트리거
  ↓
DAG: daily_price_aggregation
  ├─ task 1: 전일자 확정 (receipt 지연 수집 커버)
  ├─ task 2: mart.price_daily_agg UPSERT
  ├─ task 3: 이상치 탐지 → dq.quality_result
  └─ task 4: Slack 알림 (성공/실패)
```

Dramatiq는 이 흐름에 개입하지 않는다.

### 3.3 DQ 실패로 HOLD 된 파이프라인 재개 (Airflow + Visual ETL + Dramatiq 협력)

```
[Visual ETL Pipeline Run]  실행 중
  ↓
DQ_CHECK 노드 FAIL (severity=ERROR)
  ↓
pipeline_run.status = ON_HOLD  (Dramatiq가 set)
  ↓
[Airflow] DAG: dq_hold_resume
  └─ Sensor: ON_HOLD 상태 polling
  └─ 승인자가 UI에서 승인하면 status = RUNNING
  └─ Sensor release → 다음 task
  └─ 후속 노드 재개 이벤트 Redis Streams로 발행
  ↓
[Dramatiq worker-transform]  HOLD 후속 노드 처리 이어감
  ↓
LOAD_MASTER 성공 → 완료
```

세 도구가 이벤트 버스(Redis Streams + PG outbox)를 통해 통신.

### 3.4 Backfill (Airflow)

```
운영자: "2026-04-01 ~ 2026-04-10 KAMIS 데이터 다시 수집해줘"
  ↓
Airflow CLI:
  airflow dags backfill --start-date 2026-04-01 --end-date 2026-04-10 ingest_kamis
  ↓
DAG 인스턴스 10개 생성 (logical_date 1일씩)
각 DAG가:
  1) raw_object insert
  2) outbox에 'staging.ready' 이벤트 발행
  3) Dramatiq가 받아 표준화 + mart 반영
```

## 4. 경계선 판단 기준

**"이 작업, Airflow로 할까 Dramatiq로 할까?"** 물으면:

| 질문 | 예 → | 도구 |
|---|---|---|
| 이벤트 1건이 도착하자마자 처리? | 예 | **Dramatiq** |
| 시간 기반 주기(매시간, 매일)? | 예 | **Airflow** |
| 여러 task 의존성 + 일부 실패 시 개별 재시도? | 예 | **Airflow** |
| 수백 ms 이하 응답 중요? | 예 | **Dramatiq** |
| 재처리/Backfill 필요? | 예 | **Airflow** |
| UI에서 실행 이력/성공/실패를 보고 싶다? | 예 | **Airflow** |
| 한 이벤트가 fan-out 되어 여러 consumer가 같이 받아야? | 예 | **Dramatiq (Redis Streams consumer group)** |

"사용자가 웹에서 노드로 그린 흐름?" → **Visual ETL** (내부적으로 Dramatiq가 실행, 스케줄이 있으면 Airflow DAG로 등록).

## 5. Airflow와 Visual ETL의 관계

### 5.1 사용자가 Visual ETL에서 "매일 06:00 실행" 설정하면

1. Pipeline PUBLISHED 시 내부적으로 Airflow DAG 파일 자동 생성:
   - `backend/airflow_dags/generated/pipeline_{id}_v{version}.py`
2. 이 DAG은 단 하나의 태스크만 가진다: `trigger_pipeline_run(pipeline_id, version)`
3. 태스크가 실행되면 `run.pipeline_run` insert → Dramatiq가 이어받아 노드 실행
4. Airflow UI에서는 "트리거만" 보이고, 실제 노드 상태는 Visual ETL UI에서 본다

### 5.2 왜 이렇게 나누나?

- Visual ETL은 "데이터 변환 그래프의 시각화" 가 본질.
- Airflow는 "시간/백필/재실행 UI" 가 본질.
- Airflow DAG에 React Flow 그래프를 정교하게 매핑하려고 시도하면 서로의 강점이 섞여 둘 다 약해진다.
- 대신 **스케줄 소유권을 Airflow가 가진다** (진실의 원천). Visual ETL UI는 편집만.

## 6. Kafka 도입 시 (Phase 4 조건부)

Kafka가 들어오면 Redis Streams와 어떻게 겹치는가?

| 용도 | 도구 |
|---|---|
| 애플리케이션 이벤트 (`ingest.received`, `ocr.completed` 등) | **Redis Streams** 유지 |
| DB CDC 이벤트 (`cdc.source_a.public.products`) | **Kafka + Debezium** |
| 로그 집계 | Loki 별도 |

즉 Kafka는 "DB 변경 로그 전용 특수 버스"로 도입. 애플리케이션 이벤트까지 Kafka로 몰면 운영 복잡도만 올라가고 이득 없음.

## 6.5 로컬 기동 (Phase 2.2.3 ~)

`make airflow-up` 한 줄이면 Airflow 가 main `docker compose` 스택에 합류한다.
LocalExecutor 1프로세스 — 시스템 DAG 트래픽엔 충분하다 (수평 확장은 Phase 4 NKS 에서
CeleryExecutor 로 전환).

```bash
make dev-up         # 인프라 + 관제
make airflow-up     # airflow-init → webserver/scheduler 일괄 기동
make airflow-logs   # 로그 follow
```

| URL | 인증 |
|---|---|
| http://localhost:8080 | `airflow` / `airflow` (`.env` 의 `AIRFLOW_ADMIN_PASSWORD` override 권장) |

### Connections (자동 등록 — `airflow-init`)

| Conn ID | 용도 | URI |
|---|---|---|
| `postgres_default` | 메인 애플리케이션 DB (`datapipeline`) | `postgresql://app:app@postgres:5432/datapipeline` |
| `redis_default` | Redis Streams / Dramatiq 같은 인스턴스 | `redis://redis:6379/0` |

Airflow metadata DB 는 별도 — `postgresql+psycopg2://app:app@postgres:5432/airflow` (postgres 첫 기동 시 `infra/postgres/init/01_create_airflow_db.sql` 가 생성).

### DAG 작성 규칙 (Phase 2.2.3)

이 프로젝트의 Airflow DAG 는 **시스템 DAG** 만 포함한다 (집계 / 파티션 / 아카이브 / DB-to-DB 증분 등). 사용자 정의 파이프라인은 Phase 3 Visual ETL 이 별도로 다룬다.

- 파일/dag_id: `system_<purpose>` (예: `system_daily_agg`, `system_monthly_partition`).
- tag: `["system", "phase-N"]` 최소.
- owner: `platform` (운영팀 합류 후 팀 이름으로 갱신).
- 외부 호출은 Operator / Hook / `connections` 사용 — DAG 안에서 직접 `requests.get` 금지 (`7. 금지 사항` 참조).
- 새 시스템 DAG 추가 시 `infra/airflow/dags/<dag>.py` 작성 → 재기동 없이 scheduler 가 1분 내 인식.
- Phase 2 의 Hello smoke test: `infra/airflow/dags/hello_pipeline.py` (`system_hello_pipeline` 1회 손으로 trigger 해보면 BashOperator + PythonOperator 1개씩 동작).

운영(NKS) 이관 시: provider 패키지는 `infra/airflow/requirements/airflow.txt` 핀을 그대로 베이스 이미지에 COPY → `_PIP_ADDITIONAL_REQUIREMENTS` 의존 제거.

## 7. 금지 사항

- ❌ Dramatiq actor 안에서 `time.sleep()` 길게 쓰기 (→ Airflow Sensor 써라)
- ❌ Airflow task 안에서 사용자 요청 처리 (→ FastAPI + Dramatiq 써라)
- ❌ Visual ETL 노드에서 시스템 유지보수 (→ Airflow DAG로 분리)
- ❌ Airflow DAG에서 직접 `requests.get` 하는 대신 Operator/Hook 쓰기
- ❌ Kafka를 Dramatiq 대체로 도입 (둘 다 쓰는 상황이면 책임 구분 기준에 따라 나눔)

## 8. 한 장 요약

```
┌──────────────────────────── 이벤트/명령 들어옴 ────────────────────────────┐
│                                                                             │
│  실시간(API/파일 업로드)  →  FastAPI  →  outbox  →  Dramatiq               │
│                                                                             │
│  시간 기반(크론) ─────────────────────→  Airflow scheduler                │
│                                                                             │
│  사용자 UI(Visual ETL 실행) ──→ pipeline_run insert ──→ Dramatiq          │
│                                    │                                        │
│                                    └─ PUBLISHED 스케줄 있으면 ─→ Airflow   │
│                                                                             │
│  DB CDC(Phase 4) ────────────→ Kafka → Dramatiq transform 큐              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
