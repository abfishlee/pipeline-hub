"""Phase 6.1 — generic Public API Connector.

Revision ID: 0046
Revises: 0045
Create Date: 2026-04-27 09:00:00+00:00

핵심 설계 (사용자 결정 — 2026-04-27):

  > "사용자는 API 주소 + KEY값 + 파라미터 + 수집 주기만 설정하면 끝.
  >  KAMIS / 식약처 / 통계청 등 *어떤 API 든* 코딩 없이 row 1건 INSERT 로 추가."

  → 절대 KAMIS_x.py / sklab_y.py 같은 *공급자별 모듈* 만들지 않음.
  → 모든 사용자 입력은 본 테이블의 컬럼/JSONB 로만 표현.
  → engine 은 단 1개 (`app/domain/public_api/engine.py`).

테이블:
  domain.public_api_connector — 사용자 입력 spec (모든 API 공통)
  domain.public_api_run        — 호출 이력 (preview / dry-run / scheduled)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # domain.public_api_connector
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE domain.public_api_connector (
            connector_id      BIGSERIAL PRIMARY KEY,
            domain_code       TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            resource_code     TEXT NOT NULL,
            name              TEXT NOT NULL,
            description       TEXT,
            -- HTTP 기본
            endpoint_url      TEXT NOT NULL,
            http_method       TEXT NOT NULL DEFAULT 'GET',
            -- 인증
            auth_method       TEXT NOT NULL DEFAULT 'none',
            auth_param_name   TEXT,
            secret_ref        TEXT,
            request_headers   JSONB NOT NULL DEFAULT '{}'::jsonb,
            -- request 본체 (templating: {ymd} {page} {cursor} 등)
            query_template    JSONB NOT NULL DEFAULT '{}'::jsonb,
            body_template     JSONB,
            -- pagination
            pagination_kind   TEXT NOT NULL DEFAULT 'none',
            pagination_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            -- response 처리
            response_format   TEXT NOT NULL DEFAULT 'json',
            response_path     TEXT,
            -- 운영 정책
            timeout_sec       INTEGER NOT NULL DEFAULT 15,
            retry_max         INTEGER NOT NULL DEFAULT 2,
            rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
            -- 수집 주기 (옵션)
            schedule_cron     TEXT,
            schedule_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
            -- 상태머신 (Phase 5.2.0 가드레일과 일치)
            status            TEXT NOT NULL DEFAULT 'DRAFT',
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_by        BIGINT REFERENCES ctl.app_user(user_id),
            approved_by       BIGINT REFERENCES ctl.app_user(user_id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_public_api_http_method CHECK (
                http_method IN ('GET','POST')
            ),
            CONSTRAINT ck_public_api_auth_method CHECK (
                auth_method IN ('none','query_param','header','basic','bearer')
            ),
            CONSTRAINT ck_public_api_pagination CHECK (
                pagination_kind IN ('none','page_number','offset_limit','cursor')
            ),
            CONSTRAINT ck_public_api_response_format CHECK (
                response_format IN ('json','xml')
            ),
            CONSTRAINT ck_public_api_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_public_api_connector_lookup "
        "ON domain.public_api_connector (domain_code, resource_code, status);"
    )
    op.execute(
        "CREATE INDEX domain_public_api_connector_schedule "
        "ON domain.public_api_connector (schedule_cron, schedule_enabled) "
        "WHERE schedule_enabled = TRUE AND status = 'PUBLISHED';"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON domain.public_api_connector TO app_rw; "
        "GRANT SELECT ON domain.public_api_connector TO app_mart_write; "
        "GRANT USAGE, SELECT ON SEQUENCE "
        "  domain.public_api_connector_connector_id_seq TO app_rw;"
    )

    # ------------------------------------------------------------------
    # domain.public_api_run — 호출 이력
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE domain.public_api_run (
            run_id            BIGSERIAL PRIMARY KEY,
            connector_id      BIGINT NOT NULL REFERENCES domain.public_api_connector(connector_id)
                              ON DELETE CASCADE,
            run_kind          TEXT NOT NULL,
            runtime_params    JSONB NOT NULL DEFAULT '{}'::jsonb,
            request_summary   JSONB NOT NULL DEFAULT '{}'::jsonb,
            http_status       INTEGER,
            row_count         INTEGER,
            duration_ms       INTEGER,
            error_message     TEXT,
            sample_rows       JSONB,
            raw_object_id     BIGINT,
            triggered_by      BIGINT REFERENCES ctl.app_user(user_id),
            started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at      TIMESTAMPTZ,
            CONSTRAINT ck_public_api_run_kind CHECK (
                run_kind IN ('test','dry_run','scheduled','manual_publish')
            )
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_public_api_run_recent "
        "ON domain.public_api_run (connector_id, started_at DESC);"
    )
    op.execute(
        "CREATE INDEX domain_public_api_run_failed "
        "ON domain.public_api_run (started_at DESC) "
        "WHERE error_message IS NOT NULL;"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON domain.public_api_run TO app_rw; "
        "GRANT USAGE, SELECT ON SEQUENCE "
        "  domain.public_api_run_run_id_seq TO app_rw;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.public_api_run CASCADE;")
    op.execute("DROP TABLE IF EXISTS domain.public_api_connector CASCADE;")
