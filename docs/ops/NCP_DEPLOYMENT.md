# NCP Docker Compose 배포 가이드 (Phase 1~3 전용)

**대상:** Phase 1 MVP ~ Phase 3 말까지의 VM 단일 노드 배포.
**Phase 4부터는 NKS로 이관**한다 → `docs/ops/NKS_DEPLOYMENT.md` 참조.
**전제:** 로컬 Docker Compose 구성이 완성되어 있고, DB 마이그레이션이 완료된 상태.

**⚠️ 중요:** 이 문서의 내용은 운영팀 6~7명 합류 전까지만 유효. Phase 4 진입 시점에 이 문서의 VM 환경은 2주 병행 운영 후 폐기된다.

---

## 1. NCP 리소스 구성

### 1.1 최소 구성 (Phase 1~2)

| 리소스 | 스펙(가이드) | 용도 |
|---|---|---|
| **Server (Compact-g2)** | vCPU 2 / RAM 4GB 1대 | App + Worker + nginx + frontend 정적 |
| **Cloud DB for PostgreSQL** | vCPU 2 / RAM 4GB / SSD 100GB | 운영 DB |
| **Cloud DB for Redis** | 1GB Standalone | 큐/캐시 |
| **Object Storage** | 버킷 2개 (raw, archive) | 원천 파일 |
| **VPC + Subnet** | 1 VPC, public + private subnet | 네트워킹 |
| **ACG (보안그룹)** | App/DB/Redis 각각 분리 | 방화벽 |
| **Global Traffic Manager** | 헬스체크 + HTTPS | 도메인 + TLS |

### 1.2 확장 구성 (Phase 3~4)

| 리소스 | 스펙 | 용도 |
|---|---|---|
| Server #2 (Compact-g2) | | Worker 전담 |
| Server #3 (Compact-g2) | | nginx LB + frontend |
| Cloud DB PG | vCPU 4 / RAM 8GB / SSD 300GB | 읽기 replica 1대 추가 |
| NAT Gateway | | Outbound 통제 |
| Secret Manager | | 비밀 관리 |
| Container Registry | | Docker 이미지 |

---

## 2. 네트워크 구성

```
[Internet]
   │
   ├── Global Traffic Manager  (HTTPS)
   │
   ├── Public Subnet
   │     ├── Server #1 (nginx + app + worker)
   │     └── Server #2 (worker 전담, 필요시)
   │
   └── Private Subnet
         ├── Cloud DB PG (private IP only)
         ├── Cloud DB Redis (private IP only)
         └── Object Storage (endpoint)
```

**ACG 정책:**
- App → DB: TCP 5432 (app subnet → DB)
- App → Redis: TCP 6379
- Internet → nginx: 443 only (80은 80→443 리다이렉트)
- SSH: Bastion IP만

---

## 3. 계정/시크릿 관리

### 3.1 NCP Secret Manager 키

```
/prod/app/db/url              → postgresql+asyncpg://...
/prod/app/redis/url
/prod/app/jwt/secret
/prod/app/os/access_key
/prod/app/os/secret_key
/prod/app/os/bucket
/prod/app/clova_ocr/secret    (Phase 2)
/prod/app/hyperclova/secret   (Phase 2)
/prod/app/slack/webhook       (Phase 2)

# Airflow (Phase 2)
/prod/airflow/db_url                   → postgresql+psycopg2://airflow_user:***@.../airflow
/prod/airflow/fernet_key               → fernet key (Python: Fernet.generate_key())
/prod/airflow/webserver_secret
/prod/airflow/admin_user
/prod/airflow/admin_password
```

- 애플리케이션은 시작 시 Secret Manager에서 조회 → 환경변수 주입.
- 대안: NCP Server의 **Init Script** 로 `.env` 생성.

### 3.2 DB 계정

```sql
-- Airflow metadata 전용 (별도 DB 권장)
CREATE DATABASE airflow;
CREATE USER airflow_user WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE airflow TO airflow_user;

-- Migration 전용 (DDL 권한)
CREATE USER app_migrate WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE datapipeline TO app_migrate;

-- 일반 애플리케이션 (DML만)
CREATE USER app_rw WITH PASSWORD '...';
GRANT CONNECT ON DATABASE datapipeline TO app_rw;
GRANT USAGE ON SCHEMA ctl, raw, stg, run, dq, wf, audit TO app_rw;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ctl, raw, stg, run, dq, wf, audit TO app_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO app_rw;
-- mart 쓰기는 별도 계정
CREATE USER app_mart_write WITH PASSWORD '...';
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA mart TO app_mart_write;

-- 외부 Public API (읽기 전용 + RLS)
CREATE USER app_public WITH PASSWORD '...';
GRANT USAGE ON SCHEMA mart TO app_public;
GRANT SELECT ON SPECIFIC mart views TO app_public;
```

---

## 4. 빌드/배포 파이프라인

### 4.1 이미지 빌드 (GitHub Actions)

```yaml
# .github/workflows/build.yml (가이드)
on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Login NCP Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ secrets.NCR_ENDPOINT }}
          username: ${{ secrets.NCP_ACCESS_KEY }}
          password: ${{ secrets.NCP_SECRET_KEY }}
      - name: Build & push backend
        run: |
          docker build -t $NCR/backend:${{ github.sha }} backend/
          docker push $NCR/backend:${{ github.sha }}
      - name: Build & push frontend
        run: |
          docker build -t $NCR/frontend:${{ github.sha }} frontend/
          docker push $NCR/frontend:${{ github.sha }}
```

### 4.2 배포 스크립트 (`infra/scripts/deploy.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail
ENV=${1:-prod}
IMAGE_TAG=${2:-latest}

ssh app@${PROD_HOST} <<EOF
  cd /opt/datapipeline
  export IMAGE_TAG=${IMAGE_TAG}
  docker compose -f docker-compose.prod.yml pull
  docker compose -f docker-compose.prod.yml run --rm backend \
    alembic -c alembic.ini upgrade head
  docker compose -f docker-compose.prod.yml up -d
  docker system prune -f
EOF
```

**안전장치:**
- `alembic upgrade head` 실패 시 배포 중단.
- 배포 전 자동 백업 스냅샷 (NCP Cloud DB API).
- 배포 후 헬스체크 60초 지속 확인.

### 4.3 Rollback

```bash
./infra/scripts/deploy.sh prod <previous-sha>
# + 필요 시 alembic downgrade -1
```

---

## 5. docker-compose.prod.yml 골격

```yaml
version: '3.9'

x-common-env: &common-env
  APP_ENV: prod
  APP_DATABASE_URL: ${APP_DATABASE_URL}
  APP_REDIS_URL: ${APP_REDIS_URL}
  APP_OS_ENDPOINT: https://kr.object.ncloudstorage.com
  APP_OS_ACCESS_KEY: ${APP_OS_ACCESS_KEY}
  APP_OS_SECRET_KEY: ${APP_OS_SECRET_KEY}
  APP_OS_BUCKET: ${APP_OS_BUCKET}
  APP_OS_SCHEME: ncp
  APP_JWT_SECRET: ${APP_JWT_SECRET}
  APP_LOG_JSON: "true"

services:
  backend:
    image: ${NCR}/backend:${IMAGE_TAG}
    restart: unless-stopped
    environment: *common-env
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
    depends_on: [redis-local]   # Redis가 NCP 관리형이면 삭제

  worker-transform:
    image: ${NCR}/backend:${IMAGE_TAG}
    restart: unless-stopped
    environment: *common-env
    command: dramatiq app.workers --queues default transform --processes 2 --threads 4

  worker-ocr:
    image: ${NCR}/backend:${IMAGE_TAG}
    restart: unless-stopped
    environment: *common-env
    command: dramatiq app.workers --queues ocr --processes 2 --threads 2

  worker-crawler:
    image: ${NCR}/backend:${IMAGE_TAG}
    restart: unless-stopped
    environment: *common-env
    command: dramatiq app.workers --queues crawler --processes 1 --threads 2

  # --- Airflow (Phase 2부터) ---
  airflow-init:
    image: apache/airflow:2.9.3-python3.12
    environment: &airflow-env
      AIRFLOW__CORE__EXECUTOR: LocalExecutor
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: ${AIRFLOW_DB_URL}
      AIRFLOW__CORE__FERNET_KEY: ${AIRFLOW_FERNET_KEY}
      AIRFLOW__WEBSERVER__SECRET_KEY: ${AIRFLOW_WEBSERVER_SECRET}
      AIRFLOW__CORE__LOAD_EXAMPLES: "false"
      AIRFLOW__API__AUTH_BACKENDS: airflow.api.auth.backend.basic_auth
      <<: *common-env
    entrypoint: /bin/bash
    command:
      - -c
      - |
        airflow db upgrade
        airflow users create -r Admin -u ${AIRFLOW_ADMIN_USER} \
          -p ${AIRFLOW_ADMIN_PASSWORD} -e ${AIRFLOW_ADMIN_EMAIL} \
          -f admin -l admin || true
    volumes:
      - ./backend/airflow_dags:/opt/airflow/dags
      - airflow_logs:/opt/airflow/logs

  airflow-webserver:
    image: apache/airflow:2.9.3-python3.12
    restart: unless-stopped
    environment: *airflow-env
    command: webserver
    depends_on: [airflow-init]
    volumes:
      - ./backend/airflow_dags:/opt/airflow/dags
      - airflow_logs:/opt/airflow/logs
    # 외부 노출은 nginx 리버스 프록시로 `/airflow/` path 기반

  airflow-scheduler:
    image: apache/airflow:2.9.3-python3.12
    restart: unless-stopped
    environment: *airflow-env
    command: scheduler
    depends_on: [airflow-init]
    volumes:
      - ./backend/airflow_dags:/opt/airflow/dags
      - airflow_logs:/opt/airflow/logs

  airflow-worker:
    # LocalExecutor 사용 시 scheduler 내에서 실행되므로 이 서비스는 Phase 4 CeleryExecutor 전환 시 활성화
    image: apache/airflow:2.9.3-python3.12
    restart: unless-stopped
    environment: *airflow-env
    command: celery worker
    profiles: ["celery"]
    depends_on: [airflow-scheduler]
    volumes:
      - ./backend/airflow_dags:/opt/airflow/dags
      - airflow_logs:/opt/airflow/logs

  frontend:
    image: ${NCR}/frontend:${IMAGE_TAG}
    restart: unless-stopped

  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    volumes:
      - ./infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    ports:
      - "443:443"
      - "80:80"
    depends_on: [backend, frontend]

  prometheus:
    image: prom/prometheus:v2.54.0
    restart: unless-stopped
    volumes:
      - ./infra/prometheus/:/etc/prometheus/:ro
      - prometheus_data:/prometheus

  grafana:
    image: grafana/grafana:11.3.0
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
    volumes:
      - grafana_data:/var/lib/grafana
      - ./infra/grafana/:/etc/grafana/provisioning/:ro

volumes:
  prometheus_data:
  grafana_data:
  airflow_logs:
```

---

## 6. Object Storage 사용 (NCP)

- Endpoint: `https://kr.object.ncloudstorage.com` (또는 KRS-Standard)
- S3 호환 → boto3 그대로 사용 가능.
- 버킷 네이밍: `datapipeline-raw-prod`, `datapipeline-archive-prod`.
- 라이프사이클 정책 (콘솔 설정):
  - `raw/` prefix: 30일 → Cool (또는 Infrequent), 365일 → Archive, 13개월 후 삭제는 코드에서 명시적으로.
  - `archive/` prefix: 영구 Archive 등급.

boto3 설정:
```python
import boto3
s3 = boto3.client(
    "s3",
    aws_access_key_id=settings.os_access_key,
    aws_secret_access_key=settings.os_secret_key,
    endpoint_url="https://kr.object.ncloudstorage.com",
    region_name="kr-standard",
)
```

---

## 7. CLOVA OCR 연동 (Phase 2)

- NCP 콘솔 → AI·Application Service → CLOVA OCR → General/Receipt 서비스 활성화.
- API URL + Secret Key 발급.
- 요금: 페이지당 과금 → 월 예산 알람 설정 (NCP 알람).
- 일일 사용량 모니터링: `/ocr/usage` 자체 대시보드.

---

## 8. 백업/복구

### 8.1 DB

- NCP Cloud DB 자동 백업 활성화 (일 1회, 보존 7일).
- **추가 수동 덤프** (주 1회, Object Storage):
  ```
  pg_dump -Fc --no-owner ... | aws s3 cp - s3://backup-bucket/datapipeline-YYYY-MM-DD.dump
  ```
- WAL 기반 PITR (Cloud DB 설정).

### 8.2 Object Storage

- 버전 관리 활성화.
- 별도 리전 복제 검토 (Phase 4).

### 8.3 복구 테스트

- 분기 1회 복구 리허설 (임시 DB에 복원 → 샘플 쿼리 검증).

---

## 9. 관제 연동

- Prometheus `scrape_configs` 에 애플리케이션 `/metrics` 추가.
- NCP Cloud Insight 메트릭 → Grafana에 수동 연결 or NCP 자체 대시보드.
- 알람:
  - 수집 API 5xx > 1% (5분 rolling)
  - event_outbox PENDING > 1000 (5분)
  - Dramatiq DLQ row 증가
  - Disk > 80%
  - DB connection pool > 90%
- 알림 채널: Slack 우선, 이메일 보조.

---

## 10. 도메인/TLS

- 도메인: 운영자 대시보드 `ops.datapipeline.co.kr`, 외부 API `api.datapipeline.co.kr` (Phase 4).
- TLS:
  - 초기: Let's Encrypt (`certbot --nginx`)
  - 확장: NCP SSL 인증서 서비스
- HSTS 활성: `max-age=31536000; includeSubDomains`.

---

## 11. 비용 모니터링

- NCP Billing API 또는 콘솔에서 월별 추출.
- 예산 초과 알람: 100% 도달 시 Slack.
- 비용 drill-down 주요 항목:
  - Server (app + worker VM)
  - Cloud DB PG
  - Cloud DB Redis
  - Object Storage (용량 + 트래픽)
  - CLOVA OCR (사용량 기반)
  - 외부 임베딩 API (HyperCLOVA / OpenAI)

---

## 12. 최초 배포 체크리스트 (Phase 1 종료 시)

- [ ] NCP 계정 + VPC/Subnet/ACG 준비
- [ ] Cloud DB PG, Redis, Object Storage 프로비저닝
- [ ] DB 유저(app_migrate/app_rw) 생성 + 최소 권한 확인
- [ ] Container Registry 준비
- [ ] GitHub Actions 시크릿 등록
- [ ] 첫 이미지 빌드 & 배포
- [ ] alembic migration 적용 + seed 데이터
- [ ] TLS 인증서 설치
- [ ] 도메인 연결
- [ ] Grafana/Prometheus 접근 확인
- [ ] 백업 자동 스크립트 cron 등록
- [ ] 롤백 리허설 1회

---

## 13. 금지 사항

- SSH rootname/비밀번호 로그인 금지 (키 인증 only).
- DB 운영 비밀번호 코드 저장 금지.
- 운영 DB에 직접 쿼리로 DDL 수행 금지 — migration 파일 통해서만.
- NCP Object Storage 버킷을 public-read 로 설정 금지 (presigned URL 방식만).
