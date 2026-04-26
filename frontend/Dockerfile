# ============================================================================
# Frontend Dockerfile — multi-stage (Node 빌드 → Nginx static 서빙)
# NKS Ready 8계명 준수:
#   ① Stateless (read-only static)
#   ② env-driven (vite 빌드 시점 env 또는 런타임 nginx 프록시)
#   ③ /healthz 엔드포인트 (nginx 가 200 OK 리턴)
#   ④ SIGTERM graceful (nginx 가 처리)
#   ⑤ stdout 로그 (nginx access/error → stdout/stderr)
#   ⑥ Request ID 전파 (nginx → backend 로 패스스루)
#   ⑦ multi-stage + non-root USER
#   ⑧ 마이그레이션 없음 (frontend 는 정적 자산만)
# ============================================================================

ARG NODE_VERSION=20
ARG NGINX_VERSION=1.27-alpine

# -- Stage 1: builder ---------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /build

# pnpm 활성화
RUN corepack enable

# 의존성 설치 (lock 우선)
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# 소스 복사 + 빌드
COPY tsconfig.json vite.config.ts tailwind.config.ts postcss.config.js index.html ./
COPY src ./src
RUN pnpm build

# -- Stage 2: nginx runtime ---------------------------------------------------
FROM nginx:${NGINX_VERSION} AS runtime

# 정적 자산 복사
COPY --from=builder /build/dist /usr/share/nginx/html

# nginx 설정 — SPA fallback + /v1 backend proxy + healthz
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

# non-root: nginx alpine 이미지는 nginx 유저(101) 가 이미 있음.
# nginx 1.27 의 default nginx.conf 가 `pid /run/nginx.pid;` 를 사용하므로
# /run 도 nginx 가 쓸 수 있어야 함. /etc/nginx/conf.d 도 entrypoint 가
# envsubst 시도하므로 쓰기 권한 필요.
RUN chown -R nginx:nginx \
        /usr/share/nginx/html \
        /var/cache/nginx \
        /var/log/nginx \
        /run \
        /etc/nginx/conf.d \
 && chmod -R 755 /usr/share/nginx/html

# unprivileged 포트 (80 포함) — 실제 NKS 에서는 ingress 가 외부 노출.
EXPOSE 80
USER nginx

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz || exit 1

LABEL org.opencontainers.image.title="datapipeline-frontend" \
      org.opencontainers.image.source="https://github.com/abfishlee/pipeline-hub"
