"""Phase 4.2.7 — Partition Archive 자동화: ctl.partition_archive_log.

Revision ID: 0028
Revises: 0027
Create Date: 2026-04-26 22:00:00+00:00

매월 1일 04:00 KST 배치가 13 개월+ 경과 partition 을 detect → Object Storage cold
tier 로 복제 → checksum 검증 → DETACH → DROP. 본 테이블이 그 이력을 보관 + 운영자
복원 시 흔적.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ctl.partition_archive_log (
            archive_id      BIGSERIAL PRIMARY KEY,
            schema_name     TEXT NOT NULL,
            table_name      TEXT NOT NULL,
            partition_name  TEXT NOT NULL,
            row_count       BIGINT,
            byte_size       BIGINT,
            checksum        TEXT,
            object_uri      TEXT,
            status          TEXT NOT NULL DEFAULT 'PENDING',
            archived_at     TIMESTAMPTZ,
            restored_at     TIMESTAMPTZ,
            restored_to     TEXT,
            archived_by     BIGINT REFERENCES ctl.app_user(user_id),
            restored_by     BIGINT REFERENCES ctl.app_user(user_id),
            error_message   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_partition_archive_status CHECK (
                status IN ('PENDING','COPYING','COPIED','DETACHED',
                           'DROPPED','RESTORED','FAILED')
            ),
            CONSTRAINT uq_partition_archive_partition UNIQUE (
                schema_name, table_name, partition_name
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX ctl_partition_archive_status_idx "
        "ON ctl.partition_archive_log (status, archived_at DESC NULLS LAST);"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON ctl.partition_archive_log TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE ctl.partition_archive_log_archive_id_seq "
        "      TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ctl.partition_archive_log CASCADE;")
