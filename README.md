# Unified Data Pipeline Platform (pipeline-hub)

농축산물 가격 데이터를 다채널에서 수집 → AI 표준코드로 정규화 → 외부 서비스에 제공하는 플랫폼.

**상태:** Phase 1 시작 (2026-04-25 ~ 2026-05-30 목표). 코드는 아직 없고 설계 문서만 존재.

---

## 먼저 읽을 것

1. [`CLAUDE.md`](CLAUDE.md) — Claude 작업 원칙, 핵심 맥락
2. [`docs/README.md`](docs/README.md) — 전체 문서 목차
3. [`docs/phases/CURRENT.md`](docs/phases/CURRENT.md) — 현재 Phase / 타임라인

## 로컬 기동 (Phase 1.2.2 이후 동작)

Phase 1.2.1(레포/환경)이 끝난 현재 시점에서는 아직 컨테이너가 없다. 1.2.2(Backend 스켈레톤) 완료 후부터 아래가 동작한다.

```bash
# 환경변수
cp .env.example .env    # (1.2.2에서 .env.example 생성 예정)

# 인프라 (PostgreSQL / Redis / MinIO)
docker compose -f infra/docker-compose.yml up -d

# Backend (FastAPI)
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Frontend (Vite)
cd frontend
pnpm install
pnpm dev
```

자세한 단계별 할 일은 [`docs/phases/PHASE_1_CORE.md`](docs/phases/PHASE_1_CORE.md).

## 폴더 구조

```
datapipeline/
├── CLAUDE.md              # Claude 진입점
├── docs/                  # 설계 문서
├── backend/               # FastAPI 애플리케이션 (Phase 1.2.2~)
├── frontend/              # React + Vite (Phase 1.2.9~)
├── migrations/            # Alembic (Phase 1.2.3~)
├── infra/                 # docker-compose / IaC
├── scripts/               # 운영/시드 스크립트
└── tests/                 # 레포 전체 E2E
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
