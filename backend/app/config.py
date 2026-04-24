"""Application settings loaded from APP_* environment variables.

모든 설정은 이 모듈을 거쳐야 한다 — `os.getenv` 직접 호출 금지.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

type Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    """Runtime configuration (APP_ prefix, case-insensitive)."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
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
