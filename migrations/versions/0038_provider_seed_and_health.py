"""Phase 5.2.1.1 — provider_definition.secret_ref + seed defaults + provider_health.

Revision ID: 0038
Revises: 0037
Create Date: 2026-04-27 01:00:00+00:00

변경:
  1. domain.provider_definition 에 `secret_ref TEXT` 추가 (Q3 답변).
     - 실제 API key 는 env 또는 Secret Manager. DB 에는 *참조 이름* 만.
     - 예: secret_ref='CLOVA_OCR_API_KEY' → os.environ 또는 NCP Secret Manager 조회.
  2. 기본 provider 6종 seed:
     - OCR: clova_v2, upstage, external_ocr_api (placeholder)
     - CRAWLER: httpx_spider, playwright (placeholder), external_scraping_api
     - HTTP_TRANSFORM: generic_http (외부 정제 API 호출 base)
  3. domain.provider_health — circuit breaker / 실패율 / OPEN/HALF_OPEN/CLOSED 이력.
     Redis 가 *현재 상태* 를 빠르게 보관, DB 는 *이력* 보관 — 운영 화면 + 감사용.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text

revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) secret_ref 컬럼.
    op.execute(
        "ALTER TABLE domain.provider_definition "
        "ADD COLUMN IF NOT EXISTS secret_ref TEXT;"
    )

    # 2) provider_health — circuit breaker 이력.
    op.execute(
        """
        CREATE TABLE domain.provider_health (
            health_id        BIGSERIAL PRIMARY KEY,
            provider_code    TEXT NOT NULL REFERENCES domain.provider_definition(provider_code),
            source_id        BIGINT REFERENCES ctl.data_source(source_id),
            state            TEXT NOT NULL,
            failure_count    INTEGER NOT NULL DEFAULT 0,
            success_count    INTEGER NOT NULL DEFAULT 0,
            last_error       TEXT,
            opened_at        TIMESTAMPTZ,
            closed_at        TIMESTAMPTZ,
            half_open_at     TIMESTAMPTZ,
            occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_provider_health_state CHECK (
                state IN ('CLOSED','OPEN','HALF_OPEN')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_provider_health_lookup "
        "ON domain.provider_health (provider_code, source_id, occurred_at DESC);"
    )
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE
              ON domain.provider_health TO app_rw;
        GRANT SELECT ON domain.provider_health TO app_mart_write;
        GRANT USAGE, SELECT
              ON SEQUENCE domain.provider_health_health_id_seq TO app_rw;
        """
    )

    # 3) 기본 provider seed.
    seed_rows = (
        # OCR
        ("clova_v2", "OCR", "internal_class", "CLOVA OCR V2 (Phase 1.2.4 baseline)",
         "CLOVA_OCR_SECRET", '{"endpoint_env":"CLOVA_OCR_URL"}'),
        ("upstage", "OCR", "internal_class", "Upstage Document OCR (Phase 2.2.4 fallback)",
         "UPSTAGE_API_KEY", '{"endpoint_env":"UPSTAGE_OCR_URL"}'),
        ("external_ocr_api", "OCR", "external_api",
         "Generic external OCR API (placeholder for AWS Textract / Google Vision / 자체 OCR)",
         None, '{"endpoint":"https://example.invalid/ocr","timeout_sec":30}'),
        # CRAWLER
        ("httpx_spider", "CRAWLER", "internal_class",
         "httpx 기반 정적 HTML spider (Phase 2.2.8 baseline)",
         None, '{"respect_robots":true,"rate_limit_per_min":30}'),
        ("playwright", "CRAWLER", "internal_class",
         "Playwright 기반 동적 HTML spider (placeholder)",
         None, '{"headless":true,"viewport":{"width":1280,"height":720}}'),
        ("external_scraping_api", "CRAWLER", "external_api",
         "외부 scraping 서비스 (placeholder)",
         None, '{"endpoint":"https://example.invalid/scrape","timeout_sec":60}'),
        # HTTP_TRANSFORM
        ("generic_http", "HTTP_TRANSFORM", "external_api",
         "범용 외부 정제 API 호출 (Phase 5.2.2 의 HTTP_TRANSFORM 노드 base)",
         None, '{"timeout_sec":15,"max_payload_bytes":1048576}'),
    )

    # bindparam 사용 — JSON 안의 ':30' 같은 문자열이 SQL 파라미터로 오인되는 문제 회피.
    bind = op.get_bind()
    stmt = text(
        "INSERT INTO domain.provider_definition "
        "(provider_code, provider_kind, implementation_type, description, "
        " secret_ref, config_schema, is_active) "
        "VALUES (:code, :kind, :impl, :desc, :secret_ref, "
        "        CAST(:config AS JSONB), TRUE) "
        "ON CONFLICT (provider_code) DO UPDATE SET "
        "  provider_kind = EXCLUDED.provider_kind, "
        "  implementation_type = EXCLUDED.implementation_type, "
        "  description = EXCLUDED.description, "
        "  secret_ref = EXCLUDED.secret_ref, "
        "  config_schema = EXCLUDED.config_schema"
    ).bindparams(
        bindparam("code"),
        bindparam("kind"),
        bindparam("impl"),
        bindparam("desc"),
        bindparam("secret_ref"),
        bindparam("config"),
    )
    for code, kind, impl, desc, secret_ref, config in seed_rows:
        bind.execute(
            stmt,
            {
                "code": code,
                "kind": kind,
                "impl": impl,
                "desc": desc,
                "secret_ref": secret_ref,
                "config": config,
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM domain.provider_definition WHERE provider_code IN ("
        "'clova_v2','upstage','external_ocr_api','httpx_spider','playwright',"
        "'external_scraping_api','generic_http')"
    )
    op.execute("DROP TABLE IF EXISTS domain.provider_health CASCADE;")
    op.execute("ALTER TABLE domain.provider_definition DROP COLUMN IF EXISTS secret_ref;")
