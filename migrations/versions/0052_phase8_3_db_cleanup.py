"""Phase 8.3 — DB cleanup (운영 이관 전 spike/구버전 흔적 제거).

Revision ID: 0052
Revises: 0051
Create Date: 2026-04-27 00:00:00+00:00

dp_postgres 실측 검증 후 안전 정리 3건:

  1. iot_spike_mart schema 전체 DROP (Phase 5.2.1a spike 잔재, ADR-0017 채택 후 미사용)
  2. ctl.connector 테이블 DROP (v1 초기 설계, v2 generic 플랫폼이 대체)
  3. ctl.api_key.expired_at 컬럼 DROP (migration 0026 호환 기간 종료, 100% null)

미래 기능 (CDC, crowd payout, provider usage 등) 은 0 rows 이지만 사용 예정이므로 유지.
pgvector IVFFLAT 재정책, 파티션 rolling, matview 추가는 별도 PR (PHASE_8_3 §6).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. iot_spike_mart schema 제거 ─────────────────────────────────
    # 0030_spike_iot.py 의 downgrade 와 동일.
    # 4 테이블 (sensor_v1 / reading_v1 / embedding_512 / embedding_1024) +
    # FK / index / sequence 모두 CASCADE 로 정리.
    op.execute("DROP SCHEMA IF EXISTS iot_spike_mart CASCADE;")

    # ── 2. ctl.connector 테이블 제거 ──────────────────────────────────
    # FK ctl.connector.source_id → ctl.data_source.source_id 자동 정리.
    # CHECK constraint connector_kind_check, sequence connector_id_seq 도 함께 정리.
    op.execute("DROP TABLE IF EXISTS ctl.connector CASCADE;")

    # ── 3. ctl.api_key.expired_at 컬럼 제거 ───────────────────────────
    # migration 0026 에서 expires_at 도입 + 기존 expired_at 값 mig 완료.
    # 코드는 모두 expires_at 사용 (Phase 7+).
    op.execute("ALTER TABLE ctl.api_key DROP COLUMN IF EXISTS expired_at;")


def downgrade() -> None:
    # 데이터 복구 불가 — 빈 객체만 재생성.

    # ── 3. ctl.api_key.expired_at 재추가 ──────────────────────────────
    op.execute(
        "ALTER TABLE ctl.api_key ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ;"
    )

    # ── 2. ctl.connector 재생성 (0002_ctl_tables.py 정의 복원) ────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ctl.connector (
            connector_id   BIGSERIAL PRIMARY KEY,
            source_id      BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            connector_kind TEXT NOT NULL,
            secret_ref     TEXT NOT NULL,
            config_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT connector_kind_check
                CHECK (connector_kind IN ('PG','MYSQL','ORACLE','MSSQL','HTTP','S3'))
        );
        """
    )

    # ── 1. iot_spike_mart schema 재생성 (0030_spike_iot.py 의 upgrade 동일) ─
    op.execute("CREATE SCHEMA IF NOT EXISTS iot_spike_mart;")
    op.execute(
        """
        CREATE TABLE iot_spike_mart.sensor_v1 (
            sensor_id        BIGSERIAL PRIMARY KEY,
            device_model_id  TEXT NOT NULL,
            location         TEXT,
            unit             TEXT NOT NULL,
            registered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sensor_model_location UNIQUE (device_model_id, location)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE iot_spike_mart.reading_v1 (
            reading_id     BIGSERIAL PRIMARY KEY,
            sensor_id      BIGINT NOT NULL REFERENCES iot_spike_mart.sensor_v1(sensor_id),
            observed_at    TIMESTAMPTZ NOT NULL,
            value          NUMERIC(14, 4) NOT NULL,
            quality_score  NUMERIC(5, 2)
        );
        """
    )
    op.execute(
        "CREATE INDEX iot_spike_reading_sensor_time "
        "ON iot_spike_mart.reading_v1 (sensor_id, observed_at DESC);"
    )
    op.execute(
        """
        CREATE TABLE iot_spike_mart.embedding_512 (
            sensor_id   BIGINT PRIMARY KEY REFERENCES iot_spike_mart.sensor_v1(sensor_id),
            embedding   vector(512) NOT NULL,
            model_name  TEXT NOT NULL DEFAULT 'spike-512',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE iot_spike_mart.embedding_1024 (
            sensor_id   BIGINT PRIMARY KEY REFERENCES iot_spike_mart.sensor_v1(sensor_id),
            embedding   vector(1024) NOT NULL,
            model_name  TEXT NOT NULL DEFAULT 'spike-1024',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        GRANT USAGE ON SCHEMA iot_spike_mart TO app_rw;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON ALL TABLES IN SCHEMA iot_spike_mart TO app_rw;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA iot_spike_mart TO app_rw;
        """
    )
