"""Phase 7 Wave 1A — Inbound push channel + envelope (외부 → 우리).

Revision ID: 0049
Revises: 0048
Create Date: 2026-04-26 22:00:00+00:00

목적:
  외부 시스템 (크롤링 업체 / OCR 업체 / 소상공인 업로드 등) 이 우리에게 push 하는
  데이터를 표준 envelope 으로 수신하기 위한 인프라.

테이블:
  domain.inbound_channel — 외부 push 채널 등록 (URL slug + HMAC secret + workflow 연결)
  audit.inbound_event    — 수신된 모든 envelope (idempotency 강제, 처리 상태 추적)

global standard 참조:
  - Stripe Webhook (HMAC SHA256 + replay window)
  - Singer / Airbyte inbound spec
  - Outbox pattern (Wave 6 에서 outbox 와 연동)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Phase 6 Wave 5 회귀 fix — ctl.dry_run_record 의 ck_dry_run_kind
    # 에 'workflow' 누락. workflow-level dry-run 시 INSERT 실패.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE ctl.dry_run_record "
        "DROP CONSTRAINT IF EXISTS ck_dry_run_kind;"
    )
    op.execute(
        "ALTER TABLE ctl.dry_run_record ADD CONSTRAINT ck_dry_run_kind "
        "CHECK (kind IN ('field_mapping','load_target','dq_rule','sql_asset',"
        "                'mart_designer','custom','workflow'));"
    )

    # ------------------------------------------------------------------
    # domain.inbound_channel — 외부 push 채널 등록
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE domain.inbound_channel (
            channel_id          BIGSERIAL PRIMARY KEY,
            channel_code        TEXT NOT NULL UNIQUE,
            domain_code         TEXT NOT NULL
                                    REFERENCES domain.domain_definition(domain_code),
            name                TEXT NOT NULL,
            description         TEXT,

            channel_kind        TEXT NOT NULL,
            secret_ref          TEXT NOT NULL,
            auth_method         TEXT NOT NULL DEFAULT 'hmac_sha256',

            expected_content_type TEXT,
            max_payload_bytes   INTEGER NOT NULL DEFAULT 10485760,
            rate_limit_per_min  INTEGER NOT NULL DEFAULT 100,
            replay_window_sec   INTEGER NOT NULL DEFAULT 300,

            workflow_id         BIGINT
                                    REFERENCES wf.workflow_definition(workflow_id)
                                    ON DELETE SET NULL,

            status              TEXT NOT NULL DEFAULT 'DRAFT',
            is_active           BOOLEAN NOT NULL DEFAULT true,
            created_by          BIGINT REFERENCES ctl.app_user(user_id),
            approved_by         BIGINT REFERENCES ctl.app_user(user_id),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_inbound_channel_kind CHECK (
                channel_kind IN ('WEBHOOK', 'FILE_UPLOAD',
                                 'OCR_RESULT', 'CRAWLER_RESULT')
            ),
            CONSTRAINT ck_inbound_channel_auth CHECK (
                auth_method IN ('hmac_sha256', 'api_key', 'mtls')
            ),
            CONSTRAINT ck_inbound_channel_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT ck_inbound_channel_code_format CHECK (
                channel_code ~ '^[a-z][a-z0-9_]{1,62}$'
            ),
            CONSTRAINT ck_inbound_channel_payload_size CHECK (
                max_payload_bytes BETWEEN 1024 AND 1073741824
            ),
            CONSTRAINT ck_inbound_channel_rate CHECK (
                rate_limit_per_min BETWEEN 1 AND 100000
            ),
            CONSTRAINT ck_inbound_channel_replay CHECK (
                replay_window_sec BETWEEN 30 AND 3600
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_inbound_channel_domain ON domain.inbound_channel "
        "(domain_code, status) WHERE is_active = true;"
    )
    op.execute(
        "CREATE INDEX idx_inbound_channel_workflow ON domain.inbound_channel "
        "(workflow_id) WHERE workflow_id IS NOT NULL;"
    )

    # ------------------------------------------------------------------
    # audit.inbound_event — 수신된 envelope (idempotent + 추적)
    # ------------------------------------------------------------------
    # PARTITION BY received_at (월별) — 1년 후 cold archive 가능 (Phase 4.2.7).
    op.execute(
        """
        CREATE TABLE audit.inbound_event (
            envelope_id         BIGSERIAL,
            received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

            channel_code        TEXT NOT NULL,
            channel_id          BIGINT,
            domain_code         TEXT,

            idempotency_key     TEXT NOT NULL,

            sender_signature    TEXT,
            sender_ip           INET,
            user_agent          TEXT,
            request_id          TEXT NOT NULL,

            content_type        TEXT NOT NULL,
            payload_size_bytes  INTEGER NOT NULL,
            payload_object_key  TEXT,
            payload_inline      JSONB,

            status              TEXT NOT NULL DEFAULT 'RECEIVED',
            workflow_run_id     BIGINT,
            error_message       TEXT,
            processed_at        TIMESTAMPTZ,

            PRIMARY KEY (envelope_id, received_at),
            CONSTRAINT ck_inbound_event_status CHECK (
                status IN ('RECEIVED','PROCESSING','DONE','FAILED','DLQ')
            )
        ) PARTITION BY RANGE (received_at);
        """
    )
    # 현재 월 + 다음 월 partition 미리 생성 (운영 cron 이 월별 추가).
    op.execute(
        """
        CREATE TABLE audit.inbound_event_2026_04
            PARTITION OF audit.inbound_event
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
        CREATE TABLE audit.inbound_event_2026_05
            PARTITION OF audit.inbound_event
            FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
        CREATE TABLE audit.inbound_event_2026_06
            PARTITION OF audit.inbound_event
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
        """
    )
    # idempotency UNIQUE (channel_code, idempotency_key) — partition-aware.
    op.execute(
        "CREATE UNIQUE INDEX uq_inbound_event_idempotency "
        "ON audit.inbound_event (channel_code, idempotency_key, received_at);"
    )
    op.execute(
        "CREATE INDEX idx_inbound_event_status ON audit.inbound_event "
        "(status, received_at) WHERE status IN ('RECEIVED','PROCESSING');"
    )
    op.execute(
        "CREATE INDEX idx_inbound_event_channel ON audit.inbound_event "
        "(channel_code, received_at DESC);"
    )

    # GRANT
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON domain.inbound_channel TO app_rw; "
        "GRANT SELECT, INSERT, UPDATE ON audit.inbound_event TO app_rw; "
        "GRANT USAGE ON SEQUENCE domain.inbound_channel_channel_id_seq TO app_rw; "
        "GRANT USAGE ON SEQUENCE audit.inbound_event_envelope_id_seq TO app_rw;"
    )

    # ------------------------------------------------------------------
    # wf.node_definition CHECK — 신규 node_type 3종 추가 (Wave 1A)
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
        # Phase 7 Wave 1A 신규
        "WEBHOOK_INGEST", "FILE_UPLOAD_INGEST", "DB_INCREMENTAL_FETCH",
    )
    op.execute(
        "ALTER TABLE wf.node_definition DROP CONSTRAINT IF EXISTS ck_node_type;"
    )
    quoted = ",".join(f"'{t}'" for t in (*_V1_TYPES, *_V2_TYPES))
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )


def downgrade() -> None:
    # node_type CHECK 복원 (Phase 6 Wave 4 시점 = 18종)
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
    )
    quoted = ",".join(f"'{t}'" for t in (*_V1_TYPES, *_V2_TYPES))
    op.execute(
        f"ALTER TABLE wf.node_definition "
        f"ADD CONSTRAINT ck_node_type CHECK (node_type IN ({quoted}));"
    )

    op.execute("DROP TABLE IF EXISTS audit.inbound_event_2026_06 CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.inbound_event_2026_05 CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.inbound_event_2026_04 CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.inbound_event CASCADE;")
    op.execute("DROP TABLE IF EXISTS domain.inbound_channel CASCADE;")

    # dry_run_record CHECK 복원 (workflow 제거)
    op.execute(
        "ALTER TABLE ctl.dry_run_record "
        "DROP CONSTRAINT IF EXISTS ck_dry_run_kind;"
    )
    op.execute(
        "ALTER TABLE ctl.dry_run_record ADD CONSTRAINT ck_dry_run_kind "
        "CHECK (kind IN ('field_mapping','load_target','dq_rule','sql_asset',"
        "                'mart_designer','custom'));"
    )
