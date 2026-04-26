"""Phase 5.2.5 STEP 8 — Shadow Run dual-path 인프라 + Cutover Flag.

Revision ID: 0042
Revises: 0041
Create Date: 2026-04-27 04:00:00+00:00

배경 (STEP 8 답변):

  Q1. dual-active shadow — v1 응답이 사용자에게, v2 결과는 비교만 (audit).
       → audit.shadow_diff 테이블 (v1_value / v2_value / diff_kind / occurred_at)
  Q2. ADMIN 명시 승인 후 cutover.
       → ctl.cutover_flag 테이블 — (domain_code, resource_code) 별 active path.
  Q3. sha256 + partition/chunk 단위 checksum.
       → audit.t0_snapshot 테이블 — 시점/대상별 checksum 누적.
  Q4. dual-path diff 임계 — alert + cutover_block. auto-rollback X.
       → 본 migration 은 ledger 만. alert/block 로직은 application layer.

설계 메모:
  * audit.* schema 는 Phase 4.0.x 부터 존재 (audit.sql_execution_log, audit.access_log).
  * shadow_diff 는 row 단위로 *not zero* diff 만 적재. 동일 row 는 적재하지 않음.
  * cutover_flag 는 도메인-자원 별 단일 row — UPDATE 로 active_path 전환.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- audit.shadow_diff ----
    op.execute(
        """
        CREATE TABLE audit.shadow_diff (
            diff_id          BIGSERIAL PRIMARY KEY,
            domain_code      TEXT NOT NULL,
            resource_code    TEXT NOT NULL,
            request_kind     TEXT NOT NULL,
            request_key      TEXT,
            v1_value_hash    TEXT,
            v2_value_hash    TEXT,
            diff_kind        TEXT NOT NULL,
            v1_payload       JSONB,
            v2_payload       JSONB,
            extra            JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_shadow_diff_kind CHECK (
                diff_kind IN (
                    'identical_skipped','row_count_mismatch','value_mismatch',
                    'schema_mismatch','v1_only','v2_only','exception','other'
                )
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_shadow_diff_lookup "
        "ON audit.shadow_diff (domain_code, resource_code, occurred_at DESC);"
    )
    op.execute(
        "CREATE INDEX audit_shadow_diff_kind "
        "ON audit.shadow_diff (diff_kind, occurred_at DESC) "
        "WHERE diff_kind <> 'identical_skipped';"
    )
    op.execute(
        "GRANT SELECT, INSERT ON audit.shadow_diff TO app_rw; "
        "GRANT SELECT ON audit.shadow_diff TO app_mart_write; "
        "GRANT USAGE, SELECT ON SEQUENCE audit.shadow_diff_diff_id_seq TO app_rw;"
    )

    # ---- audit.t0_snapshot ----
    op.execute(
        """
        CREATE TABLE audit.t0_snapshot (
            snapshot_id      BIGSERIAL PRIMARY KEY,
            domain_code      TEXT NOT NULL,
            resource_code    TEXT NOT NULL,
            target_table     TEXT NOT NULL,
            partition_key    TEXT,
            partition_value  TEXT,
            row_count        BIGINT NOT NULL,
            checksum         TEXT NOT NULL,
            checksum_algo    TEXT NOT NULL DEFAULT 'sha256',
            captured_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            extra            JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_t0_snapshot_algo CHECK (
                checksum_algo IN ('sha256','md5')
            ),
            CONSTRAINT uq_t0_snapshot_unit UNIQUE (
                domain_code, resource_code, target_table,
                partition_key, partition_value, captured_at
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX audit_t0_snapshot_lookup "
        "ON audit.t0_snapshot (domain_code, resource_code, captured_at DESC);"
    )
    op.execute(
        "GRANT SELECT, INSERT ON audit.t0_snapshot TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE audit.t0_snapshot_snapshot_id_seq TO app_rw;"
    )

    # ---- ctl.cutover_flag ----
    op.execute(
        """
        CREATE TABLE ctl.cutover_flag (
            domain_code      TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            resource_code    TEXT NOT NULL,
            active_path      TEXT NOT NULL DEFAULT 'v1',
            v2_read_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
            v1_write_disabled BOOLEAN NOT NULL DEFAULT FALSE,
            shadow_started_at TIMESTAMPTZ,
            cutover_at       TIMESTAMPTZ,
            approved_by      BIGINT REFERENCES ctl.app_user(user_id),
            notes            TEXT,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (domain_code, resource_code),
            CONSTRAINT ck_cutover_active CHECK (
                active_path IN ('v1','v2','shadow')
            )
        );
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON ctl.cutover_flag TO app_rw; "
        "GRANT SELECT ON ctl.cutover_flag TO app_mart_write;"
    )

    # 기본 seed — agri 의 핵심 resource 3종 = shadow 시작 (active='v1', v2_read=FALSE).
    op.execute(
        """
        INSERT INTO ctl.cutover_flag
            (domain_code, resource_code, active_path, v2_read_enabled,
             v1_write_disabled, notes)
        SELECT 'agri', rc, 'v1', FALSE, FALSE, 'STEP 8 baseline'
          FROM (VALUES ('PRICE_FACT'),('DAILY_AGG'),('PRODUCT_MAPPING')) AS t(rc)
         WHERE EXISTS (
            SELECT 1 FROM domain.domain_definition WHERE domain_code = 'agri'
         )
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ctl.cutover_flag CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.t0_snapshot CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit.shadow_diff CASCADE;")
