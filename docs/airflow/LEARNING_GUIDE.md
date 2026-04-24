# Airflow 학습 가이드 (초심자용)

**대상:** Airflow를 처음 써보는 사용자. 이 프로젝트에 필요한 만큼만 단계별로 학습.
**원칙:** "왜 쓰는가 → 최소 동작 → 우리 프로젝트에 어떻게 적용하는가" 순서로.

---

## Step 0 — Airflow가 뭔가?

**한 줄 정의:** 파이썬으로 정의한 작업 그래프(DAG)를 정해진 스케줄에 맞춰 실행하고, 결과를 UI로 모니터링하는 데이터 오케스트레이터.

**이 프로젝트에서 Airflow 가 하는 일:**
- 매일 00:30에 어제자 가격 데이터 집계
- 매월 1일에 다음 달 파티션 테이블 생성
- 매 10분마다 DB-to-DB 증분 수집
- 특정 기간 데이터 재수집(Backfill) 버튼 1번으로
- Outbox backlog 감시하다 이상 시 Slack 알림
- DQ 실패로 `ON_HOLD` 된 파이프라인이 승인되면 다음 단계 자동 재개

**이 프로젝트에서 Airflow가 하지 않는 일:**
- 실시간 수집 API → 이건 FastAPI가 한다
- 실시간 OCR/표준화 처리 → 이건 Dramatiq worker가 한다
- 사용자가 웹에서 설계하는 파이프라인 → 이건 Visual ETL Designer가 한다

**왜 Dramatiq과 둘 다 쓰나?** 
- Dramatiq: 이벤트 즉시 처리 (수집 직후 OCR 돌리기)
- Airflow: 시간 기반 일감 (매일 집계, 재처리, 감시)
- 두 도구는 역할이 다르고 한 쪽이 다른 쪽을 대체할 수 없다. `INTEGRATION.md` 참고.

---

## Step 1 — 5분 체험 (로컬에서 띄워보기)

```bash
# 1) 작은 테스트용 docker-compose
docker run -d --name airflow-demo -p 8080:8080 \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=true \
  apache/airflow:2.9.3-python3.12 standalone
```

- 브라우저 `http://localhost:8080` 접속, `airflow/airflow` 로그인
- 예제 DAG 몇 개 켜서 (toggle ON) 실행되는 모습 보기
- **DAGs → Grid view** 에서 태스크 색상 (초록=성공, 빨강=실패, 회색=미실행) 익히기
- **DAGs → Graph view** 에서 의존성 그래프 보기

체크:
- [ ] DAG이 어디에 정의되어 있는지 확인 (컨테이너 안 `/opt/airflow/dags`)
- [ ] 태스크 실패 시 클릭하면 로그를 볼 수 있음을 확인

---

## Step 2 — 가장 단순한 DAG 작성

`my_first_dag.py`:

```python
from __future__ import annotations
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

def say_hello():
    print("안녕 Airflow!")

def say_goodbye():
    print("잘 가 Airflow!")

with DAG(
    dag_id="my_first_dag",
    start_date=datetime(2026, 4, 25),
    schedule="@daily",              # 매일 자정
    catchup=False,                  # 과거분 자동 실행 방지
    tags=["tutorial"],
    default_args={
        "owner": "me",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
) as dag:

    t1 = PythonOperator(task_id="hello", python_callable=say_hello)
    t2 = PythonOperator(task_id="bye",   python_callable=say_goodbye)

    t1 >> t2   # t1 완료 후 t2
```

**학습 포인트:**
- `dag_id`는 고유. 파일명과 다를 수 있음.
- `schedule`: `@daily` / `@hourly` / `"*/10 * * * *"` (크론 표현식).
- `start_date` 는 "이 시점부터 스케줄 계산 시작" 이라는 뜻. **지금 기준 과거 날짜로 두면 catchup=True 일 때 과거 것까지 다 돌려버리므로 주의.**
- `>>` 연산자로 의존성 표현.
- `retries`, `retry_delay` 는 기본값.

---

## Step 3 — 우리 DB에 붙기

**Connection 등록 (Airflow UI → Admin → Connections):**
- Conn Id: `datapipeline_pg`
- Conn Type: Postgres
- Host / Schema / Login / Port / Password 입력

**DAG 예:**

```python
from airflow import DAG
from airflow.providers.postgres.operators.postgres import PostgresOperator
from datetime import datetime

with DAG(
    dag_id="daily_price_aggregation",
    start_date=datetime(2026, 4, 25),
    schedule="30 0 * * *",     # 매일 00:30
    catchup=False,
    tags=["system", "price"],
) as dag:

    refresh = PostgresOperator(
        task_id="refresh_daily_agg",
        postgres_conn_id="datapipeline_pg",
        sql="""
            -- 어제+오늘 집계 (지연 수집 반영)
            INSERT INTO mart.price_daily_agg (...)
            SELECT ...
            FROM mart.price_fact
            WHERE observed_at::date >= CURRENT_DATE - INTERVAL '1 day'
            ON CONFLICT (agg_date, std_code, retailer_id, region_sido)
            DO UPDATE SET ...;
        """,
    )
```

---

## Step 4 — Sensor 개념 (조건 만족까지 대기)

데이터가 도착할 때까지 기다리다가 다음 단계로 가는 용도.

```python
from airflow.sensors.sql import SqlSensor

wait_for_new_rows = SqlSensor(
    task_id="wait_outbox",
    conn_id="datapipeline_pg",
    sql="""
      SELECT 1 FROM run.event_outbox
      WHERE event_type = 'staging.ready'
        AND status = 'PENDING'
      LIMIT 1
    """,
    poke_interval=60,          # 60초마다 확인
    timeout=60 * 60,           # 최대 1시간 기다림
    mode="reschedule",         # worker slot 해제하며 대기 (효율적)
)
```

**이 프로젝트에서:**
- `DQHoldSensor` — `run.pipeline_run.status='ON_HOLD'` 가 풀릴 때까지 대기
- `RawArrivalSensor` — 특정 source에서 오늘치 raw 도착 확인

---

## Step 5 — Backfill (과거 재수집)

**명령:**
```bash
airflow dags backfill \
  --start-date 2026-04-01 \
  --end-date   2026-04-24 \
  daily_price_aggregation
```

- 과거 날짜를 논리적 실행일(`logical_date`)로 집어넣어 각 날짜별로 DAG 1회씩 실행.
- 실무에서 "어제 파이프라인이 실패했는데 오늘 분은 이미 돌았다" 같은 상황에서 필수.

---

## Step 6 — Executor 개념

| Executor | 특징 | 우리 프로젝트 |
|---|---|---|
| **SequentialExecutor** | 1개씩만 실행. 로컬 체험용. | 안 씀 |
| **LocalExecutor** | 한 머신에서 병렬 실행. PG metadata. | **Phase 2 기본** |
| **CeleryExecutor** | worker 여러 머신 분산. Redis/Kafka broker. | Phase 4에서 검토 |
| **KubernetesExecutor** | 태스크마다 K8s pod. | 우리 범위 아님 |

시작은 항상 LocalExecutor, 태스크 많아지면 Celery로 전환.

---

## Step 7 — DAG 작성 시 반드시 지킬 것

- [ ] **Idempotent (멱등)**. 같은 `logical_date` 로 재실행해도 결과가 같아야 함. 절대 `INSERT` 만 쓰지 말고 `UPSERT` 사용.
- [ ] **원자성**. 하나의 DAG task 안에서 여러 트랜잭션 금지. 실패 시 중간상태 방지.
- [ ] **작은 task 여러 개**. 한 task에 모든 로직 몰지 말기. 실패 후 재시도 쉽게.
- [ ] **외부 호출은 타임아웃**. `execution_timeout` 반드시 지정.
- [ ] **큰 데이터 XCom 금지**. XCom은 작은 값(ID 등)만. 대용량은 Object Storage 경유.
- [ ] **로그에 비밀 금지**. connection은 Airflow UI에서 관리.
- [ ] **파일 기준 DAG 저장**. DB에 DAG 정의 저장 안 함 (파일이 SoT).
- [ ] **DAG 파일 top-level에서 무거운 작업 금지**. DAG 스케줄러가 계속 재평가하므로, DB 쿼리/HTTP 호출을 top-level에 두면 느려짐.

---

## Step 8 — 이 프로젝트의 DAG 디렉토리 구조

```
backend/airflow_dags/
├── system/                           # 플랫폼 자체 유지보수
│   ├── daily_price_aggregation.py
│   ├── monthly_partition_create.py
│   ├── hourly_outbox_watchdog.py
│   └── daily_raw_archive.py
├── ingest/                           # 수집
│   ├── ingest_kamis.py
│   ├── ingest_db_incremental.py
│   └── receipt_backfill.py
├── quality/                          # DQ 관련
│   └── dq_hold_resume.py
├── common/                           # 공용 helper (센서, callable)
│   ├── __init__.py
│   ├── sensors.py
│   └── callables.py
└── tests/
    └── test_dag_imports.py
```

---

## Step 9 — 학습 순서 제안 (2~3일 집중)

| 날 | 할 일 |
|---|---|
| Day 1 오전 | Step 0~2 (개념 + 체험) |
| Day 1 오후 | Step 3 (PG 연결) + 우리 DB에서 SELECT 돌리는 DAG 작성 |
| Day 2 오전 | Step 4 (Sensor) + `hourly_outbox_watchdog.py` 실습 |
| Day 2 오후 | Step 5 (Backfill) + `daily_price_aggregation.py` 작성 |
| Day 3 | docker-compose 통합, `AIRFLOW__` 환경변수 익히기, Connection을 secret에서 주입하는 법 |

---

## Step 10 — 자주 막히는 부분

| 증상 | 원인 | 해결 |
|---|---|---|
| DAG이 UI에 안 보임 | 파일 파싱 에러 | `airflow dags list-import-errors` 로 원인 확인 |
| 스케줄됐는데 실행이 안 됨 | `catchup=True` 인데 과거 너무 많음 | `catchup=False` + 수동 backfill |
| task가 queued 상태에서 안 움직임 | worker slot 부족 | `parallelism`, `dag_concurrency` 설정 확인 |
| `execution_date` vs `logical_date` 헷갈림 | 2.2+ 에서 이름 변경 | 둘 다 같은 개념, `logical_date` 사용 |
| XCom 크기 제한 | 기본 48KB | 큰 데이터는 S3/Object Storage 경유 |
| Connection 비밀 누설 | UI나 로그에 노출 | Fernet 키 관리 + 로그 mask |

---

## 추천 레퍼런스

- 공식 튜토리얼: https://airflow.apache.org/docs/apache-airflow/stable/tutorial/index.html
- Astronomer 가이드: https://docs.astronomer.io/learn
- "Data Pipelines with Apache Airflow" (Manning) — 입문서 1권

---

## Claude에게 도움 요청할 때 쓸 명령 예시

> "docs/airflow/LEARNING_GUIDE.md 의 Step 2 예제를 우리 레포에 맞춰 만들어줘. 목적은 `hourly_outbox_watchdog` 이고 DAG 파일 위치는 `backend/airflow_dags/system/` 이야."

> "내가 만든 `daily_price_aggregation.py` 를 리뷰해줘. Idempotent 체크와 execution_timeout 적정값을 봐주고, 개선 포인트를 3가지만 뽑아줘."

> "Airflow UI에서 task가 queued로 멈췄어. 로그를 줄 테니 원인 후보 3개랑 확인 명령어 알려줘."

더 많은 명령 템플릿은 `docs/HOW_TO_WORK_WITH_CLAUDE.md` 참고.
