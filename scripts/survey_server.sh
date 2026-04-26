#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Pipeline Hub — staging server pre-survey
#
# 목적: 회사 서버에 staging 배포 전, 환경 정보를 한 번에 수집해 Claude 가
#       *맞춤 bootstrap 스크립트* 를 만들 수 있게 함.
#
# 실행 방법 (서버 SSH 접속 후):
#   bash <(curl -fsSL https://raw.githubusercontent.com/<repo>/feature/v2-generic-platform/scripts/survey_server.sh)
#   또는
#   wget -O /tmp/survey.sh https://raw.githubusercontent.com/<repo>/feature/v2-generic-platform/scripts/survey_server.sh
#   bash /tmp/survey.sh
#
# 출력은 마크다운 형식 → 그대로 chat 에 paste 하면 됩니다.
# 비밀값/IP/도메인 외 *식별 가능한 사용자 정보* 는 출력하지 않습니다.
# ----------------------------------------------------------------------------

set -u
LANG=C

# 색상은 chat paste 시 노이즈가 되므로 끄기.
export NO_COLOR=1

print_header() {
  printf "\n## %s\n\n" "$1"
}

# 일부 명령은 sudo 없이도 정보가 나오는 fallback 을 우선 시도.
try() {
  local label="$1"; shift
  local out
  if ! out=$("$@" 2>&1); then
    printf -- "- %s: ❌ (실행 실패: %s)\n" "$label" "$out" | head -1
    return 1
  fi
  printf -- "- %s:\n  ```\n%s\n  ```\n" "$label" "$out"
}

# ----------------------------------------------------------------------------
# 0. 메타
# ----------------------------------------------------------------------------
echo "# pipeline-hub staging — server survey"
echo
echo "_생성 시각: $(date -u +%Y-%m-%dT%H:%M:%SZ)_"
echo "_스크립트 호스트: $(hostname 2>/dev/null || echo unknown) ($(whoami 2>/dev/null || echo unknown)@\$(env|grep -i ssh_connection|head -1|awk '{print \$3}' 2>/dev/null || echo unknown))_"

# ----------------------------------------------------------------------------
# 1. OS / 커널 / 아키텍처
# ----------------------------------------------------------------------------
print_header "1. OS / 커널 / 아키텍처"

if [ -f /etc/os-release ]; then
  printf -- "- /etc/os-release:\n  \`\`\`\n%s\n  \`\`\`\n" "$(grep -E '^(NAME|VERSION|VERSION_ID|VERSION_CODENAME|PRETTY_NAME)=' /etc/os-release)"
fi
printf -- "- kernel: \`%s\`\n" "$(uname -srvm 2>/dev/null || echo unknown)"
printf -- "- architecture: \`%s\`\n" "$(uname -m 2>/dev/null || echo unknown)"
printf -- "- timezone: \`%s\`\n" "$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)"

# ----------------------------------------------------------------------------
# 2. 자원 (CPU / RAM / 디스크)
# ----------------------------------------------------------------------------
print_header "2. 자원"

printf -- "- CPU: \`%s vCPU\`\n" "$(nproc 2>/dev/null || echo unknown)"
printf -- "- CPU model: \`%s\`\n" "$(awk -F: '/model name/ {print $2; exit}' /proc/cpuinfo 2>/dev/null | sed 's/^[ \t]*//' || echo unknown)"
printf -- "- 메모리:\n  \`\`\`\n%s\n  \`\`\`\n" "$(free -h 2>/dev/null || echo unknown)"
printf -- "- 디스크:\n  \`\`\`\n%s\n  \`\`\`\n" "$(df -h / /opt /var 2>/dev/null | sort -u || df -h / 2>/dev/null)"
printf -- "- swap: \`%s\`\n" "$(swapon --show=NAME,SIZE,USED 2>/dev/null | head -3 | tr '\n' ' ' || echo none)"

# ----------------------------------------------------------------------------
# 3. 네트워크 / 외부 IP / DNS
# ----------------------------------------------------------------------------
print_header "3. 네트워크"

printf -- "- 사설 IP (interfaces):\n  \`\`\`\n%s\n  \`\`\`\n" \
  "$(ip -4 -o addr show 2>/dev/null | awk '{print $2,$4}' | grep -v '127.0.0.1' || hostname -I 2>/dev/null || echo unknown)"

# 외부 IP — curl 또는 dig 사용 (sudo 불필요).
EXT_IP=""
for url in "https://api.ipify.org" "https://ifconfig.me" "https://ipinfo.io/ip"; do
  EXT_IP=$(curl -s --max-time 4 "$url" 2>/dev/null || true)
  if [ -n "$EXT_IP" ] && echo "$EXT_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    break
  fi
  EXT_IP=""
done
printf -- "- 외부 IP: \`%s\`\n" "${EXT_IP:-unknown (외부 인터넷 차단 환경일 수 있음)}"

# DNS resolver 확인.
printf -- "- /etc/resolv.conf:\n  \`\`\`\n%s\n  \`\`\`\n" \
  "$(grep -E '^(nameserver|search)' /etc/resolv.conf 2>/dev/null || echo none)"

# ----------------------------------------------------------------------------
# 4. 포트 사용 — 충돌 가능성 (sudo 없이도 LISTEN 만 보면 됨)
# ----------------------------------------------------------------------------
print_header "4. 포트 사용 (충돌 가능성 검사)"

# Phase 5 staging 이 사용 예정인 포트.
TARGET_PORTS="22 80 443 3000 5173 5434 6380 8000 8080 9000 9001"

if command -v ss >/dev/null 2>&1; then
  echo "- listening sockets (\`ss -tlnp\`, sudo 없으면 process 컬럼 비어있을 수 있음):"
  echo "  \`\`\`"
  ss -tlnp 2>&1 | head -40
  echo "  \`\`\`"

  echo
  echo "- target 포트 점유 상태:"
  echo "  \`\`\`"
  for p in $TARGET_PORTS; do
    found=$(ss -tlnH "sport = :$p" 2>/dev/null | head -1)
    if [ -n "$found" ]; then
      printf "  %-5s  USED   %s\n" "$p" "$found"
    else
      printf "  %-5s  free\n" "$p"
    fi
  done
  echo "  \`\`\`"
else
  echo "- ss 없음 — netstat 사용:"
  echo "  \`\`\`"
  netstat -tlnp 2>&1 | head -30 || echo "netstat 도 없음"
  echo "  \`\`\`"
fi

# ----------------------------------------------------------------------------
# 5. 기존 설치된 도구 (Docker, Postgres, Nginx, etc.)
# ----------------------------------------------------------------------------
print_header "5. 이미 설치된 도구"

check_cmd() {
  local cmd="$1"; local label="${2:-$1}"
  if command -v "$cmd" >/dev/null 2>&1; then
    local v
    v=$("$cmd" --version 2>/dev/null | head -1 || "$cmd" -V 2>/dev/null | head -1 || echo "(version 불명)")
    printf -- "- %s: ✅ \`%s\`\n" "$label" "$v"
  else
    printf -- "- %s: ❌ (미설치)\n" "$label"
  fi
}

check_cmd docker "Docker"
check_cmd "docker compose" "docker compose v2" || \
  ( docker compose version 2>/dev/null | head -1 | sed 's/^/- docker compose v2: ✅ `/;s/$/`/' || \
    echo "- docker compose v2: ❌" )
check_cmd docker-compose "docker-compose v1 (legacy)"
check_cmd nginx "nginx"
check_cmd certbot "certbot (Let's Encrypt)"
check_cmd psql "psql (PostgreSQL client)"
check_cmd redis-cli "redis-cli"
check_cmd python3 "python3"
check_cmd node "node"
check_cmd git "git"
check_cmd ufw "ufw (firewall)"
check_cmd curl "curl"
check_cmd jq "jq"

# ----------------------------------------------------------------------------
# 6. 실행 중인 프로세스 / 서비스 (성격 파악)
# ----------------------------------------------------------------------------
print_header "6. 실행 중인 서비스"

if command -v systemctl >/dev/null 2>&1; then
  echo "- systemd active (사용자 / DB / 웹 관련 일부):"
  echo "  \`\`\`"
  systemctl list-units --type=service --state=running 2>/dev/null \
    | grep -E '(docker|postgres|redis|nginx|apache|mysql|mariadb|mongo|elastic)' \
    | head -20 || echo "  (관련 서비스 없음)"
  echo "  \`\`\`"
fi

if command -v docker >/dev/null 2>&1; then
  echo
  echo "- docker 실행 중 컨테이너:"
  echo "  \`\`\`"
  docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}" 2>&1 | head -20 || echo "  (docker 권한 없음 또는 미동작)"
  echo "  \`\`\`"
fi

# ----------------------------------------------------------------------------
# 7. 방화벽 / 보안 그룹
# ----------------------------------------------------------------------------
print_header "7. 방화벽 / 보안 그룹"

if command -v ufw >/dev/null 2>&1; then
  echo "- ufw status (sudo 필요할 수 있음):"
  echo "  \`\`\`"
  ufw status verbose 2>&1 | head -20 || echo "  (sudo 없이 조회 불가)"
  echo "  \`\`\`"
fi

if command -v iptables >/dev/null 2>&1; then
  echo "- iptables INPUT (요약):"
  echo "  \`\`\`"
  iptables -L INPUT -n 2>&1 | head -10 || echo "  (sudo 없이 조회 불가)"
  echo "  \`\`\`"
fi

# ----------------------------------------------------------------------------
# 8. 사용자 / sudo 권한
# ----------------------------------------------------------------------------
print_header "8. 사용자 / sudo / docker group"

printf -- "- 현재 사용자: \`%s\`\n" "$(whoami)"
printf -- "- 그룹: \`%s\`\n" "$(id -Gn 2>/dev/null)"
echo "- sudo 가능 여부:"
echo "  \`\`\`"
sudo -n true 2>&1 && echo "  passwordless sudo OK" || \
  echo "  passwordless sudo 불가 (대화형 password 필요)"
echo "  \`\`\`"

# ----------------------------------------------------------------------------
# 9. 프로젝트 디렉토리 후보
# ----------------------------------------------------------------------------
print_header "9. 프로젝트 디렉토리 후보"

for d in /opt /srv /home /var/www; do
  if [ -d "$d" ]; then
    free=$(df -h "$d" 2>/dev/null | awk 'NR==2 {print $4}')
    owned=$(stat -c '%U:%G' "$d" 2>/dev/null || echo unknown)
    printf -- "- \`%s\`: 여유 %s, 소유자 %s\n" "$d" "$free" "$owned"
  fi
done

# ----------------------------------------------------------------------------
# 10. SSL / 도메인 힌트
# ----------------------------------------------------------------------------
print_header "10. SSL / 도메인 정책 (수동 답변 필요)"

cat <<'EOF'
다음 중 하나 선택해서 답해주세요 (스크립트로 자동 감지 X):

A) 사내망 only — IP:포트 로 운영 (예: http://172.30.1.131:8080).
   → 가장 간단. SSL 불필요.

B) 사내 도메인 + 회사 와일드카드 인증서.
   → 도메인 이름 + cert/key 파일 위치 알려주세요.

C) 외부 도메인 + Let's Encrypt 자동.
   → 도메인 이름 + DNS A 레코드가 이미 이 서버 IP 를 가리키는지 확인.

D) 기타 (IDC 자체 인증서 / 회사 ACM 등).
   → 시나리오 설명.
EOF

# /etc/nginx/sites-available 같은 곳에 기존 cert 가 있으면 hint.
echo
if [ -d /etc/letsencrypt/live ]; then
  echo "- 발견된 Let's Encrypt 인증서:"
  echo "  \`\`\`"
  ls /etc/letsencrypt/live 2>&1 | head -10
  echo "  \`\`\`"
fi
if [ -d /etc/ssl/certs ]; then
  custom_certs=$(find /etc/ssl/certs -maxdepth 1 -name '*.pem' -newer /etc/ssl 2>/dev/null | head -5)
  if [ -n "$custom_certs" ]; then
    echo "- /etc/ssl/certs 에 발견된 사용자 cert 후보:"
    echo "  \`\`\`"
    echo "$custom_certs"
    echo "  \`\`\`"
  fi
fi

# ----------------------------------------------------------------------------
# 11. 결과 — paste 안내
# ----------------------------------------------------------------------------
echo
echo "---"
echo
echo "## 다음 단계"
echo
echo "위 마크다운 결과를 그대로 chat 에 paste 해주세요."
echo "Claude 가 환경에 맞춰 다음 산출물을 만듭니다:"
echo "  1. \`infra/docker-compose.staging.yml\` — 충돌 안 나는 포트 + 모드 D-1/D-2/D-3 반영"
echo "  2. \`.env.staging.example\` — 비밀값은 서버에서 직접 생성"
echo "  3. \`scripts/staging_bootstrap.sh\` — 한 줄로 clone → migration → 서비스 기동"
echo "  4. \`docs/ops/STAGING_RUNBOOK.md\` — 일상 운영 절차"
echo
echo "비밀값 / IP / 도메인 외 식별 정보는 결과에 포함 안 됩니다."
echo "혹시 노출되면 안 되는 항목이 있으면 paste 전 가려주세요."
