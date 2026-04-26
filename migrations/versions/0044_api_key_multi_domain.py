"""Phase 5.2.7 STEP 10 — api_key multi-domain JSONB + retailer_allowlist deprecated.

Revision ID: 0044
Revises: 0043
Create Date: 2026-04-27 06:00:00+00:00

설계 (STEP 10 답변):

  Q1. retailer_allowlist deprecation timeline:
       Phase 5 = deprecated 표시 (컬럼 유지) + agri 자동 매핑.
       Phase 6 = v1/v2 동시 운영, 자동 매핑 유지.
       Phase 7 = 사용량 확인 후 제거 검토.
  Q2. multi-domain JSONB 구조:
       domain → resources → resource_name → allowlist (확장형).
       예: {"agri": {"resources": {"prices": {"retailer_ids": [1,2]}}},
            "pos":  {"resources": {"transactions": {"shop_ids": [100]}}}}
  Q4. Redis cache fingerprint (application 레이어 확장):
       public:v1:prices:latest:{query_hash}:{retailer_allowlist_hash}
       public:v2:agri:prices:latest:{query_hash}:{scope_hash}:{schema_version}

테이블 변경:
  ctl.api_key
    + domain_resource_allowlist JSONB NOT NULL DEFAULT '{}'
    + retailer_allowlist  → deprecated 표시 (컬럼은 유지)

Migration helper:
  - retailer_allowlist 가 비어있지 않은 기존 api_key 의 값을 자동으로 agri 도메인의
    domain_resource_allowlist 로 복제 (호환).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ctl.api_key "
        "ADD COLUMN IF NOT EXISTS domain_resource_allowlist JSONB "
        "NOT NULL DEFAULT '{}'::jsonb;"
    )
    op.execute(
        "COMMENT ON COLUMN ctl.api_key.retailer_allowlist IS "
        "'DEPRECATED Phase 5 — agri 도메인의 domain_resource_allowlist 로 자동 매핑됨. "
        "Phase 7 에서 제거 검토. 새 api_key 는 domain_resource_allowlist 사용 권장.';"
    )
    op.execute(
        "COMMENT ON COLUMN ctl.api_key.domain_resource_allowlist IS "
        "'Multi-domain scope JSONB. 형식: "
        "  {\"agri\":{\"resources\":{\"prices\":{\"retailer_ids\":[1,2]}}}, "
        "   \"pos\":{\"resources\":{\"transactions\":{\"shop_ids\":[100]}}}}';"
    )

    # 기존 retailer_allowlist 가 있는 api_key 의 값을 agri 도메인으로 자동 복제.
    # (Q1 — Phase 5 호환 매핑 정책)
    op.execute(
        """
        UPDATE ctl.api_key
           SET domain_resource_allowlist =
               jsonb_set(
                 COALESCE(domain_resource_allowlist, '{}'::jsonb),
                 '{agri,resources,prices,retailer_ids}',
                 to_jsonb(retailer_allowlist),
                 TRUE
               )
         WHERE retailer_allowlist IS NOT NULL
           AND array_length(retailer_allowlist, 1) IS NOT NULL
           AND (
             domain_resource_allowlist IS NULL
             OR domain_resource_allowlist = '{}'::jsonb
             OR NOT (domain_resource_allowlist ? 'agri')
           );
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ctl_api_key_domain_allowlist_idx "
        "ON ctl.api_key USING gin (domain_resource_allowlist);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ctl.ctl_api_key_domain_allowlist_idx;")
    op.execute(
        "ALTER TABLE ctl.api_key DROP COLUMN IF EXISTS domain_resource_allowlist;"
    )
