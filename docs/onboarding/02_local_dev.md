# 2. 로컬 / 회사서버 실행

## 사전 요구사항
- Docker Desktop (또는 colima/podman)
- Python 3.12+
- Node.js 20+ (frontend)
- `uv` (`pip install uv` 또는 `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## 첫 실행 (clean state)

### 1. clone + 환경
```bash
git clone https://github.com/<your-org>/pipeline-hub.git
cd pipeline-hub
cp backend/.env.example backend/.env
# .env 의 비밀값 (CLOVA_OCR_SECRET 등) 편집
```

### 2. docker-compose (DB / Redis / pgvector)
```bash
docker compose -f infra/docker-compose.dev.yml up -d
# 또는 회사서버:
docker compose -f infra/docker-compose.staging.yml up -d
```

`postgres` 컨테이너가 healthy 까지 대기 (~10초).

### 3. backend 의존성 + DB migration
```bash
cd backend
uv sync
uv run alembic upgrade head      # 0045 까지 적용 (Phase 5.2.8)
```

migration 실패 시 `infra/scripts/seed_roles.sql` 가 먼저 적용됐는지 확인.

### 4. 도메인 yaml seed
```bash
uv run python scripts/seed_domain.py domains/agri.yaml
uv run python scripts/seed_domain.py domains/pos.yaml      # Phase 5.2.6 부터
```

### 5. backend / worker / frontend 실행
```bash
# 터미널 1 — backend
cd backend && uv run uvicorn app.main:app --reload --port 8000

# 터미널 2 — worker
cd backend && uv run dramatiq app.workers --processes 1 --threads 4

# 터미널 3 — frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

### 6. 동작 확인
- API: http://localhost:8000/docs (개발 중에만 활성)
- Public API: http://localhost:8000/public/docs
- Frontend: http://localhost:5173
- 첫 로그인: `it_admin` / `it-admin-pw-0425` (테스트 시드)

## 회사서버 (staging) 차이점

`docs/ops/UBUNTU_STAGING_DEPLOYMENT.md` 참고. 핵심:
- `.env` 의 `APP_ENV=staging` + `DATABASE_URL` 가 회사 NCP Cloud DB.
- nginx + SSL 은 미리 설정되어 있음 (Phase 0).
- worker 는 systemd unit `pipeline-worker.service` 로 자동 start.

## 공통 명령

| 작업 | 명령 |
|---|---|
| 새 migration 생성 | `uv run alembic revision -m "phase5.x.y add foo"` |
| 통합 테스트 1개 | `uv run pytest tests/integration/test_step9_pos_domain.py -v` |
| 전체 테스트 + cov | `uv run pytest --cov=app --cov-report=term` |
| 타입 체크 | `uv run mypy app` |
| lint + format | `uv run ruff check --fix && uv run ruff format` |
| FE lint | `cd frontend && npm run lint && npm run typecheck` |
| FE 빌드 | `cd frontend && npm run build` |

## 트러블슈팅

| 증상 | 원인 | 조치 |
|---|---|---|
| `migration 0030 → 0031` 에서 spike 충돌 | 0030 spike 가 cleanup 안 됨 | `alembic downgrade 0029 && upgrade head` |
| `app_rw role 없음` | 시드 누락 | `psql -f infra/scripts/seed_roles.sql` |
| FE 의 `/v1/*` 가 CORS error | `APP_CORS_ORIGINS` 설정 | `.env` 에 `http://localhost:5173` 추가 |
| Redis 연결 실패 | docker-compose down 됨 | `docker compose ps` 확인 후 up |
| `pg_stat_statements` extension 없음 | dev DB | 무시 (Phase 5.2.8 의 baseline 측정은 SAVEPOINT 로 안전) |

## Phase 6 NKS 이관 시 차이

`docs/ops/NKS_DEPLOYMENT.md` 의 *cluster manifest* 적용 + GitOps (Argo CD).
docker-compose 와의 차이:
- 컨테이너 이미지를 NCP Container Registry 에 push.
- `Deployment` + `Service` + `Ingress` + `HPA` (CPU 기반 auto-scale).
- `Secret` 은 NCP Secret Manager 에서 sync.

→ Phase 4 합류 운영팀 6~7명이 이 단계를 주도.
