# ============================================================================
# Makefile — Phase 1 로컬 개발 편의 명령
# ----------------------------------------------------------------------------
# Windows: GNU Make 가 필요하다 (winget install GnuWin32.Make 또는 choco install make)
#          또는 WSL/Git Bash + make 패키지
# Mac/Linux: 기본 제공
#
# make 없이 쓰고 싶으면 각 타겟 안의 명령어를 그대로 복사해서 실행해도 된다.
# ============================================================================

.DEFAULT_GOAL := help
COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: help
help:
	@echo "사용 가능한 명령:"
	@echo "  make dev-up      - 로컬 인프라(PG/Redis/MinIO) 기동"
	@echo "  make dev-down    - 로컬 인프라 종료 (데이터 보존)"
	@echo "  make dev-reset   - 볼륨 포함 전부 삭제 후 재기동 (데이터 초기화)"
	@echo "  make dev-logs    - 실시간 로그"
	@echo "  make dev-ps      - 컨테이너 상태"
	@echo "  make dev-psql    - PostgreSQL shell"
	@echo "  make dev-redis   - Redis CLI"
	@echo "  make dev-minio   - MinIO Web Console 열기 안내"
	@echo ""
	@echo "DB 마이그레이션 (Phase 1.2.3+):"
	@echo "  make db-migrate     - 최신 head 까지 upgrade"
	@echo "  make db-downgrade   - 1단계 downgrade"
	@echo "  make db-current     - 현재 revision"
	@echo "  make db-history     - 전체 history"
	@echo "  make db-revision M='msg'  - 빈 revision 생성"
	@echo "  make db-reset       - 볼륨 초기화 + 재마이그레이션 (위험)"
	@echo ""
	@echo "Worker (Phase 2.2.1+):"
	@echo "  make worker-up      - worker-outbox 컨테이너 빌드+기동"
	@echo "  make worker-down    - worker-outbox 종료"
	@echo "  make worker-logs    - worker-outbox 실시간 로그"
	@echo "  make worker-local   - 로컬(uv)에서 dramatiq 직접 실행 (디버깅)"
	@echo ""
	@echo "Airflow (Phase 2.2.3+):"
	@echo "  make airflow-up       - airflow-init → webserver/scheduler 일괄 기동"
	@echo "  make airflow-down     - airflow 컨테이너만 종료 (volume 보존)"
	@echo "  make airflow-logs     - airflow 실시간 로그"
	@echo "  make airflow-dag-list - 등록된 DAG 목록"
	@echo "  make airflow-cli A='dags trigger system_hello_pipeline'  - 임의 CLI 실행"
	@echo ""
	@echo "처음이라면:"
	@echo "  1) cp .env.example .env"
	@echo "  2) make dev-up"
	@echo "  3) make db-migrate"

.env:
	@echo ""
	@echo "❌  .env 파일이 없습니다."
	@echo "   먼저 실행하세요:   cp .env.example .env"
	@echo ""
	@exit 1

.PHONY: dev-up
dev-up: .env
	$(COMPOSE) up -d
	@echo ""
	@echo "✅  기동 완료"
	@echo "   PostgreSQL :  localhost:5432  (user=app, db=datapipeline)"
	@echo "   Redis      :  localhost:6379"
	@echo "   MinIO API  :  http://localhost:9000"
	@echo "   MinIO UI   :  http://localhost:9001  (minioadmin / minioadmin)"

.PHONY: dev-down
dev-down:
	$(COMPOSE) down

.PHONY: dev-reset
dev-reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d
	@echo "✅  볼륨 초기화 + 재기동 완료"

.PHONY: dev-logs
dev-logs:
	$(COMPOSE) logs -f

.PHONY: dev-ps
dev-ps:
	$(COMPOSE) ps

.PHONY: dev-psql
dev-psql:
	$(COMPOSE) exec postgres psql -U app -d datapipeline

.PHONY: dev-redis
dev-redis:
	$(COMPOSE) exec redis redis-cli

.PHONY: dev-minio
dev-minio:
	@echo "MinIO Console: http://localhost:9001"
	@echo "Login: minioadmin / minioadmin"

# ============================================================================
# DB Migration (Alembic) — backend/ 에서 실행
# ============================================================================
# Phase 1.2.3 부터 사용. 운영(NKS)에서는 Helm pre-install Job 으로 동일하게 실행.
# 로컬: cp .env.example .env  →  make dev-up  →  make db-migrate

ALEMBIC := cd backend && python -m uv run --python /c/Users/fishlee/AppData/Local/Microsoft/WindowsApps/python.exe python -m alembic

.PHONY: db-migrate
db-migrate: .env
	$(ALEMBIC) upgrade head
	@echo "✅  마이그레이션 적용 완료"

.PHONY: db-downgrade
db-downgrade: .env
	$(ALEMBIC) downgrade -1
	@echo "↩️   1단계 롤백 완료"

.PHONY: db-current
db-current:
	$(ALEMBIC) current

.PHONY: db-history
db-history:
	$(ALEMBIC) history --verbose

.PHONY: db-revision
db-revision:
	@if [ -z "$(M)" ]; then echo "Usage: make db-revision M='메시지'"; exit 1; fi
	$(ALEMBIC) revision -m "$(M)"

.PHONY: db-reset
db-reset: dev-reset
	@sleep 5
	$(MAKE) db-migrate
	@echo "🔥  DB 초기화 + 마이그레이션 재적용 완료"

# ============================================================================
# Worker (Dramatiq) — Phase 2.2.1
# ============================================================================
# 로컬 개발 시 backend 는 호스트 uvicorn, worker 는 컨테이너 패턴.
# 코드 변경 후 반영하려면 `make worker-up` (build 포함).

DRAMATIQ_LOCAL := cd backend && python -m uv run --python /c/Users/fishlee/AppData/Local/Microsoft/WindowsApps/python.exe python -m dramatiq

.PHONY: worker-up
worker-up: .env
	$(COMPOSE) up -d --build worker-outbox
	@echo "✅  worker-outbox 기동"

.PHONY: worker-down
worker-down:
	$(COMPOSE) stop worker-outbox

.PHONY: worker-logs
worker-logs:
	$(COMPOSE) logs -f worker-outbox

.PHONY: worker-local
worker-local: .env
	$(DRAMATIQ_LOCAL) app.workers --processes 1 --threads 4

# ============================================================================
# Airflow (LocalExecutor) — Phase 2.2.3
# ============================================================================
# 별도 컨테이너 4종(airflow-init/webserver/scheduler) — postgres/redis 와 같은
# compose 스택. 메타DB = postgres/airflow (postgres init script 가 자동 생성).

.PHONY: airflow-up
airflow-up: .env
	$(COMPOSE) up -d airflow-init airflow-webserver airflow-scheduler
	@echo "✅  Airflow 기동 — http://localhost:$${AIRFLOW_HOST_PORT:-8080}  ($${AIRFLOW_ADMIN_USER:-airflow} / $${AIRFLOW_ADMIN_PASSWORD:-airflow})"

.PHONY: airflow-down
airflow-down:
	$(COMPOSE) stop airflow-webserver airflow-scheduler airflow-init

.PHONY: airflow-logs
airflow-logs:
	$(COMPOSE) logs -f airflow-webserver airflow-scheduler

.PHONY: airflow-dag-list
airflow-dag-list:
	$(COMPOSE) exec airflow-scheduler airflow dags list

# 임의 CLI: make airflow-cli A='dags trigger system_hello_pipeline'
.PHONY: airflow-cli
airflow-cli:
	@if [ -z "$(A)" ]; then echo "Usage: make airflow-cli A='dags list'"; exit 1; fi
	$(COMPOSE) exec airflow-scheduler airflow $(A)
