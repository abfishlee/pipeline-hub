"""Phase 4.2.3 — CDC PoC: raw.db_cdc_event + ctl.cdc_subscription + ctl.data_source.cdc_enabled.

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-26 18:00:00+00:00

경로 A 채택 (wal2json + logical replication slot 직접 구독). Kafka/Debezium 미도입.
ADR-0013 의 회수 조건 만족 시 경로 B 재평가.

스키마:
  - raw.db_cdc_event   — CDC 이벤트 1건 단위 적재. (source_id, lsn) UNIQUE.
  - ctl.cdc_subscription — slot 메타 + lag 모니터링.
  - ctl.data_source 에 cdc_enabled BOOLEAN 추가.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) data_source.cdc_enabled 추가.
    op.execute(
        "ALTER TABLE ctl.data_source "
        "ADD COLUMN IF NOT EXISTS cdc_enabled BOOLEAN NOT NULL DEFAULT FALSE;"
    )

    # 2) raw.db_cdc_event — CDC 이벤트 적재.
    op.execute(
        """
        CREATE TABLE raw.db_cdc_event (
            event_id      BIGSERIAL PRIMARY KEY,
            source_id     BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            schema_name   TEXT NOT NULL,
            table_name    TEXT NOT NULL,
            op            CHAR(1) NOT NULL,
            pk_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
            before_json   JSONB,
            after_json    JSONB,
            lsn           TEXT NOT NULL,
            occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_db_cdc_event_op CHECK (op IN ('I','U','D')),
            CONSTRAINT uq_db_cdc_event_source_lsn UNIQUE (source_id, lsn)
        );
        """
    )
    op.execute(
        "CREATE INDEX raw_db_cdc_event_table_idx "
        "ON raw.db_cdc_event (source_id, schema_name, table_name, occurred_at DESC);"
    )

    # 3) ctl.cdc_subscription — slot 메타 + lag.
    op.execute(
        """
        CREATE TABLE ctl.cdc_subscription (
            subscription_id     BIGSERIAL PRIMARY KEY,
            source_id           BIGINT NOT NULL UNIQUE REFERENCES ctl.data_source(source_id),
            slot_name           TEXT NOT NULL UNIQUE,
            plugin              TEXT NOT NULL DEFAULT 'wal2json',
            publication_name    TEXT,
            enabled             BOOLEAN NOT NULL DEFAULT FALSE,
            last_committed_lsn  TEXT,
            last_lag_bytes      BIGINT,
            last_polled_at      TIMESTAMPTZ,
            snapshot_lsn        TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_cdc_subscription_plugin CHECK (plugin IN ('wal2json'))
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_cdc_subscription_lag_idx "
        "ON ctl.cdc_subscription (enabled, last_lag_bytes DESC);"
    )

    # 4) Phase 4.2.4 의 기본 GRANT 매트릭스에 새 테이블 합류.
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON raw.db_cdc_event, ctl.cdc_subscription
              TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE raw.db_cdc_event_event_id_seq,
                                          ctl.cdc_subscription_subscription_id_seq
              TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw.db_cdc_event CASCADE;")
    op.execute("DROP TABLE IF EXISTS ctl.cdc_subscription CASCADE;")
    op.execute("ALTER TABLE ctl.data_source DROP COLUMN IF EXISTS cdc_enabled;")
