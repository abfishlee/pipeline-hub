# Unified Data Pipeline Platform (pipeline-hub)

농축산물 가격 데이터를 다채널에서 수집 → AI 표준코드로 정규화 → 외부 서비스에 제공하는 플랫폼.

**상태:** Phase 1 — Core Foundation **완료** + Phase 2 — Pipeline Runtime **완료** (2026-04-25). Phase 3 — Visual ETL Designer + SQL Studio 진입.

---

## 먼저 읽을 것

1. [`CLAUDE.md`](CLAUDE.md) — Claude 작업 원칙, 핵심 맥락
2. [`docs/README.md`](docs/README.md) — 전체 문서 목차
3. [`docs/phases/CURRENT.md`](docs/phases/CURRENT.md) — 현재 Phase / 타임라인
4. [`docs/dev/PHASE_1_E2E.md`](docs/dev/PHASE_1_E2E.md) — Phase 1 동작 검증 시나리오 (10단계, 30분)
5. [`docs/dev/PHASE_2_E2E.md`](docs/dev/PHASE_2_E2E.md) — Phase 2 자동 파이프라인 + 운영자 화면 검증 (11단계, 60분)

## 로컬 기동 (Phase 1·2 완성본)

```bash
# 1) 환경변수
cp .env.example .env
# (선택) Phase 2 외부 API 키 — APP_CLOVA_OCR_*, APP_HYPERCLOVA_API_KEY 등.
# 키가 없어도 자동 파이프라인은 crowd_task placeholder 로 흘러 운영 가능.

# 2) 인프라 + 관제 + 로그 일괄 기동
#    PG / Redis / MinIO / Prometheus / Grafana / Loki / Promtail
make dev-up
make airflow-up    # Airflow 2.10 LocalExecutor (init → webserver → scheduler)
make worker-up     # Worker 5종 컨테이너 빌드+기동
                   #   (outbox / ocr / transform / price_fact / db_incremental / crawler)

# 3) DB 마이그레이션 (0001 ~ 0014 일괄 적용)
make db-migrate

# 4) 부트스트랩 admin 사용자 (Phase 1.2.11)
cd backend
uv run python ../scripts/seed_admin.py

# 5) Backend / Frontend 기동 (각 별도 터미널)
uv run uvicorn app.main:app --reload --port 8000
cd ../frontend && pnpm install && pnpm dev   # http://localhost:5173
```

### 기동 후 확인 URL

| 대상 | URL | 인증 |
|---|---|---|
| Backend OpenAPI | http://localhost:8000/docs | 없음 |
| Backend `/metrics` | http://localhost:8000/metrics | 없음 — 내부 scrape 전용 |
| Backend `/healthz`, `/readyz` | http://localhost:8000/healthz | 없음 |
| Web Portal | http://localhost:5173 | 로그인 (admin / admin) |
| Prometheus | http://localhost:9090 | 없음 |
| **Grafana — Core (Phase 1)** | http://localhost:3000/d/pipeline-hub-core | admin / admin |
| **Grafana — Runtime (Phase 2)** | http://localhost:3000/d/pipeline-hub-runtime | admin / admin |
| **Loki (Grafana Explore)** | http://localhost:3000/explore | admin / admin |
| Loki (직접) | http://localhost:3100/ready | 없음 — Promtail 만 |
| **Airflow** | http://localhost:8080 | airflow / airflow (`AIRFLOW_ADMIN_PASSWORD` 변경) |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| **Sentry** (DSN 설정 시) | `APP_SENTRY_DSN` 의 NCP Sentry 인스턴스 | 별도 SSO |

> 📸 Grafana 대시보드 스크린샷 자리 — 첫 데이터 적재 후 캡처 예정 (`docs/ops/MONITORING.md` 변경 이력 참조).

### Phase 1·2 동작 검증

| 단계 | 시나리오 | 시간 |
|---|---|---|
| Phase 1 | [`docs/dev/PHASE_1_E2E.md`](docs/dev/PHASE_1_E2E.md) — 수집 API + dedup + outbox + 관제 | ~30분 |
| Phase 2 | [`docs/dev/PHASE_2_E2E.md`](docs/dev/PHASE_2_E2E.md) — 자동 파이프라인(OCR→표준화→price_fact) + Crowd 큐 + DLQ replay + Loki/Sentry | ~60분 |

### 운영자 Web Portal 화면

로그인 후 좌측 Sidebar 메뉴:

| 메뉴 | 권한 | Phase | 용도 |
|---|---|---|---|
| 대시보드 | 전체 | 1.2.9 | 요약 메트릭 |
| 데이터 소스 | 전체 | 1.2.5 | 소스 등록/수정 |
| 수집 작업 | 전체 | 1.2.8 | ingest_job 이력 |
| 원천 데이터 | 전체 | 1.2.8 | raw_object 조회 + presigned 다운로드 |
| **검수 큐** | REVIEWER+ | 2.2.10 | crowd_task 상태 전이 (placeholder — Phase 4 정식) |
| **Dead Letter** | ADMIN | 2.2.10 | run.dead_letter replay 도구 |
| **Runtime 모니터** | 전체 | 2.2.10 | Grafana Runtime 대시보드 임베드 |
| 사용자 관리 | ADMIN | 1.2.4 | RBAC |

자세한 단계별 할 일은 [`docs/phases/PHASE_1_CORE.md`](docs/phases/PHASE_1_CORE.md), [`docs/phases/PHASE_2_RUNTIME.md`](docs/phases/PHASE_2_RUNTIME.md), 다음 단계는 [`docs/phases/PHASE_3_VISUAL_ETL.md`](docs/phases/PHASE_3_VISUAL_ETL.md).

## 폴더 구조

```
datapipeline/
├── CLAUDE.md                      # Claude 진입점
├── Makefile                       # dev-up / db-migrate / worker-up / airflow-up 등
├── docs/                          # 설계 문서 + ADR + 운영/개발 가이드
│   ├── adr/                       # 0001~0006 (드라이버 / Storage / Outbox / 트리거 / 표준화 / Crowd)
│   ├── ops/MONITORING.md          # Prometheus·Grafana·audit 운영 가이드
│   ├── airflow/INTEGRATION.md     # Airflow vs Dramatiq vs Visual ETL 책임 분담
│   └── dev/{PHASE_1_E2E,PHASE_2_E2E}.md  # 단계별 검증 시나리오
├── backend/                       # FastAPI + SQLAlchemy 2.0 + Alembic + Dramatiq
│   ├── app/api/v1/                # 라우터 (auth, sources, ingest, jobs, raw, crowd, dead_letters)
│   ├── app/domain/                # 도메인 로직 (ingest, ocr, standardization, transform,
│   │                              #   price_fact, crawl, db_incremental, idempotent_consume, outbox)
│   ├── app/core/                  # 미들웨어 (logging, metrics, access_log, request_context,
│   │                              #   sentry, events, event_topics)
│   ├── app/integrations/          # 외부 SDK 격리 (clova, upstage, hyperclova,
│   │                              #   object_storage, sourcedb, crawler, ocr)
│   ├── app/workers/               # Dramatiq actor 6종 + DLQ middleware + pipeline_actor
│   └── tests/                     # unit + integration (실 PG / Redis / MinIO)
├── frontend/                      # React 18 + Vite + Tailwind + shadcn-style + TanStack Query
│   └── src/pages/                 # Login/Dashboard/Sources/Jobs/RawObjects/Users
│                                  # + CrowdTaskQueue/DeadLetterQueue/RuntimeMonitor (Phase 2.2.10)
├── migrations/                    # Alembic 0001 ~ 0014
├── infra/
│   ├── docker-compose.yml         # PG / Redis / MinIO / Prometheus / Grafana / Loki / Promtail
│   │                              #   / Airflow init+webserver+scheduler / Worker 6종
│   ├── prometheus/prometheus.yml
│   ├── grafana/{provisioning,dashboards}/  # core.json (Phase 1) + runtime.json (Phase 2)
│   ├── loki/{config.yml,promtail.yml}
│   ├── airflow/{dags,plugins,requirements,logs}/
│   └── postgres/init/             # 첫 기동 시 1회 SQL (airflow DB 등)
├── scripts/                       # seed_admin.py (운영팀 합류 시 1회 실행)
└── tests/                         # 레포 전체 E2E (Phase 3~)
```

## 주요 기술 스택

- **Backend**: FastAPI + SQLAlchemy 2.0 + Alembic + Dramatiq
- **Frontend**: React 18 + Vite + Tailwind + React Flow
- **Orchestration**: Apache Airflow 2.9+ (Phase 2부터)
- **Infrastructure**: PostgreSQL 16, Redis 7, NCP Object Storage
- **배포**: Phase 1~3은 Docker Compose (단일 VM), Phase 4부터 NKS
- 자세한 스택 이유는 [`docs/01_TECH_STACK.md`](docs/01_TECH_STACK.md)

## 기여 규칙

- 커밋 메시지: **Conventional Commits** (`feat:`, `fix:`, `chore:`, `docs:` 등) — [`docs/05_CONVENTIONS.md`](docs/05_CONVENTIONS.md) 5.7
- 비밀/키 커밋 금지 — `.env.example` 만 commit
- DB 스키마 변경은 Alembic migration 파일로만 — 직접 ALTER 금지
- 새 Phase 체크박스 완료 시 해당 `docs/phases/PHASE_*.md` 에 `✅` 표시

## 라이선스

사내/비공개 프로젝트 (TBD).
