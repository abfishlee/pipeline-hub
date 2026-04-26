"""Phase 7 Wave 1B + Wave 3 + Wave 4 — node_type 확장 + provider_usage + DQ catalog.

Revision ID: 0050
Revises: 0049
Create Date: 2026-04-26 23:00:00+00:00

본 migration 은 Phase 7 의 Wave 1B + 3 + 4 의 schema 변화를 한 번에 적용:

Wave 1B:
  - wf.node_definition CHECK 에 OCR_RESULT_INGEST / CRAWLER_RESULT_INGEST /
    CDC_EVENT_FETCH 추가 (총 20종)

Wave 3 (Provider Registry primary path):
  - audit.provider_usage 테이블 — 외부 provider 호출 1건당 1 row
  - LLM_CLASSIFY provider_kind seed (OpenAI + Clova HCX)
  - ADDRESS_NORMALIZE / PRODUCT_CANONICALIZE / CODE_LOOKUP provider_kind 추가

Wave 4 (DQ catalog 확장):
  - dq_rule.rule_kind CHECK 에 freshness / anomaly_zscore / drift 추가
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Wave 1B — node_type 20종 (Wave 1A 17종 + 3종)
    # ------------------------------------------------------------------
    _V1_TYPES = (
        "NOOP", "SOURCE_API", "SQL_TRANSFORM", "DEDUP", "DQ_CHECK",
        "LOAD_MASTER", "NOTIFY",
    )
    _V2_TYPES = (
        "MAP_FIELDS", "SQL_INLINE_TRANSFORM", "SQL_ASSET_TRANSFORM",
        "HTTP_TRANSFORM", "FUNCTION_TRANSFORM", "LOAD_TARGET",
        "OCR_TRANSFORM", "CRAWL_FETCH", "STANDARDIZE",
        "SOURCE_DATA", "PUBLIC_API_FETCH",
        # Wave 1A
        "WEBHOOK_INGEST", "FILE_UPLOAD_INGEST", "DB_INCREMENTAL_FETCH",
        # Wave 1B (신규 3종)
        "OCR_RESULT_INGEST", "CRAWLER_RESULT_INGEST", "CDC_EVENT_FETCH",
    )
    op.execute(
        "ALTER TABLE wf.node_definition DROP CONSTRAINT IF EXISTS ck_node_type;"
    )
    quoted = ",".join(f"'{t}'" for t in (*_V1_TYPES, *_V2_TYPES))
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )

    # ------------------------------------------------------------------
    # Wave 3 — audit.provider_usage 테이블
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE audit.provider_usage (
            usage_id          BIGSERIAL,
            occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            provider_code     TEXT NOT NULL,
            provider_kind     TEXT NOT NULL,
            domain_code       TEXT,
            workflow_run_id   BIGINT,
            node_key          TEXT,
            request_count     INTEGER NOT NULL DEFAULT 1,
            success_count     INTEGER NOT NULL DEFAULT 0,
            error_count       INTEGER NOT NULL DEFAULT 0,
            duration_ms       INTEGER NOT NULL DEFAULT 0,
            cost_estimate     NUMERIC(12, 4),
            error_kind        TEXT,
            metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (usage_id, occurred_at)
        ) PARTITION BY RANGE (occurred_at);
        """
    )
    op.execute(
        """
        CREATE TABLE audit.provider_usage_2026_04
            PARTITION OF audit.provider_usage
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
        CREATE TABLE audit.provider_usage_2026_05
            PARTITION OF audit.provider_usage
            FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
        """
    )
    op.execute(
        "CREATE INDEX idx_provider_usage_provider ON audit.provider_usage "
        "(provider_code, occurred_at DESC);"
    )
    op.execute(
        "GRANT SELECT, INSERT ON audit.provider_usage TO app_rw; "
        "GRANT USAGE ON SEQUENCE audit.provider_usage_usage_id_seq TO app_rw;"
    )

    # ------------------------------------------------------------------
    # Wave 3 — provider_kind CHECK 확장 (4종 → 8종)
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE domain.provider_definition "
        "DROP CONSTRAINT IF EXISTS ck_provider_kind;"
    )
    op.execute(
        "ALTER TABLE domain.provider_definition ADD CONSTRAINT ck_provider_kind "
        "CHECK (provider_kind IN ("
        "    'OCR', 'CRAWLER', 'AI_TRANSFORM', 'HTTP_TRANSFORM', "
        "    'LLM_CLASSIFY', 'ADDRESS_NORMALIZE', "
        "    'PRODUCT_CANONICALIZE', 'CODE_LOOKUP'"
        "));"
    )

    # ------------------------------------------------------------------
    # Wave 3 — provider seed
    # ------------------------------------------------------------------
    # 기존 CHECK 는 implementation_type IN ('internal_class', 'external_api').
    # 모든 신규 provider 는 external_api 로 통일 — backend factory 가 provider_code
    # 로 dispatch.
    op.execute(
        "INSERT INTO domain.provider_definition "
        "(provider_code, provider_kind, implementation_type, config_schema, "
        " description, is_active) VALUES "
        "('llm_openai', 'LLM_CLASSIFY', 'external_api', "
        " '{\"required\":[\"api_key\",\"model\"],\"vendor\":\"openai\"}'::jsonb, "
        " 'OpenAI Function Calling + JSON Schema 응답', true), "
        "('llm_clova_hcx', 'LLM_CLASSIFY', 'external_api', "
        " '{\"required\":[\"api_key\",\"app_id\"],\"vendor\":\"clova_hcx\"}'::jsonb, "
        " 'NCP Clova HyperCLOVA X — 국내/NCP 친화', true), "
        "('addr_juso_go_kr', 'ADDRESS_NORMALIZE', 'external_api', "
        " '{\"required\":[\"confm_key\"],\"vendor\":\"juso_open_api\"}'::jsonb, "
        " '도로명/지번 표준화 (juso.go.kr)', true), "
        "('product_canon_default', 'PRODUCT_CANONICALIZE', 'internal_class', "
        " '{\"vendor\":\"rule_based\"}'::jsonb, "
        " '내장 규칙 기반 상품명 정규화', true) "
        "ON CONFLICT (provider_code) DO NOTHING;"
    )

    # ------------------------------------------------------------------
    # Wave 4 — DQ rule_kind 확장 (3종 추가)
    # ------------------------------------------------------------------
    # 기존 CHECK 는 sub-form pattern 으로 backend 가 검증. DB CHECK 는 별도이므로
    # rule_kind 컬럼에 CHECK 가 있는지 확인 필요. 없다면 무관, 있다면 확장.
    # 안전을 위해 IF EXISTS 로 drop 후 재생성 (없으면 noop).
    op.execute(
        "ALTER TABLE domain.dq_rule DROP CONSTRAINT IF EXISTS ck_dq_rule_kind;"
    )
    op.execute(
        "ALTER TABLE domain.dq_rule ADD CONSTRAINT ck_dq_rule_kind "
        "CHECK (rule_kind IN ("
        "    'row_count_min', 'null_pct_max', 'unique_columns', "
        "    'reference', 'range', 'custom_sql', "
        "    'freshness', 'anomaly_zscore', 'drift'"
        "));"
    )


def downgrade() -> None:
    # DQ rule_kind 복원
    op.execute(
        "ALTER TABLE domain.dq_rule DROP CONSTRAINT IF EXISTS ck_dq_rule_kind;"
    )
    # provider seed 제거
    op.execute(
        "DELETE FROM domain.provider_definition WHERE provider_code IN ("
        "  'llm_openai', 'llm_clova_hcx', 'addr_juso_go_kr', 'product_canon_default');"
    )
    # provider_kind CHECK 복원 (4종)
    op.execute(
        "ALTER TABLE domain.provider_definition "
        "DROP CONSTRAINT IF EXISTS ck_provider_kind;"
    )
    op.execute(
        "ALTER TABLE domain.provider_definition ADD CONSTRAINT ck_provider_kind "
        "CHECK (provider_kind IN ("
        "    'OCR', 'CRAWLER', 'AI_TRANSFORM', 'HTTP_TRANSFORM'"
        "));"
    )
    # provider_usage 제거
    op.execute("DROP TABLE IF EXISTS audit.provider_usage_2026_05 CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.provider_usage_2026_04 CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.provider_usage CASCADE;")
    # node_type CHECK 복원 (Wave 1A 17종)
    op.execute(
        "ALTER TABLE wf.node_definition DROP CONSTRAINT IF EXISTS ck_node_type;"
    )
    _V1_TYPES = (
        "NOOP", "SOURCE_API", "SQL_TRANSFORM", "DEDUP", "DQ_CHECK",
        "LOAD_MASTER", "NOTIFY",
    )
    _V2_TYPES = (
        "MAP_FIELDS", "SQL_INLINE_TRANSFORM", "SQL_ASSET_TRANSFORM",
        "HTTP_TRANSFORM", "FUNCTION_TRANSFORM", "LOAD_TARGET",
        "OCR_TRANSFORM", "CRAWL_FETCH", "STANDARDIZE",
        "SOURCE_DATA", "PUBLIC_API_FETCH",
        "WEBHOOK_INGEST", "FILE_UPLOAD_INGEST", "DB_INCREMENTAL_FETCH",
    )
    quoted = ",".join(f"'{t}'" for t in (*_V1_TYPES, *_V2_TYPES))
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )
