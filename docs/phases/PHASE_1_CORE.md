# Phase 1 — Core Foundation

**기간 목표:** **5주 (2026-04-25 ~ 2026-05-30)** — 원래 6~8주에서 압축. 2026-09-01 운영팀 합류 데드라인 역산.
**성공 기준 (DoD):** 10만 rows/일 수집을 안정적으로 받고, 원천을 유실 없이 보존하며, 운영자가 웹에서 수집 현황을 볼 수 있다. **컨테이너 이미지가 NKS Ready 8계명을 준수한다** (Phase 4 이관 대비).

Phase 1 이후에도 **설계가 뒤집히지 않는 기반**을 만드는 단계. 기능이 예쁘지 않아도 되지만, 인터페이스와 스키마는 견고해야 한다.

---

## 1.1 Phase 1 범위

**포함:**
- ✅ 레포 초기화, 폴더 구조, Docker Compose 로컬 환경
- ✅ PostgreSQL 스키마 생성 (`ctl`, `raw`, `stg`, `mart`, `run`, `audit` 만 Phase 1)
- ✅ Alembic migration 체계
- ✅ FastAPI 스켈레톤 + 헬스체크 + 구조 로깅
- ✅ 인증 (JWT, login/refresh)
- ✅ 데이터 소스 관리 CRUD
- ✅ 수집 API: `/v1/ingest/api/{source_code}`, `/v1/ingest/file/{source_code}`, `/v1/ingest/receipt`
- ✅ Object Storage 연동 (로컬 MinIO)
- ✅ content_hash + idempotency 중복 방지
- ✅ 기본 Web Portal: 대시보드 / 소스 관리 / 수집 잡 / 원천 조회
- ✅ 관제 기초: Prometheus `/metrics`, 수집/실패 카운터

**제외 (Phase 2~4로 이월):**
- ❌ Worker/DAG (수집 후 처리는 Phase 2)
- ❌ OCR, 크롤링, 표준화 (Phase 2)
- ❌ Visual ETL Designer (Phase 3)
- ❌ SQL Studio 집행 기능 (Phase 3, 조회만 Phase 1)
- ❌ Crowd, DQ 게이트, CDC (Phase 4)

---

## 1.2 작업 단위 체크리스트

### 1.2.1 레포 & 환경 [W1]

- [x] `git init` + `.gitignore` + `.editorconfig` ✅ 2026-04-25 (commit `7c9dbee`)
- [x] 최상위 구조 생성: `backend/`, `frontend/`, `migrations/`, `infra/`, `scripts/`, `tests/` ✅ 2026-04-25
- [x] `README.md` 최소 (빌드/기동 방법만) ✅ 2026-04-25
- [x] `.env.example` 작성 (아래 1.4 참고) ✅ 2026-04-25
- [x] `infra/docker-compose.yml` 에 postgres:16, redis:7, minio 정의 ✅ 2026-04-25 (minio-setup으로 버킷 자동 생성)
- [x] `make dev-up` / `make dev-down` 스크립트 ✅ 2026-04-25 (Makefile, .env 가드 포함)
- [x] CI 기본 (GitHub Actions): lint + test + typecheck ✅ 2026-04-25 (sanity + backend/frontend 조건부 job)

### 1.2.2 Backend 스켈레톤 [W1~W2]

- [x] `backend/pyproject.toml` (`fastapi`, `uvicorn[standard]`, `pydantic-settings`, `structlog`, `argon2-cffi`, `python-jose[cryptography]`, `httpx`, `prometheus-client`, `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`) ✅ 2026-04-25 — DB 드라이버(`sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pytest-postgresql`)는 1.2.3에서 추가
- [x] `backend/Dockerfile` — multi-stage + non-root + NKS Ready 8계명 준수 ✅ 2026-04-25
- [x] `backend/.dockerignore` ✅ 2026-04-25
- [x] `app/config.py` — Pydantic Settings (APP_ 프리픽스) ✅ 2026-04-25
- [x] `app/main.py` — FastAPI 인스턴스, 헬스체크 (`/healthz`, `/readyz`), CORS, 예외 핸들러, request_id 미들웨어, SIGTERM graceful shutdown(lifespan) ✅ 2026-04-25
- [x] `app/core/logging.py` — structlog JSON/Console 자동 전환 + request_id 병합 ✅ 2026-04-25
- [x] `app/core/request_context.py` — contextvars 기반 request_id 전파 ✅ 2026-04-25
- [x] `app/core/errors.py` — 도메인 예외 계층 (8종) ✅ 2026-04-25
- [x] `app/core/security.py` — JWT issue/verify, Argon2id 해시 ✅ 2026-04-25
- [x] `app/core/hashing.py` — content_hash (sha256) + idempotency 키 정규화 ✅ 2026-04-25
- [x] `app/deps.py` — DI 스텁 (Phase 1.2.3/1.2.4에서 DB/현재사용자 추가) ✅ 2026-04-25
- [x] `tests/test_health.py` — 5/5 passed (healthz/readyz/request-id 전파) ✅ 2026-04-25
- [x] 로컬 검증: ruff ✅ + ruff format ✅ + mypy strict ✅ + pytest 5/5 ✅ + uvicorn /healthz /readyz curl ✅ 2026-04-25
- [ ] SQLAlchemy async engine + session maker (`app/db/session.py`) — **Phase 1.2.3으로 이월**

### 1.2.3 DB & Migration [W2] ✅ 2026-04-25

- [x] **ADR-0001** PostgreSQL 드라이버 이중 채택 (asyncpg + psycopg3)
- [x] `app/db/session.py` — async engine + sessionmaker + ping + dispose (commit `3723c7b`)
- [x] `/readyz` DB ping + 503 on fail + `client_db_down` test fixture
- [x] `app/models/base.py` (DeclarativeBase + naming convention) + `app/models/__init__.py`
- [x] `backend/run.py` — Windows SelectorEventLoop launcher (psycopg async 호환)
- [x] `alembic init` → `migrations/` (repo root) (commit `b38727d`)
- [x] `alembic.ini` (backend/) + `env.py` async 패턴 + `app.config.get_settings()` URL 주입
- [x] `Makefile` `db-migrate / db-downgrade / db-current / db-history / db-revision / db-reset`
- [x] `0001_init_schemas` — 8 schemas + 3 extensions (commit `b38727d`)
- [x] `0002_ctl_tables` — `app_user`, `role`, `user_role`, `data_source`, `connector`, `api_key` (commit `1f82204`)
- [x] `0003_raw_tables` — `raw_object`(PARTITIONED + 4월), `content_hash_index`, `ocr_result`, `raw_web_page`, `db_snapshot` (commit `9377ac0`)
- [x] `0004_run_tables` — `ingest_job`, `event_outbox`, `processed_event`, `dead_letter` (commit `ea129c8`)
- [x] `0005_audit_tables` — `access_log`(PARTITIONED + 4월), `sql_execution_log`, `download_log` (commit `6954f3b`)
- [x] `0006_mart_tables` — `standard_code`(trigram+aliases gin), `retailer_master`, `seller_master`(POINT), `product_master`, `product_mapping`(trigram), `price_fact`(PARTITIONED+BRIN), `price_daily_agg`, `master_entity_history` (commit `02e0819`)
- [x] `0007_stg_tables` — `standard_record`, `price_observation`(미표준화 partial idx) (commit `a7cb4e0`)
- [x] `0008_seed_roles` — ADMIN/OPERATOR/REVIEWER/APPROVER/VIEWER 5종

**검증 (실 PG 16.13 컨테이너):**
- `alembic upgrade head` → 0008 (head)
- 31 tables across 6 schemas (ctl=6, raw=6, run=4, audit=4, mart=9, stg=2)
- `alembic downgrade base` + 재 `upgrade head` round-trip 통과 (재현 가능성 보장)
- ORM 모델 = migration 100% 정합 (target_metadata = Base.metadata)
- ruff/format/mypy strict/pytest 7/7 모두 통과 (20 source files)

### 1.2.4 인증 [W2~W3] ✅ 2026-04-25

- [x] `POST /v1/auth/login` — login_id + password → access/refresh token (timing attack 완화 더미 verify)
- [x] `POST /v1/auth/refresh` — refresh 토큰 → 신규 access+refresh (DB 에서 최신 roles 재조회)
- [x] `GET /v1/auth/me` — Bearer 토큰 → user + roles
- [x] `POST/GET/PATCH/DELETE /v1/users` (ADMIN 전용) + `POST/PUT /v1/users/{id}/roles` + `DELETE /v1/users/{id}/roles/{code}`
- [x] JWT claims: `sub=user_id`, `roles=[...]`, `typ=access|refresh`
- [x] RBAC 의존성: `require_roles("ADMIN", ...)` — set intersection
- [x] 통합 테스트 21건 전부 통과 (실 PG 대상):
  - 로그인 성공/실패/비활성/존재안함 (동일 401 메시지)
  - refresh 정상/access-with-refresh 거부/잘못된 토큰
  - /me 인증 누락/잘못된 scheme/만료/refresh 토큰 거부
  - ADMIN-only 가드 (VIEWER 가 /v1/users 접근 시 403)
  - 사용자 CRUD (생성/중복 409/조회/수정/소프트 삭제)
  - 역할 부여/교체/개별 삭제/존재 안하는 role 404

### 1.2.5 데이터 소스 관리 [W3] ✅ 2026-04-25

- [x] 스키마: `DataSourceCreate/Update/Out` (Pydantic v2 + StringConstraints + croniter validator)
- [x] `POST /v1/sources` — 생성 (ADMIN 전용)
- [x] `GET /v1/sources` — 목록 (limit/offset/source_type/is_active 필터, ADMIN 또는 OPERATOR)
- [x] `GET /v1/sources/{id}` (ADMIN 또는 OPERATOR)
- [x] `PATCH /v1/sources/{id}` — `model_dump(exclude_unset=True)` 부분 업데이트, source_code 는 immutable
- [x] `DELETE /v1/sources/{id}` (soft delete — `is_active=false`, FK 보호)
- [x] 정책: `source_code` regex `^[A-Z][A-Z0-9_]{2,63}$`, unique → 중복 시 409
- [x] `source_type` Literal 7종 (API/OCR/DB/CRAWLER/CROWD/RECEIPT/APP) → 위반 422
- [x] `schedule_cron` croniter 검증 (빈 문자열은 NULL 정규화) → 위반 422
- [x] 통합 테스트 20건 (실 PG):
  - 생성 (minimal/full/duplicate 409)
  - 검증 (소문자 422, 숫자 시작 422, 잘못된 type 422, 잘못된 cron 422, 빈 cron → null)
  - 조회 (by_id, 404, type 필터, is_active 필터)
  - 수정 (부분 업데이트, nullable clear)
  - soft delete
  - RBAC (OPERATOR list/get OK, create/update/delete 403, 인증 누락 401)

### 1.2.6 Object Storage 통합 [W3]

- [ ] `app/integrations/object_storage.py` — 추상 인터페이스 + MinIO/NCP OS 구현
  - `put(key, bytes, content_type) -> uri`
  - `presigned_put(key, expires_sec) -> url`
  - `presigned_get(key, expires_sec) -> url`
  - `object_uri(key) -> str` (형식: `nos://bucket/key`)
- [ ] 버킷 레이아웃: `raw/{source_code}/{YYYY}/{MM}/{DD}/{uuid}.{ext}`
- [ ] 크기 제한: API inline JSON ≤ 64KB, 초과 시 자동 Object Storage 저장
- [ ] 테스트: 업로드/다운로드 round-trip

### 1.2.7 수집 API [W4]

```
POST /v1/ingest/api/{source_code}
Content-Type: application/json
X-Idempotency-Key: <uuid>
X-Request-ID: <uuid, 옵션>
Body: { ... 소스별 JSON ... }
→ 201 { "raw_object_id": 123, "job_id": 10, "dedup": false }
```

- [ ] 요청 처리 순서:
  1. `source_code` 조회, 비활성이면 403
  2. Idempotency-Key 있으면 기존 조회 (`run.ingest_job`에서 key 기반)
  3. body 기준 `content_hash` 계산
  4. `raw.content_hash_index` 에서 중복 체크 → 중복이면 기존 raw_object_id 반환, `dedup=true`
  5. raw_object + content_hash_index + ingest_job + event_outbox insert (단일 트랜잭션)
  6. 응답
- [ ] `POST /v1/ingest/file/{source_code}` — multipart 파일 업로드, >1MB면 Object Storage 저장 후 raw_object.object_uri 기록
- [ ] `POST /v1/ingest/receipt` — 영수증 전용 (모바일/웹 업로드), 이미지 검증, 최대 10MB
- [ ] 감사 로그: 모든 수집 요청 `audit.access_log` 기록
- [ ] 메트릭: `ingest_requests_total{source,status}`, `ingest_dedup_total{source}`, `ingest_bytes_total{source}`
- [ ] 테스트: happy + 중복 + 비활성 소스 + idempotency 재시도 + 대용량 파일

### 1.2.8 작업/원천 조회 [W4~W5]

- [ ] `GET /v1/jobs?source_id=&status=&from=&to=` — 페이지네이션
- [ ] `GET /v1/jobs/{id}`
- [ ] `GET /v1/raw-objects?source_id=&from=&to=&status=` (최근 우선)
- [ ] `GET /v1/raw-objects/{id}?partition_date=` — payload 또는 presigned URL 반환
- [ ] RBAC: VIEWER 이상.
- [ ] 테스트.

### 1.2.9 Frontend 스켈레톤 [W4~W6]

- [ ] `frontend/` vite 초기화 + tailwind + shadcn/ui
- [ ] 레이아웃: 사이드바(한국어 메뉴) + 상단바 (유저 메뉴)
- [ ] 인증: 로그인 페이지, 토큰 저장 (httpOnly 쿠키 불가하면 메모리 + refresh flow)
- [ ] 페이지:
  - [ ] 대시보드 — 수집 건수(금일/누적), 실패율, 최근 오류 10건 (Recharts 간단 차트)
  - [ ] 소스 관리 — 목록/상세/생성/수정
  - [ ] 수집 작업 — 필터 + 페이지네이션
  - [ ] 원천 조회 — JSON prettified 표시, 파일은 presigned 다운로드 버튼
  - [ ] 사용자/권한 관리 — ADMIN 전용
- [ ] API 클라이언트: TanStack Query + 공통 에러 토스트
- [ ] 로그아웃 / 토큰 만료 시 자동 로그인 페이지 이동

### 1.2.10 관제 기초 [W6]

- [ ] `prometheus_client` 통합, `/metrics` 엔드포인트
- [ ] 커스텀 메트릭: ingest counter/histogram, DB pool 사용률, event_outbox backlog
- [ ] `infra/` Prometheus + Grafana compose 추가
- [ ] Grafana dashboard JSON 1장 (`infra/grafana/dashboards/core.json`): 수집 qps, p95 latency, 실패율, outbox backlog
- [ ] NCP 운영 이식성을 위해 모든 메트릭은 `scrape_configs`로 노출

### 1.2.11 문서화 & 마무리 [W7~W8]

- [ ] `docs/phases/PHASE_1_CORE.md` 체크박스 완료 기록
- [ ] `docs/phases/CURRENT.md` 를 `PHASE_2`로 전환
- [ ] ADR (`docs/adr/0001-async-sqlalchemy.md` 등) 핵심 결정 1~2건 기록
- [ ] Grafana 대시보드 스크린샷 README에 링크

---

## 1.3 샘플 시나리오 (E2E 확인)

Phase 1 종료 시 반드시 통과:

1. 사용자가 로그인한다.
2. 신규 소스 `EMART_OPEN_API` 를 등록한다 (type=API).
3. curl 로 `POST /v1/ingest/api/EMART_OPEN_API` 에 JSON 본문을 보낸다.
4. 같은 Idempotency-Key 로 다시 보내면 `dedup=true` 로 응답한다.
5. 다른 본문(다른 content_hash)으로 보내면 새 raw_object 생성.
6. 웹 UI의 "수집 작업" 페이지에 방금 요청이 나타난다.
7. "원천 조회" 에서 payload JSON을 확인한다.
8. 10MB 이미지 업로드 시 `object_uri`가 기록되고 presigned 다운로드로 확인 가능.
9. Grafana 대시보드에 수집 건수 증가 반영.
10. Prometheus `ingest_requests_total` 값 증가 확인.

---

## 1.4 `.env.example` (Phase 1)

```env
APP_ENV=local
APP_DEBUG=true
APP_BASE_URL=http://localhost:8000

# Auth
APP_JWT_SECRET=change-me-32-bytes-min-change-me-32-bytes
APP_JWT_ACCESS_TTL_MIN=60
APP_JWT_REFRESH_TTL_DAYS=14

# DB
APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/datapipeline

# Redis (Phase 2부터 사용하지만 docker-compose는 함께 올림)
APP_REDIS_URL=redis://localhost:6379/0

# Object Storage (MinIO 로컬)
APP_OS_ENDPOINT=http://localhost:9000
APP_OS_ACCESS_KEY=minioadmin
APP_OS_SECRET_KEY=minioadmin
APP_OS_BUCKET=datapipeline-raw
APP_OS_REGION=kr-standard
APP_OS_SCHEME=minio  # local=minio / prod=ncp

# CORS
APP_CORS_ORIGINS=http://localhost:5173

# 로깅
APP_LOG_LEVEL=INFO
APP_LOG_JSON=false  # 로컬은 pretty, 운영은 true
```

---

## 1.5 Phase 1 비기능 합격 기준

- [ ] 로컬에서 `docker compose up` 1회로 전 스택 기동 (< 30초).
- [ ] Cold start → healthz 200 응답: < 2초.
- [ ] 수집 API p95 < 200ms (inline JSON 10KB 기준, 로컬).
- [ ] 단일 트랜잭션 안에서 raw_object + outbox insert 보장 (테스트로 확인).
- [ ] 1,000 req 부하 테스트 시 에러율 0%, 평균 < 100ms (`scripts/loadtest_phase1.py` 제공).
- [ ] 로그가 JSON 구조화되고 request_id가 체인 전달된다.

---

## 1.6 Phase 1 → Phase 2 이관 조건

Phase 2 시작 전 반드시 충족:

1. `run.event_outbox` 에 수집 이벤트가 `PENDING` 상태로 정상 적재되고 있다.
2. 수집 raw_object 와 Object Storage 객체가 1:1 정합하고 있다 (리컨설 스크립트 `scripts/reconcile_raw.py` 제공).
3. 운영자용 UI가 최소한 동작한다 (눈으로 확인 가능).
4. 문서(`docs/`)가 실제 구현과 일치한다.
5. CI가 녹색이다.
