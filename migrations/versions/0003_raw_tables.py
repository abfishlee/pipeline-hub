"""raw tables — raw_object (PARTITIONED) + content_hash_index + ocr_result + raw_web_page + db_snapshot

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-25 10:00:00+00:00

docs/03_DATA_MODEL.md 3.3 정합. 파티션 자동 생성은 Phase 2 Airflow DAG.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- raw.raw_object (PARTITIONED BY RANGE on partition_date) ---
    # alembic.op.create_table 은 PARTITION BY 직접 지원이 약하므로 raw SQL 사용.
    op.execute(
        """
        CREATE TABLE raw.raw_object (
            raw_object_id     BIGSERIAL,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            job_id            BIGINT,
            object_type       TEXT NOT NULL CHECK (
                object_type IN ('JSON','XML','CSV','HTML','PDF','IMAGE','DB_ROW','RECEIPT_IMAGE')
            ),
            object_uri        TEXT,
            payload_json      JSONB,
            content_hash      TEXT NOT NULL,
            idempotency_key   TEXT,
            received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            partition_date    DATE NOT NULL DEFAULT CURRENT_DATE,
            status            TEXT NOT NULL DEFAULT 'RECEIVED' CHECK (
                status IN ('RECEIVED','PROCESSED','FAILED','DISCARDED')
            ),
            CONSTRAINT pk_raw_object PRIMARY KEY (raw_object_id, partition_date)
        ) PARTITION BY RANGE (partition_date);
        """
    )

    # 초기 파티션 — 2026-04 (현재 월)
    op.execute(
        """
        CREATE TABLE raw.raw_object_2026_04 PARTITION OF raw.raw_object
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
        """
    )

    # 인덱스 (파티션 부모에 생성하면 모든 child 에 적용)
    op.execute(
        "CREATE INDEX raw_object_source_received_idx "
        "ON raw.raw_object (source_id, received_at DESC);"
    )
    op.execute(
        "CREATE INDEX raw_object_status_idx "
        "ON raw.raw_object (status) WHERE status IN ('RECEIVED','FAILED');"
    )
    op.execute(
        "CREATE INDEX raw_object_payload_gin "
        "ON raw.raw_object USING gin (payload_json jsonb_path_ops);"
    )

    # --- raw.content_hash_index (전역 unique 보장) ---
    op.execute(
        """
        CREATE TABLE raw.content_hash_index (
            content_hash      TEXT PRIMARY KEY,
            raw_object_id     BIGINT NOT NULL,
            partition_date    DATE NOT NULL,
            source_id         BIGINT NOT NULL,
            first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX content_hash_source_idx ON raw.content_hash_index (source_id);"
    )

    # --- raw.ocr_result ---
    op.execute(
        """
        CREATE TABLE raw.ocr_result (
            ocr_result_id     BIGSERIAL PRIMARY KEY,
            raw_object_id     BIGINT NOT NULL,
            partition_date    DATE NOT NULL,
            page_no           INTEGER,
            text_content      TEXT,
            confidence_score  NUMERIC(5,2),
            layout_json       JSONB,
            engine_name       TEXT NOT NULL,
            engine_version    TEXT,
            duration_ms       INTEGER,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ocr_result_raw_idx "
        "ON raw.ocr_result (raw_object_id, partition_date);"
    )

    # --- raw.raw_web_page ---
    op.execute(
        """
        CREATE TABLE raw.raw_web_page (
            page_id           BIGSERIAL PRIMARY KEY,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            job_id            BIGINT,
            url               TEXT NOT NULL,
            http_status       INTEGER,
            html_object_uri   TEXT NOT NULL,
            response_headers  JSONB,
            fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            content_hash      TEXT NOT NULL,
            parser_version    TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX raw_web_page_url_fetched_idx "
        "ON raw.raw_web_page (url, fetched_at DESC);"
    )

    # --- raw.db_snapshot ---
    op.execute(
        """
        CREATE TABLE raw.db_snapshot (
            snapshot_id       BIGSERIAL PRIMARY KEY,
            source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            job_id            BIGINT,
            table_name        TEXT NOT NULL,
            mode              TEXT NOT NULL CHECK (mode IN ('SNAPSHOT','INCREMENTAL','CDC')),
            row_count         BIGINT,
            started_at        TIMESTAMPTZ NOT NULL,
            finished_at       TIMESTAMPTZ,
            watermark         TEXT,
            status            TEXT NOT NULL DEFAULT 'RUNNING'
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw.db_snapshot CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.raw_web_page CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.ocr_result CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.content_hash_index CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.raw_object_2026_04 CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.raw_object CASCADE;")
