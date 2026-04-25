# Ubuntu 회사 서버 — Staging 배포 가이드

**목적:** Phase 1~3 완성본을 회사 Ubuntu 서버(고정 IP)에 띄워 외부 데모용 staging 으로
운영. 최종 NCP NKS 이관 전 1회성 단계.

**전제 조건:**
- 회사 서버 SSH 접근 가능 (Ubuntu 22.04 / 24.04 LTS)
- 고정 IP 할당 + 80/443 또는 임의 포트 외부 개방
- root 또는 sudo 권한 사용자

이 가이드는 운영자가 SSH 접속 후 그대로 따라하면 되도록 구성. 모든 명령은 서버 측에서
실행.

---

## 1. 사전 준비

### 1.1 시스템 패키지 + Docker

```bash
# Ubuntu 23.10+ 의 경우 docker 가 이미 있을 수 있음 — 확인.
docker --version 2>/dev/null || true

# 없으면 공식 스크립트로 설치
sudo apt-get update
sudo apt-get install -y curl git

curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sudo sh /tmp/get-docker.sh

# 현재 사용자가 sudo 없이 docker 명령 가능하게.
sudo usermod -aG docker $USER
newgrp docker  # or 새 SSH 세션 재로그인.

docker compose version  # v2 확인
```

### 1.2 방화벽 (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp     # 또는 외부 데모용 임의 포트 (예: 8080)
sudo ufw allow 443/tcp    # SSL 사용 시
# sudo ufw allow 5173/tcp  # vite dev — staging 에선 권장 안 함, build 후 nginx 서빙
sudo ufw enable
sudo ufw status
```

### 1.3 작업 디렉토리

```bash
sudo mkdir -p /opt/datapipeline
sudo chown $USER:$USER /opt/datapipeline
cd /opt/datapipeline
```

---

## 2. 코드 + 설정 가져오기

### 2.1 git clone

```bash
cd /opt/datapipeline
git clone https://github.com/abfishlee/pipeline-hub.git .
git checkout main
```

### 2.2 .env 작성

`.env.example` 을 복사해 staging 용으로 수정. 절대 git 에 commit 금지.

```bash
cp .env.example .env
nano .env   # 또는 vim
```

`.env` 에서 **반드시 변경할 값**:

```env
# 서버 식별
APP_ENV=staging
APP_DEBUG=false

# 강력한 password 로 변경 (≥16자 random)
POSTGRES_PASSWORD=<RANDOM_STRONG>
REDIS_PASSWORD=<RANDOM_STRONG>           # 사용 중인 경우

# 서비스간 시크릿
APP_JWT_SECRET=<RANDOM_64BYTE>           # python -c "import secrets; print(secrets.token_hex(32))"

# Object Storage (MinIO 로컬 또는 NCP Object Storage)
OS_ENDPOINT=http://127.0.0.1:9000        # 로컬 MinIO 사용 시
OS_ACCESS_KEY=minioadmin
OS_SECRET_KEY=<RANDOM_STRONG>
OS_BUCKET=datapipeline-staging

# CORS — frontend 도메인 추가
APP_CORS_ORIGINS=http://<고정IP>,https://<도메인>

# 외부 노출 포트
POSTGRES_HOST_PORT=5434                  # 외부 노출 안 하려면 주석 처리
REDIS_HOST_PORT=6380                     # 동일
```

`.env` 파일 권한 잠그기:

```bash
chmod 600 .env
```

### 2.3 frontend production build

vite dev 서버 대신 build 한 정적 파일을 nginx 가 서빙하는 방식.

```bash
# Node.js 20+ 설치 (없으면)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# pnpm
sudo npm install -g pnpm@9

# 빌드
cd /opt/datapipeline/frontend
pnpm install --frozen-lockfile
BACKEND_URL=http://127.0.0.1:8000 pnpm build
# → dist/ 디렉토리 생성
```

---

## 3. 인프라 기동 (Docker Compose)

### 3.1 PG + Redis + MinIO

```bash
cd /opt/datapipeline
docker compose -f infra/docker-compose.yml --env-file .env up -d postgres redis minio
docker compose -f infra/docker-compose.yml --env-file .env ps
```

### 3.2 마이그레이션

```bash
cd /opt/datapipeline/backend

# venv 만들기 (Python 3.12+)
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .

# Alembic 마이그레이션 0001~0020 적용
alembic upgrade head

# admin 사용자 시드
PYTHONPATH=. python ../scripts/seed_admin.py \
  --login_id admin \
  --password '<STRONG_PASSWORD>' \
  --email admin@yourcompany.com

# (선택) admin 의 ADMIN role 매핑 — seed_admin 스크립트가 ctl.app_user_role 컬럼명을
# 잘못 참조해 실패하면 직접 수동 처리:
docker exec -it dp_postgres psql -U app -d datapipeline -c \
  "INSERT INTO ctl.user_role (user_id, role_id) \
   SELECT u.user_id, r.role_id \
     FROM ctl.app_user u, ctl.role r \
    WHERE u.login_id = 'admin' AND r.role_code = 'ADMIN' \
   ON CONFLICT DO NOTHING;"

# 샘플 데이터 시드 (선택)
PYTHONPATH=. python ../scripts/seed_default_pipelines.py
PYTHONPATH=. python ../scripts/seed_sql_templates.py
```

---

## 4. Backend 운영 모드 기동

`run.py` 는 dev 용 (reload=True). staging 은 `gunicorn + uvicorn workers` 추천.

### 4.1 systemd 서비스 등록

```bash
sudo nano /etc/systemd/system/datapipeline-backend.service
```

```ini
[Unit]
Description=Datapipeline FastAPI backend
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=<운영자>
WorkingDirectory=/opt/datapipeline/backend
EnvironmentFile=/opt/datapipeline/.env
ExecStart=/opt/datapipeline/backend/.venv/bin/python -m uvicorn \
    app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2 \
    --timeout-graceful-shutdown 10 \
    --log-level info
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now datapipeline-backend
sudo systemctl status datapipeline-backend
journalctl -u datapipeline-backend -f   # 로그 라이브 추적
```

### 4.2 헬스체크

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status":"ok"}

curl -s http://127.0.0.1:8000/readyz | jq .
# {"status":"ready", "checks": {"app":"ok","db":"ok","object_storage":"ok"}}
```

---

## 5. Nginx 리버스 프록시

frontend 정적 파일 + `/v1/*` API 경로를 backend 로 프록시.

### 5.1 nginx 설치 + 설정

```bash
sudo apt-get install -y nginx
sudo nano /etc/nginx/sites-available/datapipeline
```

```nginx
server {
    listen 80 default_server;
    server_name <고정IP> <도메인>;     # 도메인 없으면 IP만

    # 정적 파일 (frontend build)
    root /opt/datapipeline/frontend/dist;
    index index.html;

    # SPA fallback — React Router 의 client-side 경로 지원
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 프록시
    location /v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 지원 (PipelineRunDetail 의 실시간 노드 상태)
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }

    # /healthz 등 메타 엔드포인트도 프록시 (선택)
    location ~ ^/(healthz|readyz|metrics) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    # gzip
    gzip on;
    gzip_types text/css application/javascript application/json;
    gzip_min_length 1k;

    # 보안 헤더 (기본)
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 클라이언트 업로드 한도 (영수증 OCR 10MB)
    client_max_body_size 12M;
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/datapipeline /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 5.2 (선택) Let's Encrypt SSL — 도메인이 있을 때

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <도메인> -m admin@yourcompany.com --agree-tos -n
# 자동 갱신 cron 자동 등록됨.
```

---

## 6. 첫 접속 검증

### 6.1 외부 접속

```bash
# 외부 클라이언트에서:
curl -I http://<고정IP>/
# HTTP/1.1 200 OK
```

브라우저로 `http://<고정IP>/` 진입 → 로그인 화면 → admin / `<STRONG_PASSWORD>` 로 로그인.

### 6.2 메뉴 동작 확인

| 메뉴 | 검증 |
|---|---|
| 대시보드 | 로딩 정상 |
| 데이터 소스 | 비어 있음 (시드 안 했으면) |
| Visual ETL Designer | drag-and-drop 동작 |
| 배포 이력 | seed_default_pipelines 실행했으면 3개 |
| SQL Studio | seed_sql_templates 실행했으면 12개 |
| Runtime 모니터 | 프로메테우스 메트릭 정상 |

---

## 7. 운영 명령어 모음

```bash
# 서비스 관리
sudo systemctl restart datapipeline-backend
sudo systemctl reload nginx
docker compose -f infra/docker-compose.yml --env-file .env restart postgres

# 로그 보기
journalctl -u datapipeline-backend -n 200 --no-pager
docker compose -f infra/docker-compose.yml --env-file .env logs -f --tail 100

# 마이그레이션 (코드 git pull 후)
cd /opt/datapipeline
git pull
cd backend
source .venv/bin/activate
alembic upgrade head
sudo systemctl restart datapipeline-backend

# 프런트 빌드 갱신 (코드 변경 후)
cd /opt/datapipeline/frontend
pnpm install --frozen-lockfile
BACKEND_URL=http://127.0.0.1:8000 pnpm build
# nginx 는 reload 불필요 — 정적 파일 즉시 반영

# admin 비밀번호 변경
docker exec -it dp_postgres psql -U app -d datapipeline
# 또는 임시로 seed_admin --login_id admin --password '<NEW>' 재실행
```

---

## 8. 외부 데모 시 체크리스트

데모 직전:

- [ ] `/readyz` 200 확인
- [ ] admin 비밀번호 데모용으로 안전한 것 (이력서/포트폴리오에 절대 노출 금지)
- [ ] 시드 데이터 (3 pipelines + 12 SQL templates) 적재 확인
- [ ] HTTPS (도메인 있을 때) — 데모 URL 은 항상 `https://`
- [ ] CORS — 데모 도메인이 `APP_CORS_ORIGINS` 에 포함
- [ ] 방화벽 — 80/443 만 외부 개방, 5434/6380/9000 등은 절대 외부 노출 금지

---

## 9. NCP 이관 시 변경 사항 (Phase 4 진입 시)

본 staging 은 NCP NKS 이관 전 임시. NCP 이관 시 다음이 변경:

- Docker Compose → NKS Helm Chart (`infra/k8s/helm/datapipeline/`)
- 자체 PG → NCP Cloud DB for PostgreSQL (managed)
- 자체 Redis → NCP Cloud DB for Redis
- MinIO → NCP Object Storage
- nginx → NCP Load Balancer + ingress-nginx
- systemd → Kubernetes Deployment
- `.env` → NCP Secret Manager + ExternalSecrets Operator

상세 계획은 `docs/ops/NKS_DEPLOYMENT.md` + `docs/phases/PHASE_4_ENTERPRISE.md` 4.2.8b
참조.

---

## 부록 A — 트러블슈팅

### admin 로그인 401

- `ctl.user_role` 에 ADMIN role 매핑 누락. 5.2 의 수동 INSERT 다시.

### `/readyz` `db: fail`

- PG 컨테이너 헬스체크 실패. `docker logs dp_postgres` 확인.
- `.env` 의 `APP_DATABASE_URL` 이 호스트/포트 일치하는지 확인.

### 마이그레이션 `extension "vector" is not available`

- `infra/docker-compose.yml` 의 PG 이미지가 `pgvector/pgvector:pg16` 인지 확인.
- 아니라면 컨테이너 + 볼륨 삭제 후 재기동:
  ```bash
  docker compose down postgres
  docker volume rm datapipeline-dev_postgres_data
  docker compose up -d postgres
  alembic upgrade head
  ```

### nginx 502 Bad Gateway

- `systemctl status datapipeline-backend` — backend 가 안 떠 있음. `journalctl -u
  datapipeline-backend -n 200` 으로 확인.
- backend 가 떠 있으면 `curl http://127.0.0.1:8000/healthz` 직접 시도.
