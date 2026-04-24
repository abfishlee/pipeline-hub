# 01. 기술 스택 (확정)

팀이 2명(사용자 + Claude)이고 Naver Cloud Platform 배포이므로 **최소 복잡도 + NCP 네이티브** 기준으로 스택을 고정한다. 여기 없는 라이브러리/서비스는 **도입 전 사용자에게 확인**.

## 1.1 런타임/언어

| 영역 | 선택 | 버전 | 이유 |
|---|---|---|---|
| Backend 언어 | Python | 3.12+ | 원본 설계서 기준, 팀 역량 |
| Frontend 언어 | TypeScript | 5.4+ | React Flow/React 생태계 표준 |
| 패키지 매니저 (Py) | `uv` | 최신 | pip보다 빠르고 락파일 안정 |
| 패키지 매니저 (TS) | `pnpm` | 9+ | monorepo 확장 용이 |

## 1.2 Backend

| 영역 | 선택 | 대체안 (사용하지 않음) |
|---|---|---|
| Web Framework | **FastAPI** 0.110+ | Django(과함), Flask(비동기 약함) |
| ASGI Server | **uvicorn** + `--workers` | gunicorn(uvicorn 내장이면 충분) |
| ORM | **SQLAlchemy 2.0** (async) | Django ORM, Tortoise |
| Migration | **Alembic** | 직접 SQL (사용 금지) |
| 설정 관리 | **Pydantic Settings v2** | python-dotenv 단독 |
| HTTP 클라이언트 | **httpx** (async) | requests(동기 전용) |
| 검증 | Pydantic v2 | marshmallow |
| 로깅 | **structlog** + JSON 출력 | stdlib logging 단독 |

## 1.3 데이터 저장소

| 영역 | 로컬 | NCP 프로덕션 |
|---|---|---|
| RDBMS | PostgreSQL 16 (Docker) | **NCP Cloud DB for PostgreSQL** |
| Cache/Queue | Redis 7 (Docker) | **NCP Cloud DB for Redis** |
| Object Storage | MinIO (Docker) | **NCP Object Storage** (S3 호환) |
| Secret | 로컬 `.env` | **NCP Secret Manager** |

PostgreSQL 확장: `pgcrypto`, `pg_trgm`, `uuid-ossp`, `btree_gin`.

## 1.4 비동기/워커

| 영역 | 선택 | 이유 |
|---|---|---|
| Task Queue (실시간 처리) | **Dramatiq** (Redis broker) | Celery보다 가볍고 운영 단순. priority/retry/DLQ 내장 |
| 스케줄러 + Orchestrator | **APScheduler** (Phase 1) → **Apache Airflow 2.9+** (Phase 2 정식) | 데이터 엔지니어링 표준. UI/Backfill/Sensor/재실행 수동 가능 |
| 이벤트 큐 (실시간) | **Redis Streams** | Kafka 대비 운영 코스트 1/10, 현 트래픽에 충분 |
| DB 이벤트 | **PostgreSQL LISTEN/NOTIFY** + Outbox 테이블 | Airflow Sensor가 Outbox를 주시 |

### Airflow 역할 분담 (중요)

- **Airflow** = 시스템이 정의한 **정기/시스템 배치** — 일별 집계, 파티션 생성, 아카이브, DB-to-DB 증분, 크롤러 스케줄, DQ 게이트 승인 대기 등.
- **Visual ETL Designer** (Phase 3) = 사용자가 웹에서 설계하는 **비즈니스 정제 흐름**.
- **Dramatiq** = 실시간 이벤트 처리 (수집→OCR→표준화→mart), 수백 ms 응답.

두 오케스트레이션을 섞지 않는다. 자세한 역할 구분은 `docs/airflow/INTEGRATION.md`.

**Phase 4 조건부 Kafka 도입:**
- 트리거 1: Debezium CDC 소스가 3개 이상으로 확장 (기본 PoC는 1건)
- 트리거 2: 트래픽 500K rows/일 초과 + Redis Streams lag 발생
- 도입 시 ADR 작성 후 사용자 승인 필요.

## 1.5 프론트엔드

| 영역 | 선택 | 이유 |
|---|---|---|
| Framework | **React 18** + **Vite 5** | React Flow 생태계 |
| UI Kit | **shadcn/ui** (Tailwind 기반) | 생성된 컴포넌트 직접 보유, 커스터마이즈 자유 |
| Styling | **Tailwind CSS 3** | shadcn 전제 |
| State | **Zustand** (client) + **TanStack Query v5** (server) | Redux는 과함 |
| Router | **React Router v6** | Next.js는 SSR 불필요로 과함 |
| Visual ETL | **React Flow** | 본 설계서 전제 |
| 차트 | **Recharts** | 가벼움 |
| 폼 | **react-hook-form + zod** | |

## 1.6 AI / OCR / 외부 서비스

| 용도 | 1차 선택 | 폴백 |
|---|---|---|
| 영수증 OCR | **NAVER CLOVA OCR** (NCP 네이티브, 한국 영수증 특화) | Upstage Document AI |
| 상품명 → 표준코드 매핑 | **임베딩 기반 유사도** (OpenAI `text-embedding-3-small` 또는 HyperCLOVA X) + 규칙 보정 | TF-IDF + 사전 매핑 테이블 |
| 문서 분류 (영수증/전단/기타) | 단순 규칙 (Phase 2) → 경량 분류 모델 (Phase 4 검토) | — |

**비용 발생 서비스는 도입 전 반드시 사용자 승인.**

## 1.7 관제/관측

| 영역 | 선택 |
|---|---|
| 메트릭 | **Prometheus** + **prometheus_client** (Python) |
| 대시보드 | **Grafana** |
| 로그 집계 | **Loki** (Phase 2부터) |
| 트레이싱 | **OpenTelemetry** (Phase 2부터, 선택) |
| 에러 알림 | Sentry (Phase 2부터, 무료 플랜) |
| APM | 필요 시 재검토 (현재 미도입) |

## 1.8 인프라 / 배포 (2-stage)

### Stage A — Phase 1~3 (개발, 사용자+Claude 2인)

| 영역 | 로컬 | 운영 (NCP VM) |
|---|---|---|
| 컨테이너 런타임 | Docker Desktop (Windows) | NCP Container Registry + VM Docker |
| 오케스트레이션 | **Docker Compose** | **Docker Compose (단일 VM)** |
| CI/CD | GitHub Actions | GitHub Actions → SSH 배포 스크립트 |
| HTTPS/도메인 | 없음 | NCP Global Traffic Manager + Let's Encrypt |
| 설정/비밀 | `.env` | NCP Secret Manager → 환경변수 |

**이 단계의 선택 이유:** 사용자+Claude 2인 개발에서는 K8s manifest/helm 디버깅 시간이 비즈니스 기능 구현 시간을 잠식. docker compose로 빠른 반복.

### Stage B — Phase 4 (운영 이관, 6~7명 운영팀 합류)

| 영역 | 기술 선택 |
|---|---|
| 컨테이너 오케스트레이션 | **NKS (Naver Kubernetes Service)** — 매니지드 Control Plane |
| Node 구성 | Worker node 3대 시작 (`s2-g3` 2vCPU/8GB), HPA로 증감 |
| 배포 방식 | **GitOps** — Argo CD + Git repo (`infra/k8s/manifests`) |
| 패키징 | **Helm Charts** (공통), Kustomize(env별 overlay) |
| IaC | **Terraform (NCP Provider)** — VPC/NKS 클러스터/Cloud DB/Object Storage 전체 |
| Ingress | NKS Ingress NGINX + cert-manager (Let's Encrypt) |
| Secret | **External Secrets Operator** + NCP Secret Manager 연동 |
| 관제 | kube-prometheus-stack (Prometheus + Alertmanager + Grafana) + Loki |
| 로그 | Promtail → Loki |
| 트레이싱 | OpenTelemetry + Tempo (선택) |
| 백업 | **Velero** (PV/리소스 스냅샷), NCP Cloud DB 자동 백업 |

**이 단계의 선택 이유:** 6~7명이 독립 배포·네임스페이스 분리·RBAC·자동 복구·무중단 롤링 업데이트를 요구. NKS 매니지드라 Control Plane 운영 부담 없음.

### Phase 1부터 지켜야 할 "NKS 이관 Ready" 규칙

이 규칙만 지키면 Phase 4 이관 시 manifest 작성만으로 NKS 전환 가능:

1. **Stateless 컨테이너.** 로컬 파일 쓰기/디스크 의존 금지. 필요한 상태는 DB/Object Storage로.
2. **설정은 환경변수.** 하드코딩 금지. 이미지 rebuild 없이 변경 가능해야 함.
3. **헬스체크 엔드포인트.** `/healthz` (liveness), `/readyz` (readiness). DB 연결/큐 연결까지 확인.
4. **SIGTERM graceful shutdown.** 종료 신호 받으면 진행 중 요청 끝내고 10~30초 내 종료.
5. **로그는 stdout JSON.** 파일 로깅 금지.
6. **Request ID 전파.** k8s Service 간 추적을 위해 필수 (이미 `05_CONVENTIONS.md` 5.4).
7. **이미지는 multi-stage 빌드**로 가볍게. 알려진 취약점 스캔(trivy) CI에 포함.
8. **DB migration은 Init Job 패턴.** Alembic이 앱 시작 때 돌게 하지 말고, 별도 Job 또는 배포 파이프라인 step으로.

자세한 Stage B 가이드: `docs/ops/NKS_DEPLOYMENT.md`.

## 1.9 테스트

| 영역 | 선택 |
|---|---|
| Python 유닛/통합 | **pytest** + **pytest-asyncio** + **pytest-httpx** |
| DB 테스트 | `pytest-postgresql` (실제 PG 컨테이너 권장) |
| API 테스트 | FastAPI `TestClient` + httpx |
| E2E (프론트) | **Playwright** (Phase 3부터) |
| 린트/포맷 (Py) | **ruff** (lint + format 통합) |
| 린트/포맷 (TS) | **biome** 또는 eslint+prettier |
| 타입체크 | mypy (strict) / tsc |

## 1.10 보안

| 영역 | 선택 |
|---|---|
| 인증 (운영자) | **JWT** + refresh token (Phase 1) → OIDC (Phase 4, 선택) |
| 인증 (외부 소비자) | **API Key** (Phase 4) |
| 비밀번호 해시 | **Argon2id** (`argon2-cffi`) |
| CORS | FastAPI 미들웨어, 화이트리스트만 허용 |
| Rate Limit | **slowapi** (Phase 1) → NCP API Gateway (Phase 4) |
| SQL 파서 (SQL Studio 검증) | **sqlglot** |
| 위험 SQL 차단 | sqlglot AST 분석 (DROP/TRUNCATE/ALTER/GRANT 거부) |

## 1.11 버전/의존성 관리 원칙

- Python 의존성은 `pyproject.toml` + `uv.lock`.
- 프론트는 `package.json` + `pnpm-lock.yaml`.
- 의존성 추가 시 **사용 이유를 PR 설명에 기재**. 알려지지 않은 라이브러리는 도입 전 검토.
- 메이저 버전 업그레이드는 단독 PR.

## 1.12 변경 절차

이 문서의 스택을 바꾸려면:
1. `docs/adr/XXXX-change-name.md` (ADR) 작성 — 배경, 결정, 대안, 영향.
2. 사용자 승인.
3. 본 문서 갱신.

## 1.13 한 줄 요약

> **FastAPI + PostgreSQL + Redis + NCP Object Storage + React Flow + Dramatiq + Airflow. 개발은 Docker Compose, Phase 4 운영 이관 시 NKS. Kafka는 조건부. OCR은 CLOVA.**
