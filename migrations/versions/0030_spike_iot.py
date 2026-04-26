"""Phase 5.2.1a Spike — iot_spike_mart schema for Hybrid Registry PoC.

Revision ID: 0030
Revises: 0029
Create Date: 2026-04-26 23:30:00+00:00

**SPIKE 한정** — 본 migration 은 ORM/Core 전략 검증용 PoC 데이터베이스 객체.
Spike 종료 + ADR-0017 채택 후, Phase 5.2.1 의 정식 `domain.*` 스키마가 도입되면
본 migration 은 *downgrade* 로 정리 (또는 정식 spike-cleanup migration 으로 대체).

생성:
  - schema `iot_spike_mart`
  - `iot_spike_mart.sensor_v1` (master)
  - `iot_spike_mart.reading_v1` (fact, sensor_id FK)
  - `iot_spike_mart.embedding_512` (도메인별 vector — pgvector 차원 변동 검증용)
  - `iot_spike_mart.embedding_1024` (다른 차원 — Hybrid registry 가 차원 N개 지원)

동기:
  - v1 mart.* 와 *완전 분리* — 같은 PG 안에서 schema 만 분리.
  - 차원 다른 vector 테이블이 *같은 도메인* 안에 공존 가능한지 (HyperCLOVA 1536 +
    OpenAI 3072 같은 케이스) 검증.
  - SQLAlchemy Core + reflected Table 로 ORM 모델 없이 SELECT/INSERT/JOIN 가능 검증.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS iot_spike_mart;")

    # 1) sensor master.
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

    # 2) reading fact.
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

    # 3) 두 가지 차원의 vector 테이블 — Hybrid registry 의 *동적 차원* 검증.
    #    pgvector 확장이 v1 에서 이미 활성화 (migration 0012). 그대로 사용.
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

    # 4) Phase 4.2.4 의 4 PG role 매트릭스에 합류 (spike 용 — RW 만).
    op.execute(
        """
        GRANT USAGE ON SCHEMA iot_spike_mart TO app_rw;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON ALL TABLES IN SCHEMA iot_spike_mart TO app_rw;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA iot_spike_mart TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS iot_spike_mart CASCADE;")
