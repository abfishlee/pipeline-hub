"""Phase 5.2.1 — source_contract (source × domain × resource × version).

Revision ID: 0034
Revises: 0033
Create Date: 2026-04-27 00:10:00+00:00

핵심 설계 (Q5 답변):
  - 한 source 가 여러 (domain, resource) contract 를 가질 수 있음 (이마트 source =
    농축산물 + 의약품 + 가전).
  - resource_selector_json 으로 raw payload 에서 어떤 resource 인지 분기.
  - compatibility_mode default = 'backward' (Avro/Confluent 표준 채택).

resource_selector_json 형식 (우선순위 = endpoint → payload.type → JSONPath):
  {
    "endpoint": "/v1/retail/prices",      # 1순위 — 명시 endpoint match
    "payload_type": "PRICE",              # 2순위 — payload.type field 비교
    "jsonpath": "$.items[?(@.cat=='F')]"  # 3순위 — fallback
  }
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.source_contract (
            contract_id          BIGSERIAL PRIMARY KEY,
            source_id            BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
            domain_code          TEXT NOT NULL REFERENCES domain.domain_definition(domain_code),
            resource_code        TEXT NOT NULL,
            schema_version       INTEGER NOT NULL DEFAULT 1,
            schema_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
            compatibility_mode   TEXT NOT NULL DEFAULT 'backward',
            resource_selector_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status               TEXT NOT NULL DEFAULT 'DRAFT',
            description          TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_source_contract_status CHECK (
                status IN ('DRAFT','REVIEW','APPROVED','PUBLISHED')
            ),
            CONSTRAINT ck_source_contract_compat CHECK (
                compatibility_mode IN ('backward','forward','full','none')
            ),
            CONSTRAINT uq_source_contract_id_version UNIQUE
                (source_id, domain_code, resource_code, schema_version)
        );
        """
    )
    op.execute(
        "CREATE INDEX domain_source_contract_lookup "
        "ON domain.source_contract (source_id, domain_code, resource_code, status);"
    )
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
              ON domain.source_contract
              TO app_rw;
        GRANT SELECT ON domain.source_contract TO app_mart_write;
        GRANT USAGE, SELECT
              ON SEQUENCE domain.source_contract_contract_id_seq TO app_rw;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain.source_contract CASCADE;")
