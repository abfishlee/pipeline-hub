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

    # ---- Upstage Document OCR (Phase 2.2.4 폴백) ----
    upstage_ocr_url: str = "https://api.upstage.ai"
    upstage_api_key: SecretStr = SecretStr("")

    # ---- OCR 정책 ----
    ocr_confidence_threshold: float = 0.85

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
