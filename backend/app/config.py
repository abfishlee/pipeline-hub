"""Application settings loaded from APP_* environment variables.

모든 설정은 이 모듈을 거쳐야 한다 — `os.getenv` 직접 호출 금지.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 탐색 경로: 현재 cwd → backend/ → repo root.
# 중복 정의된 키는 마지막에 로드된 파일 값이 우선 (Pydantic 문서 기준).
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_ENV_FILES: tuple[str, ...] = (
    str(_REPO_ROOT / ".env"),  # repo root (운영/개발 통합 .env)
    str(_BACKEND_DIR / ".env"),  # backend 전용 override (선택)
    ".env",  # cwd (테스트나 임시 override)
)

type Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    """Runtime configuration (APP_ prefix, case-insensitive)."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 환경 ----
    env: Environment = "local"
    debug: bool = False
    base_url: str = "http://localhost:8000"

    # ---- Auth ----
    jwt_secret: SecretStr = Field(
        default=SecretStr("dev-only-change-me-dev-only-change-me-32b"),
        description="JWT signing secret (32+ bytes).",
    )
    jwt_access_ttl_min: int = 60
    jwt_refresh_ttl_days: int = 14

    # ---- DB / Redis ----
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/datapipeline"
    redis_url: str = "redis://localhost:6379/0"

    # ---- Worker (Phase 2.2.1~) ----
    # Redis Streams 토픽 prefix — 실제 stream key 는 `<prefix>:<aggregate_type>`.
    redis_streams_prefix: str = "dp:events"
    # Dramatiq 큐 prefix — actor 큐 이름은 `<prefix>:<queue>`.
    dramatiq_queue_prefix: str = "dp"
    # outbox publisher 1회 배치 크기 (DB UPDATE 단위).
    outbox_batch_size: int = 200
    # 영구 실패 판정 max attempts (이 값 이상이면 dead_letter 로 이동).
    outbox_max_attempts: int = 5

    # ---- Object Storage ----
    os_endpoint: str = "http://localhost:9000"
    os_access_key: SecretStr = SecretStr("minioadmin")
    os_secret_key: SecretStr = SecretStr("minioadmin")
    os_bucket: str = "datapipeline-raw"
    os_region: str = "kr-standard"
    os_scheme: Literal["minio", "ncp"] = "minio"

    # ---- CORS ----
    cors_origins: str = "http://localhost:5173"

    # ---- 로깅 ----
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False

    # ---- 외부 AI (Phase 2부터 사용) ----
    clova_ocr_url: str = ""
    clova_ocr_secret: SecretStr = SecretStr("")
    hyperclova_api_key: SecretStr = SecretStr("")
    hyperclova_api_url: str = "https://clovastudio.stream.ntruss.com"
    hyperclova_embedding_app: str = "/testapp/v1/api-tools/embedding/v2"

    # ---- Upstage Document OCR (Phase 2.2.4 폴백) ----
    upstage_ocr_url: str = "https://api.upstage.ai"
    upstage_api_key: SecretStr = SecretStr("")

    # ---- OCR 정책 ----
    ocr_confidence_threshold: float = 0.85

    # ---- 표준화 정책 (Phase 2.2.5) ----
    std_trigram_threshold: float = 0.7
    std_embedding_threshold: float = 0.85
    embedding_dim: int = 1536

    # ---- price_fact 게이트 (Phase 2.2.6) ----
    # 80~95 confidence 구간의 row 중 이 비율만 crowd_task("price_fact_sample_review") 적재.
    price_fact_sample_rate: float = 0.05

    # ---- 크롤러 정책 (Phase 2.2.8) ----
    crawler_user_agent: str = (
        "datapipeline-crawler/2.2.8 (+https://github.com/abfishlee/pipeline-hub)"
    )
    crawler_timeout_sec: float = 15.0
    crawler_respect_robots: bool = True

    # ---- Airflow integration (Phase 4.0.4) ----
    # Airflow scheduled_pipelines DAG 가 backend 의 internal endpoint 를 호출할 때 헤더에
    # 동봉. 비어 있으면 internal endpoint 가 503 (개발 환경에서 cron 자동 실행 비활성).
    airflow_internal_token: SecretStr = SecretStr("")

    # ---- Notify worker (Phase 4.2.2) ----
    # Slack 기본 webhook URL. 비어 있으면 Slack 발송은 no-op (로그만).
    notify_slack_webhook_url: SecretStr = SecretStr("")
    # Email SMTP 미구성 — Phase 4.x 후속에서 Naver Cloud Mailer 도입 예정. 우선 stub.
    notify_email_from: str = "noreply@pipeline-hub.local"
    notify_http_timeout_sec: float = 5.0

    # ---- Sentry (Phase 2.2.9) — DSN 비어 있으면 init skip ----
    sentry_dsn: SecretStr = SecretStr("")
    # 환경 라벨 (env 와 분리). prod 만 보내고 싶을 때 sample_rate 0 으로 끌 수도 있음.
    sentry_env: str = "local"
    sentry_sample_rate: float = 0.1
    # transaction sample (APM). 1.0 이면 모든 요청 추적 (성능 영향 큼).
    sentry_traces_sample_rate: float = 0.0

    # ---- 계산 프로퍼티 ----
    @property
    def cors_origin_list(self) -> list[str]:
        """Comma-separated origins → stripped list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "prod"

    @property
    def is_local(self) -> bool:
        return self.env == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings singleton (환경변수 기반이라 불변)."""
    return Settings()


__all__ = ["Settings", "get_settings"]
