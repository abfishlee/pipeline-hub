# Unified Data Pipeline Platform (pipeline-hub)

농축산물 가격 데이터를 다채널에서 수집 → AI 표준코드로 정규화 → 외부 서비스에 제공하는 플랫폼.

**상태:** Phase 1 — Core Foundation **완료** (2026-04-25). Phase 2 — Pipeline Runtime 진입.

---

## 먼저 읽을 것

1. [`CLAUDE.md`](CLAUDE.md) — Claude 작업 원칙, 핵심 맥락
2. [`docs/README.md`](docs/README.md) — 전체 문서 목차
3. [`docs/phases/CURRENT.md`](docs/phases/CURRENT.md) — 현재 Phase / 타임라인
4. [`docs/dev/PHASE_1_E2E.md`](docs/dev/PHASE_1_E2E.md) — Phase 1 동작 검증 시나리오 (운영팀 9월 합류 시 가장 먼저 따라할 문서)

## 로컬 기동 (Phase 1 완성본)

```bash
# 1) 환경변수
cp .env.example .env

# 2) 인프라 + 관제 일괄 기동 (PG / Redis / MinIO / Prometheus / Grafana)
make dev-up
# 또는: docker compose -f infra/docker-compose.yml --env-file .env up -d

# 3) DB 마이그레이션
make db-migrate

# 4) Backend (FastAPI, 호스트 포트 8000)
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# 5) Frontend (Vite, 호스트 포트 5173)
cd ../frontend
pnpm install
pnpm dev
```

### 기동 후 확인 URL

| 대상 | URL | 인증 |
|---|---|---|
| Backend OpenAPI | http://localhost:8000/docs | 없음 (Phase 1) |
| Backend `/metrics` | http://localhost:8000/metrics | 없음 — 내부 scrape 전용 |
| Backend `/healthz`, `/readyz` | http://localhost:8000/healthz | 없음 |
| Web Portal | http://localhost:5173 | 로그인 (admin / admin) |
| Prometheus | http://localhost:9090 | 없음 |
| **Grafana 대시보드** | **http://localhost:3000** | **admin / admin** (`.env` 의 `GRAFANA_ADMIN_PASSWORD` 변경 권장) |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |

Grafana 진입 후 좌측 Dashboards → "Pipeline Hub — Core" 가 자동 프로비저닝되어 있다 (9 패널: 수집 QPS, dedup율, 24h 누적, p95 by path, 5xx rate, source × kind, outbox PENDING placeholder, DB pool).

> 📸 Grafana 대시보드 스크린샷 자리 — 첫 데이터 적재 후 캡처 예정 (`docs/ops/MONITORING.md` 7. 변경 이력에 함께 기록).

### 동작 검증 (E2E 10단계)

수집 API 가 정상 동작하고 dedup·outbox·메트릭이 끝까지 흐르는지 확인하려면 **[`docs/dev/PHASE_1_E2E.md`](docs/dev/PHASE_1_E2E.md)** 의 1~10 시나리오를 그대로 따라가면 된다.

자세한 단계별 할 일은 [`docs/phases/PHASE_1_CORE.md`](docs/phases/PHASE_1_CORE.md), 다음 단계는 [`docs/phases/PHASE_2_RUNTIME.md`](docs/phases/PHASE_2_RUNTIME.md).

## 폴더 구조

```
datapipeline/
├── CLAUDE.md                      # Claude 진입점
├── Makefile                       # make dev-up / db-migrate / test 등
├── docs/                          # 설계 문서 + ADR + 운영/개발 가이드
│   ├── adr/                       # 0001 PG 드라이버 듀얼 / 0002 Object Storage / 0003 Outbox+content_hash
│   ├── ops/MONITORING.md          # Prometheus·Grafana·audit 운영 가이드
│   └── dev/PHASE_1_E2E.md         # Phase 1 동작 검증 시나리오
├── backend/                       # FastAPI + SQLAlchemy 2.0 + Alembic
│   ├── app/api/v1/                # 라우터 (auth, sources, ingest, jobs, raw)
│   ├── app/domain/                # 도메인 로직 (ingest, sources, ...)
│   ├── app/core/                  # 미들웨어 (logging, metrics, access_log, request_context)
│   ├── app/integrations/          # 외부 SDK 격리 (Phase 2: clova, upstage)
│   └── tests/                     # unit + integration (실 PG 90+/MinIO 15+)
├── frontend/                      # React 18 + Vite + Tailwind + shadcn-style
├── migrations/                    # Alembic
├── infra/
│   ├── docker-compose.yml         # PG / Redis / MinIO / Prometheus / Grafana
│   ├── prometheus/prometheus.yml
│   └── grafana/{provisioning,dashboards}/
├── scripts/                       # 운영/시드 스크립트
└── tests/                         # 레포 전체 E2E (Phase 2~)
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
