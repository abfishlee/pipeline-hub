#!/usr/bin/env bash
# ============================================================================
# Pipeline Hub — Staging Bootstrap (Ubuntu 24.04 / D-1 all-in-one / HTTP only)
#
# 사용자 답변 기반 (2026-04-27):
#   - 회사 서버: fishnoon@172.30.1.131 (Ubuntu 24.04, 4vCPU/16GB/468GB)
#   - SSL: A — 사내망 only, http://172.30.1.131:8080
#   - DB: D-1 — docker PG/Redis/MinIO (NCP managed 안 씀)
#   - 외부: internal_only
#   - admin: admin / fishnoon@example.com
#   - 외부 API: 전부 mock
#
# 한 줄 실행 (서버 SSH 후):
#   curl -fsSL https://raw.githubusercontent.com/abfishlee/pipeline-hub/feature/v2-generic-platform/scripts/staging_bootstrap.sh -o /tmp/bootstrap.sh
#   bash /tmp/bootstrap.sh
#
# 또는 사용자가 직접 clone 한 상태라면:
#   cd /opt/datapipeline && bash scripts/staging_bootstrap.sh
#
# 스크립트는 *멱등* — 여러 번 실행해도 안전. 실패 지점부터 재시작 가능.
# ============================================================================

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-/opt/datapipeline}"
GIT_REPO="${GIT_REPO:-https://github.com/abfishlee/pipeline-hub.git}"
GIT_BRANCH="${GIT_BRANCH:-feature/v2-generic-platform}"
COMPOSE_FILE="infra/docker-compose.staging.yml"
ENV_FILE=".env.staging"

# 호스트 IP (출력용 — 변경 X).
HOST_IP="${HOST_IP:-172.30.1.131}"

color() { printf "\033[%sm%s\033[0m" "$1" "$2"; }
log()   { printf "%s %s\n" "$(color 36 "[bootstrap]")" "$1"; }
warn()  { printf "%s %s\n" "$(color 33 "[warn]")"      "$1" >&2; }
fail()  { printf "%s %s\n" "$(color 31 "[fail]")"      "$1" >&2; exit 1; }

# ──────────────────────────────────────────────────────────────────────────────
# 0. 사전 검증
# ──────────────────────────────────────────────────────────────────────────────
log "0. 사전 검증"

[ "$(id -u)" -ne 0 ] || fail "root 로 실행 금지. 일반 사용자 + sudo 사용."

if [ ! -f /etc/os-release ]; then
  fail "/etc/os-release 가 없음 — Ubuntu 가 아닌 OS"
fi
. /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then
  warn "Ubuntu 가 아님 (ID=${ID:-unknown}) — 스크립트 일부가 실패할 수 있음"
fi

# sudo 1회 캐시 (이후 명령 자동 갱신).
log "sudo 권한 확인 (password 입력 필요할 수 있음)"
sudo -v || fail "sudo 권한 없음"
# 백그라운드로 sudo 캐시 갱신 (5분 timeout 회피).
( while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null ) &
SUDO_KEEPALIVE_PID=$!
trap "kill $SUDO_KEEPALIVE_PID 2>/dev/null || true" EXIT

# ──────────────────────────────────────────────────────────────────────────────
# 1. 시스템 패키지 + Docker
# ──────────────────────────────────────────────────────────────────────────────
log "1. 시스템 패키지 + Docker 설치"

if ! command -v docker >/dev/null 2>&1; then
  log "  Docker 미설치 → 설치 중"
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    ca-certificates curl gnupg git make jq openssl
  # Docker 공식 repo (Ubuntu 24.04 noble 지원).
  sudo install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  ARCH=$(dpkg --print-architecture)
  CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME}")
  echo \
    "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  log "  Docker 이미 설치됨: $(docker --version)"
fi

# 사용자 docker group 추가 (재로그인 시 적용 — 본 세션은 sudo docker 로 진행).
if ! id -nG "$USER" | grep -qw docker; then
  log "  $USER 를 docker group 에 추가 (재로그인 후 sudo 없이 docker 사용 가능)"
  sudo usermod -aG docker "$USER"
fi

# Docker daemon 기동.
sudo systemctl enable --now docker

# 본 세션은 docker group 적용 안 됐을 수 있어 sudo 사용.
DOCKER="sudo docker"
COMPOSE="sudo docker compose"

# ──────────────────────────────────────────────────────────────────────────────
# 2. 작업 디렉토리 + git clone
# ──────────────────────────────────────────────────────────────────────────────
log "2. 작업 디렉토리 + git clone"

if [ ! -d "$INSTALL_DIR" ]; then
  sudo mkdir -p "$INSTALL_DIR"
  sudo chown "$USER:$USER" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [ -d .git ]; then
  log "  기존 repo 발견 → fetch + checkout $GIT_BRANCH"
  git fetch origin "$GIT_BRANCH"
  git checkout "$GIT_BRANCH"
  git pull --ff-only origin "$GIT_BRANCH"
else
  log "  clone $GIT_REPO ($GIT_BRANCH)"
  git clone --branch "$GIT_BRANCH" "$GIT_REPO" .
fi

# ──────────────────────────────────────────────────────────────────────────────
# 3. .env.staging 생성 (비밀값 자동 — 이미 있으면 그대로 사용)
# ──────────────────────────────────────────────────────────────────────────────
log "3. .env.staging 생성"

ADMIN_PASSWORD_GENERATED=""

if [ -f "$ENV_FILE" ]; then
  log "  $ENV_FILE 이미 존재 → 그대로 사용"
else
  log "  $ENV_FILE 신규 생성 (랜덤 비밀값 채움)"
  cp infra/staging.env.example "$ENV_FILE"

  # 랜덤 비밀값 생성.
  rand32() { openssl rand -hex 16; }
  rand64() { openssl rand -hex 32; }
  rand24() {
    # alphanumeric only — admin password (UI 입력 친화적).
    LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24
  }

  POSTGRES_PASSWORD=$(rand32)
  MINIO_ROOT_PASSWORD=$(rand32)
  APP_JWT_SECRET=$(rand64)
  ADMIN_PASSWORD=$(rand24)
  ADMIN_PASSWORD_GENERATED="$ADMIN_PASSWORD"

  # 줄 추가 (env example 의 주석된 #VAR= 자리에).
  cat >> "$ENV_FILE" <<EOF

# ── 자동 생성 비밀값 ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ──
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
APP_JWT_SECRET=${APP_JWT_SECRET}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
EOF

  chmod 600 "$ENV_FILE"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 4. 방화벽 (UFW) — 외부 인터넷 노출 안 함, 사내망 8080 만 개방
# ──────────────────────────────────────────────────────────────────────────────
log "4. UFW 방화벽 설정 (사내망 only)"

if command -v ufw >/dev/null 2>&1; then
  sudo ufw status verbose | head -3 || true
  # SSH (22) 는 항상 허용.
  sudo ufw allow OpenSSH 2>/dev/null || true
  # 사내망 only — 회사 LAN (172.30.0.0/16 또는 더 좁게) 에서만 8080.
  # 외부 인터넷 노출 안 함.
  sudo ufw allow from 172.30.0.0/16 to any port 8080 proto tcp comment 'pipeline-hub frontend' || true
  sudo ufw allow from 172.30.0.0/16 to any port 8000 proto tcp comment 'pipeline-hub backend (debug)' || true
  sudo ufw allow from 172.30.0.0/16 to any port 9001 proto tcp comment 'pipeline-hub minio console' || true
  # ufw enable 은 *사용자 승인* 후 실행 — SSH 끊기지 않도록.
  if ! sudo ufw status | grep -q "Status: active"; then
    warn "  ufw 가 비활성 상태. 활성화 시 SSH 끊길 위험 → 수동 활성화 권장:"
    warn "    sudo ufw enable"
  fi
else
  warn "  ufw 미설치 — 회사 사내 방화벽으로 대체"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 5. Docker Compose 빌드 + 기동
# ──────────────────────────────────────────────────────────────────────────────
log "5. Docker Compose 빌드 (5~15분 소요)"

$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build

log "  PG / Redis / MinIO 먼저 기동 → migration 실행"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d postgres redis minio
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up minio-setup
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm migrate

log "  backend / worker / frontend 기동"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d backend worker frontend

# ──────────────────────────────────────────────────────────────────────────────
# 6. Health check
# ──────────────────────────────────────────────────────────────────────────────
log "6. Health check"

sleep 10
log "  컨테이너 상태:"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

# Backend healthz.
backend_ok=0
for i in 1 2 3 4 5 6; do
  if curl -fsS "http://127.0.0.1:8000/healthz" >/dev/null 2>&1; then
    backend_ok=1
    break
  fi
  sleep 5
done

# Frontend healthz.
frontend_ok=0
for i in 1 2 3 4 5 6; do
  if curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
    frontend_ok=1
    break
  fi
  sleep 5
done

# ──────────────────────────────────────────────────────────────────────────────
# 7. 결과 보고
# ──────────────────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════════════════"
echo " Pipeline Hub Staging — 배포 결과"
echo "════════════════════════════════════════════════════════════════════════════"
echo

if [ "$backend_ok" = "1" ]; then
  echo "  ✅ backend  http://${HOST_IP}:8000/healthz       → OK"
else
  echo "  ⚠  backend  http://${HOST_IP}:8000/healthz       → 응답 없음 (로그 확인 필요)"
fi
if [ "$frontend_ok" = "1" ]; then
  echo "  ✅ frontend http://${HOST_IP}:8080/healthz       → OK"
else
  echo "  ⚠  frontend http://${HOST_IP}:8080/healthz       → 응답 없음"
fi

echo
echo "  📌 사용자 진입 URL:"
echo "      http://${HOST_IP}:8080         ← Frontend (메인)"
echo "      http://${HOST_IP}:8000/docs    ← Backend OpenAPI (개발용)"
echo "      http://${HOST_IP}:9001         ← MinIO Console (관리자)"
echo

if [ -n "$ADMIN_PASSWORD_GENERATED" ]; then
  echo "════════════════════════════════════════════════════════════════════════════"
  echo " ⚠  최초 ADMIN 계정 — 이 값은 이후 *다시 표시 안 됨*. 안전한 곳에 보관."
  echo "════════════════════════════════════════════════════════════════════════════"
  echo "    login_id : admin"
  echo "    password : ${ADMIN_PASSWORD_GENERATED}"
  echo "    email    : fishnoon@example.com"
  echo "════════════════════════════════════════════════════════════════════════════"
  echo
  echo " ${ENV_FILE} 에도 평문으로 저장되어 있음 (chmod 600) → 운영 후 비밀번호 변경 권장."
fi

echo
echo "  📋 다음 단계:"
echo "     - 첫 로그인: http://${HOST_IP}:8080 → admin / 위 password"
echo "     - 운영 명령: docs/ops/STAGING_RUNBOOK.md 참고"
echo "     - 로그 확인: $COMPOSE -f $COMPOSE_FILE logs -f backend worker frontend"
echo "     - 재시작:   $COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE restart backend worker"
echo "     - 종료:     $COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE down"
echo
echo " 완료."
echo
