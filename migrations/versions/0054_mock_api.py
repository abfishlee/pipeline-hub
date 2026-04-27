"""Phase 8.6 — Mock API 자체 검증 도구.

Revision ID: 0054
Revises: 0053
Create Date: 2026-04-27 14:00:00+00:00

운영자가 외부 API 의존 없이 시스템을 검증할 수 있도록, 우리 시스템 안에 *외부 API
흉내* 를 내는 endpoint 를 만든다. mock 응답을 사용자가 등록하면 같은 시스템의
Source/API Connector 로 호출 가능.

table:
  ctl.mock_api_endpoint
    mock_id           BIGSERIAL PK
    code              TEXT UNIQUE — URL slug (예: 'sample_iot_sensors')
    name              TEXT
    description       TEXT
    response_format   TEXT — 'json' | 'xml' | 'csv' | 'tsv' | 'text'
    response_body     TEXT — 응답 본문 (사용자가 입력)
    response_headers  JSONB — 추가 헤더 (Content-Type 등)
    status_code       INT (default 200)
    delay_ms          INT (default 0) — 응답 지연 시뮬레이션
    is_active         BOOLEAN (default true)
    call_count        BIGINT (default 0) — 누적 호출수
    last_called_at    TIMESTAMPTZ
    created_by        BIGINT
    created_at        TIMESTAMPTZ
    updated_at        TIMESTAMPTZ
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 8.6 — domain.public_api_connector.response_format CHECK 확장 (json/xml → 7종).
    op.execute(
        "ALTER TABLE domain.public_api_connector "
        "DROP CONSTRAINT IF EXISTS ck_public_api_response_format;"
    )
    op.execute(
        "ALTER TABLE domain.public_api_connector "
        "ADD CONSTRAINT ck_public_api_response_format "
        "CHECK (response_format IN ('json','xml','csv','tsv','text','excel','binary'));"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ctl.mock_api_endpoint (
            mock_id          BIGSERIAL PRIMARY KEY,
            code             TEXT NOT NULL UNIQUE,
            name             TEXT NOT NULL,
            description      TEXT,
            response_format  TEXT NOT NULL DEFAULT 'json',
            response_body    TEXT NOT NULL,
            response_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
            status_code      INT NOT NULL DEFAULT 200,
            delay_ms         INT NOT NULL DEFAULT 0,
            is_active        BOOLEAN NOT NULL DEFAULT TRUE,
            call_count       BIGINT NOT NULL DEFAULT 0,
            last_called_at   TIMESTAMPTZ,
            created_by       BIGINT REFERENCES ctl.app_user(user_id),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_mock_api_format
                CHECK (response_format IN ('json','xml','csv','tsv','text')),
            CONSTRAINT ck_mock_api_status
                CHECK (status_code BETWEEN 100 AND 599),
            CONSTRAINT ck_mock_api_code_format
                CHECK (code ~ '^[a-z][a-z0-9_]{1,62}$'),
            CONSTRAINT ck_mock_api_delay
                CHECK (delay_ms BETWEEN 0 AND 30000)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mock_api_active "
        "ON ctl.mock_api_endpoint (is_active, code);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ctl.mock_api_endpoint CASCADE;")
    op.execute(
        "ALTER TABLE domain.public_api_connector "
        "DROP CONSTRAINT IF EXISTS ck_public_api_response_format;"
    )
    op.execute(
        "ALTER TABLE domain.public_api_connector "
        "ADD CONSTRAINT ck_public_api_response_format "
        "CHECK (response_format IN ('json','xml'));"
    )
