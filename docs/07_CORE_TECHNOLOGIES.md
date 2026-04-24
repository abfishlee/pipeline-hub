# 07. 핵심 기술 개요 — Kubernetes / Airflow / Kafka

**목적:** 이 세 기술이 각각 **무엇이고, 왜 만들어졌고, 우리 시스템에서 어떤 역할을 하는지** 한 문서에 정리. 학습 지향.

---

# 🟦 1. Kubernetes (NKS) — 컨테이너 오케스트레이션

## 1.1 한 줄 요약
**"수많은 Docker 컨테이너를 여러 서버에 자동으로 배치하고, 죽으면 다시 살리고, 트래픽 따라 늘렸다 줄였다 해주는 시스템."**

## 1.2 왜 만들어졌나?
Docker 컨테이너가 늘어나면 수동으로 어느 서버에 띄울지, 죽으면 누가 살릴지, 업데이트는 어떻게 순차 적용할지 관리하기 어려워짐.
→ Google이 수천 대 서버에서 컨테이너를 관리하던 "Borg"를 오픈소스로 풀어낸 게 Kubernetes(2014).

## 1.3 핵심 개념

| 개념 | 뜻 | 비유 |
|---|---|---|
| **Pod** | 1개 이상의 컨테이너를 묶은 실행 단위 | 방 한 칸 (컨테이너는 그 방의 가구) |
| **Deployment** | "Pod를 N개 유지해줘"라는 선언 | 호텔 운영자 ("203호 항상 가동") |
| **Service** | Pod 그룹에 접근하는 고정 주소 | 호텔 대표 전화번호 |
| **Ingress** | 외부(인터넷)→Service 라우팅 | 호텔 로비 리셉션 |
| **Namespace** | 리소스 논리 분리 공간 | 호텔의 층 (운영팀/개발팀 층 분리) |
| **ConfigMap** | 설정값 묶음 | 각 방 설정 매뉴얼 |
| **Secret** | 비밀 정보 (비밀번호 등) | 금고 |
| **PersistentVolume (PV)** | 영속 저장소 | 호텔 창고 |
| **HPA** | Pod 자동 증감 | 주말엔 방 더 열고 평일 줄임 |
| **RBAC** | 누가 무엇을 할 수 있는지 | 직원 권한 카드 |

## 1.4 주요 기능

| 기능 | 설명 |
|---|---|
| **Self-healing** | Pod가 죽으면 자동 재시작. 노드가 고장나면 다른 노드로 이전. |
| **Rolling Update** | 신버전 Pod 1개씩 교체 → 무중단 배포 |
| **Auto-scaling (HPA)** | CPU/메모리/커스텀 메트릭 기반 Pod 수 자동 조정 |
| **Service Discovery** | Pod IP가 바뀌어도 Service 이름으로 찾기 |
| **Load Balancing** | Service가 여러 Pod에 요청 분산 |
| **Secret 주입** | 환경변수/볼륨으로 안전하게 비밀 전달 |
| **Network Policy** | Pod 간 통신 제한 (제로 트러스트) |

## 1.5 우리 시스템에서의 역할 (Phase 4부터)

**Phase 1~3에는 쓰지 않는다.** Docker Compose로 단일 VM 운영. 이유는 2인 개발팀에 K8s 학습/운영 부담이 개발 속도 저하.

**Phase 4 (운영팀 6~7명 합류) 시 NKS 이관:**

| 우리 컴포넌트 | K8s 리소스 | 이유 |
|---|---|---|
| FastAPI 백엔드 | Deployment(replicas=3) + Service + HPA | 수집 API 트래픽 따라 자동 증감 |
| Dramatiq worker-ocr | Deployment + HPA (커스텀 메트릭: 큐 lag) | OCR 피크 시 Pod 자동 증가 |
| Dramatiq worker-transform | Deployment + HPA | 표준화 부하 대응 |
| Airflow (webserver/scheduler/worker) | Deployment/StatefulSet | 안정성 + 스케일 |
| Frontend | Deployment(replicas=2) | 무중단 배포 |
| Nginx Ingress | Ingress Controller | HTTPS + 라우팅 |
| Secret (DB pw, API key) | ExternalSecrets + NCP Secret Manager | Git 노출 방지 |
| DB migration | Job (Helm hook) | 배포 시 1회 실행 |

### 왜 운영팀 합류 시점에 도입하나
- **6~7명이 독립 작업**하려면 Namespace/RBAC/GitOps 필요.
- **무중단 배포/자동 복구**가 SLA 99.5%의 기반.
- **Argo CD**로 Git push만 하면 배포 → 여러 사람 충돌 없음.

## 1.6 언제 도입을 **하지 말아야** 하나
- 팀이 2명 이하
- 운영 단순화가 학습보다 더 급할 때
- 규모가 작아서 VM 1~2대로 충분
- → **Phase 1~3의 우리 상황이 정확히 이 경우**

## 1.7 학습 단계 (운영팀 온보딩 전 기본)
1. Docker 숙련 (Dockerfile, compose)
2. `kubectl` 기본 5개: `get / describe / logs / exec / apply`
3. Pod → Deployment → Service 개념 이해
4. Helm 템플릿 기초
5. Argo CD GitOps 흐름

---

# 🟨 2. Apache Airflow — 워크플로우 오케스트레이터

## 2.1 한 줄 요약
**"파이썬으로 '작업 그래프(DAG)'를 정의하면, 정해진 시간에 자동 실행하고 실패 시 재시도하고 UI에서 결과를 볼 수 있게 해주는 스케줄러."**

## 2.2 왜 만들어졌나?
- cron은 **순서/의존성/재시도/UI가 없다.**
- "A 끝난 후 B, B 성공 시 C 1번 재시도, 모두 실패하면 Slack 알림" 같은 흐름을 cron으로 쓰면 복잡.
- Airbnb가 2014년에 오픈소스로 풀었음. 이제 데이터 엔지니어링의 **사실상 표준**.

## 2.3 핵심 개념

| 개념 | 뜻 |
|---|---|
| **DAG (Directed Acyclic Graph)** | 방향성 있고 순환 없는 작업 그래프. 한 단위의 워크플로우. |
| **Task** | DAG의 한 노드. 실제 작업 1개. |
| **Operator** | Task의 "타입". `PythonOperator`, `PostgresOperator`, `BashOperator` 등. |
| **Sensor** | 조건이 만족될 때까지 대기하는 Task. (파일 도착/DB row 생김 등) |
| **XCom** | Task 간 작은 데이터 전달 (수 KB). 큰 데이터는 S3 경유. |
| **Scheduler** | 시간 되면 DAG을 실행 대기 큐에 올리는 컴포넌트 |
| **Executor** | 실제로 Task를 돌리는 엔진 (Local/Celery/Kubernetes) |
| **logical_date** | "이 DAG 인스턴스가 대표하는 논리적 시점" (예: 2026-04-24의 집계) |

## 2.4 주요 기능

| 기능 | 설명 |
|---|---|
| **Cron 스케줄** | `schedule="@daily"`, `"*/10 * * * *"` |
| **Backfill** | 과거 기간을 한 번에 돌림 (`airflow dags backfill`) |
| **Retry / 지연 재시도** | `retries=3, retry_delay=5min` |
| **Sensor** | 데이터가 도착할 때까지 대기하는 특수 Task |
| **Web UI** | DAG 목록, 실행 이력, 로그, Gantt, Graph view |
| **의존성** | `a >> b >> c` 로 선후 관계 |
| **Connections / Variables** | DB/API 접속정보와 런타임 변수 중앙 관리 |
| **Alerts** | 실패 시 이메일/Slack |

## 2.5 우리 시스템에서의 역할 (Phase 2부터)

**Airflow = 시스템이 정의한 정기 배치의 오케스트레이터**

우리 프로젝트에서 Airflow가 담당하는 구체 DAG:

| DAG | 주기 | 하는 일 |
|---|---|---|
| `daily_price_aggregation` | 매일 00:30 | 전일 `price_fact` → `price_daily_agg` UPSERT |
| `monthly_partition_create` | 매월 1일 03:00 | 다음 달 파티션 테이블 자동 생성 |
| `daily_raw_archive` | 매일 04:00 | 30일 경과 raw 파일 archive 이동 |
| `hourly_outbox_watchdog` | 매시간 | outbox PENDING > 1000이면 Slack 알림 |
| `ingest_kamis` | 매일 06:00 | aT KAMIS 데이터 pull → raw_object |
| `ingest_db_incremental` | 매 10분 | 외부 DB에서 updated_at 기준 증분 수집 |
| `receipt_backfill` | 수동 | 특정 기간 영수증 재처리 (Backfill) |
| `dq_hold_resume` | 상시 Sensor | `pipeline_run.status='ON_HOLD'` 감시 → 승인 시 후속 재개 |
| `ncp_billing_alert` | 매일 09:00 | CLOVA OCR 비용이 예산 초과 시 알람 |

**역할 경계 (중요):**
- Airflow가 하지 **않는** 일: 실시간 API 처리(FastAPI 담당), 이벤트 단건 처리(Dramatiq 담당), 사용자 정의 파이프라인(Visual ETL 담당).
- Airflow는 **시간**과 **의존성**이 핵심인 작업만.

### Airflow가 우리에게 주는 가치
1. **UI가 있다** — 6~7명 운영팀이 실패 원인 바로 볼 수 있음
2. **Backfill** — 과거 데이터 재수집이 버튼 한 번
3. **Sensor** — "승인 될 때까지 대기" 같은 장기 작업 표현
4. **학습 가치** — 데이터 엔지니어링 업계 표준

## 2.6 Executor 3가지 비교

| Executor | 특징 | 우리 사용 |
|---|---|---|
| **SequentialExecutor** | 1개씩만 실행, 체험용 | 안 씀 |
| **LocalExecutor** | 한 서버에서 병렬 실행 | **Phase 2~3** |
| **CeleryExecutor** | worker 여러 서버 분산 | **Phase 4 (NKS)** |
| **KubernetesExecutor** | Task마다 Pod 생성 | 고려 안 함 |

## 2.7 자세한 학습 가이드
`docs/airflow/LEARNING_GUIDE.md` (10단계, 2~3일 집중) 참고.

---

# 🟥 3. Apache Kafka — 분산 이벤트 스트리밍

## 3.1 한 줄 요약
**"초당 수만~수십만 이벤트를 '여러 소비자가 독립적으로, 순서 보장하며' 받아볼 수 있게 해주는 초고속 분산 메시지 저장소."**

## 3.2 왜 만들어졌나?
- LinkedIn이 2011년에 사용자 행동 로그를 **여러 팀이 실시간으로 재사용**하려고 만듦.
- 기존 메시지 큐(RabbitMQ)는 소비자가 1회 소비하면 사라짐 → 새 consumer가 과거 이벤트 못 봄.
- **Kafka는 이벤트를 디스크에 보관**(기본 7일~영구). 새 consumer가 과거부터 다시 읽을 수 있음.

## 3.3 핵심 개념

| 개념 | 뜻 |
|---|---|
| **Broker** | Kafka 서버 1대 |
| **Cluster** | Broker 여러 대 묶음 |
| **Topic** | 메시지 논리 채널 (예: `cdc.products`) |
| **Partition** | Topic 내 물리 분할. 순서 보장은 Partition 단위. |
| **Producer** | 메시지 보내는 쪽 |
| **Consumer** | 메시지 받는 쪽 |
| **Consumer Group** | 같은 group_id 공유하는 consumer들. partition을 나눠 가짐. |
| **Offset** | Partition 내 메시지 위치 |
| **Retention** | 메시지 디스크 보관 기간 |
| **Replication Factor** | 각 partition 복제본 수 (장애 대비) |

## 3.4 주요 기능

| 기능 | 설명 |
|---|---|
| **초고처리량** | 단일 broker에서 초당 수만 메시지 |
| **디스크 보관** | 7일~영구, 새 consumer가 과거부터 재소비 가능 |
| **순서 보장 (partition 단위)** | 같은 partition 내에선 순서 유지 |
| **Fan-out** | 1개 이벤트를 여러 consumer group이 각자 처리 |
| **Exactly-Once Semantics** | Transactional producer + idempotent |
| **Stream 처리** | Kafka Streams로 변환/집계 실시간 |
| **Connect** | Debezium 등으로 DB ↔ Kafka 자동 동기화 |

## 3.5 Redis Streams와 뭐가 다른가?

| 항목 | Redis Streams | Kafka |
|---|---|---|
| 운영 복잡도 | 낮음 (Redis 1대) | 높음 (broker 3+, KRaft/ZK) |
| 처리량 | 초당 수만 | 초당 수십만+ |
| 보관 기간 | 메모리 한도 내 | 디스크, 영구 가능 |
| 순서 보장 | Stream 단위 | Partition 단위 |
| 관리형 (NCP) | Cloud DB for Redis | 없음 (직접 배포) |
| **우리에게 적합한 용도** | **애플리케이션 이벤트** | **DB CDC 대량 이벤트** |

→ 현재 규모(10만~30만/일)에서는 **Redis Streams가 충분**. Kafka 들어오면 운영 복잡도만 증가.

## 3.6 우리 시스템에서의 역할 (Phase 4 조건부)

**기본값: Kafka 도입하지 않는다.** Redis Streams 유지.

### 도입 트리거 (둘 중 하나 충족 시)
1. **CDC 소스가 3개 이상으로 확장** → Debezium이 Kafka를 사실상 전제로 함.
2. **트래픽이 500K rows/일 초과** + Redis Streams consumer lag 발생.

### 만약 도입하면 역할 분담

| 이벤트 종류 | 버스 |
|---|---|
| 애플리케이션 이벤트 (`ingest.received`, `ocr.completed` 등) | **Redis Streams 계속 사용** |
| **DB CDC 이벤트** (`cdc.retailer_a.public.products`) | **Kafka 전용** |
| 감사 로그 전파 | Redis Streams |
| 로그 집계 | Loki (Kafka 쓰지 않음) |

Kafka가 들어오더라도 **Redis Streams를 대체하지 않는다**. 두 버스가 공존.

## 3.7 Kafka를 안 쓰면 놓치는 것 (현재는 필요 없음)
- 하루치 이벤트를 "새 consumer"가 처음부터 다시 읽는 기능 — 우리는 `raw_object` 테이블에서 재처리 가능, 필요 없음.
- Exactly-once 스트림 변환 — 우리는 Dramatiq idempotent consumer로 충분.
- 수십만 tps 처리 — 당분간 해당 규모 안 옴.

---

# 🎯 세 도구의 책임 분리 한눈에

```
실시간 단건 처리 (< 60초)                Dramatiq + Redis Streams
    수집 이벤트 하나 → OCR → 표준화 → mart

시간 기반 배치 / Backfill / Sensor       Apache Airflow
    매일 집계, 월 파티션, 재수집, HOLD 감시

컨테이너 오케스트레이션 (배포 기반)       Kubernetes (NKS, Phase 4부터)
    Pod 자동 배치/복구/스케일, GitOps

DB CDC 대량 이벤트 (Phase 4 조건부)      Apache Kafka
    Debezium으로 여러 소스 DB 변경을 안정적으로
```

| 질문 | 답 |
|---|---|
| "이 작업 어디서 돌릴까?" 판단 1순위 | 실시간? → Dramatiq / 시간 기반? → Airflow |
| "이 컨테이너 어디서 띄울까?" | Phase 1~3: docker compose / Phase 4+: NKS |
| "이 이벤트 어디로 보낼까?" | 대부분 Redis Streams / DB CDC면 Kafka(조건부) |

---

# 📚 추천 학습 순서 (이 프로젝트 맥락)

1. **Docker + Docker Compose** (Phase 1 시작 전, 1일)
2. **Airflow 기초** (Phase 2 시작 전, 2~3일) — `docs/airflow/LEARNING_GUIDE.md`
3. **React Flow + DAG 개념** (Phase 3 시작 전, 1~2일)
4. **Kubernetes 기초 + Helm + Argo CD** (Phase 4 시작 전 or 운영팀 합류 후 같이, 1주)
5. Kafka는 **실제 도입 필요성이 입증되면** 그때 학습 (Phase 4 후반 or 이후)

---

# 🔗 관련 문서

- 세 도구의 책임 구분 상세: `docs/airflow/INTEGRATION.md`
- Airflow 초심자 학습: `docs/airflow/LEARNING_GUIDE.md`
- NKS 배포 가이드: `docs/ops/NKS_DEPLOYMENT.md`
- 데이터 흐름 10단계: `docs/06_DATA_FLOW.md`
