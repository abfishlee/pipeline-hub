# ============================================================================
# Backend Dockerfile — NKS Ready 8계명 준수
# ----------------------------------------------------------------------------
# ① stateless: 컨테이너 내 파일 쓰기 안 함 (업로드는 Object Storage)
# ② env-driven config: APP_* 환경변수만 (하드코딩 금지)
# ③ healthz / readyz: FastAPI 라우트로 제공
# ④ SIGTERM graceful: uvicorn --timeout-graceful-shutdown 10
# ⑤ stdout JSON logs: structlog → stdout
# ⑥ request_id 전파: 미들웨어
# ⑦ multi-stage build + non-root USER
# ⑧ DB migration 자동 실행 X (별도 Job / 명령어)
# ============================================================================

ARG PYTHON_VERSION=3.12

# -- Stage 1: builder -----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# uv: 빠른 의존성 관리
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# deps 먼저 복사 → 레이어 캐시 활용
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 소스 복사 + project 설치
COPY app ./app
COPY alembic.ini* ./
RUN uv sync --frozen --no-dev

# -- Stage 2: runtime -----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

# curl: healthcheck 전용 (최소한만), tini: PID 1 signal forwarding
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# non-root user
RUN groupadd --system --gid 1000 appuser \
 && useradd  --system --uid 1000 --gid appuser --create-home --shell /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic.ini* ./

USER appuser
EXPOSE 8000

# tini = PID 1, uvicorn이 SIGTERM 받아 graceful shutdown
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "10", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

# readiness는 K8s readinessProbe / docker compose healthcheck 에서 처리.
# 여기 HEALTHCHECK 는 docker 단독 실행 시 편의용.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# image metadata (이관 대비)
LABEL org.opencontainers.image.title="datapipeline-backend" \
      org.opencontainers.image.source="https://github.com/abfishlee/pipeline-hub" \
      org.opencontainers.image.description="Unified Data Pipeline Platform — FastAPI backend"
