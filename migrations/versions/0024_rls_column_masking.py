"""Phase 4.2.4 — RLS + 컬럼 마스킹: 4 PG role 분리 + masking VIEW + RLS 정책.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-26 16:00:00+00:00

설계:
  1. 4 NOLOGIN PG role 신설 — 애플리케이션 connection user (`app`) 가 SET ROLE 로
     필요한 권한 표면을 골라 잡는다.
       - app_rw          — 일반 API (기존 동작 유지, 모든 schema RW)
       - app_mart_write  — LOAD_MASTER + APPROVED SQL 의 mart upsert 전용
       - app_readonly    — SQL Studio sandbox (replica 라우팅 후 read-only)
       - app_public      — 외부 API key 의 mart 조회 전용 (RLS + 컬럼 마스킹)

  2. 컬럼 마스킹은 *masking VIEW* 로 처리. 운영 코드는 view 를 SELECT, 그 view 가
     `current_role` 에 따라 컬럼 값을 평문 또는 마스크로 반환.
       - mart.retailer_master_view — business_no / head_office_addr 마스킹
       - mart.seller_master_view   — address 마스킹 (sido/sigungu 는 노출)

  3. Row-level security 는 *retailer_id 가 명시된 테이블* 에 적용.
       - mart.seller_master    — retailer_id 컬럼 보유
       - mart.product_mapping  — retailer_id 컬럼 보유 (NOT NULL)
     api_key 별 허용 retailer 를 `current_setting('app.retailer_allowlist')` 로 주입.
     allowlist 비어 있으면 모든 row 차단 (보안 우선 — "미포함 시 보이지 않음").

  4. ctl.api_key 에 `retailer_allowlist BIGINT[] DEFAULT '{}'` 컬럼 추가.

다운그레이드:
  RLS 정책 + masking view 제거. PG role 은 그대로 유지 (다른 환경에서 grant 가
  잔존할 수 있음 — DROP 시 cascade 위험 차단). 운영자가 명시적으로 DROP ROLE 결정.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PG_ROLES: tuple[str, ...] = (
    "app_rw",
    "app_mart_write",
    "app_readonly",
    "app_public",
)


def _ensure_role(role: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            CREATE ROLE {role} NOLOGIN;
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    # 1) ctl.api_key 에 retailer_allowlist 컬럼 추가.
    op.execute(
        """
        ALTER TABLE ctl.api_key
            ADD COLUMN IF NOT EXISTS retailer_allowlist BIGINT[] NOT NULL DEFAULT '{}'::bigint[];
        """
    )

    # 2) 4 PG role 생성 (idempotent).
    for r in PG_ROLES:
        op.execute(_ensure_role(r))

    # 3) connection user (current_user 기준) 에게 모든 role grant — SET ROLE 가능하게.
    #    Migration 은 보통 superuser 또는 owner (app) 로 돌아가므로 current_user 사용.
    op.execute(
        """
        DO $$
        DECLARE
            r TEXT;
            cur_user TEXT;
        BEGIN
            SELECT current_user INTO cur_user;
            FOREACH r IN ARRAY ARRAY['app_rw', 'app_mart_write', 'app_readonly', 'app_public']
            LOOP
                EXECUTE format('GRANT %I TO %I', r, cur_user);
            END LOOP;
        END
        $$;
        """
    )

    # 4) schema USAGE — 4 role 모두 mart/ctl/wf 등 메타 schema 접근 필요.
    op.execute(
        """
        GRANT USAGE ON SCHEMA mart, ctl, wf, dq, run, stg, raw, audit
              TO app_rw, app_mart_write, app_readonly, app_public;
        """
    )

    # 5) app_rw — 기존 동작 유지: 모든 schema CRUD.
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
              ON ALL TABLES IN SCHEMA mart, ctl, wf, dq, run, stg, raw, audit
              TO app_rw;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA
              mart, ctl, wf, dq, run, stg, raw, audit
              TO app_rw;
        """
    )

    # 6) app_mart_write — mart upsert 만.
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mart
              TO app_mart_write;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA mart TO app_mart_write;
        """
    )

    # 7) app_readonly — mart/wf/stg SELECT (sandbox).
    op.execute(
        """
        GRANT SELECT ON ALL TABLES IN SCHEMA mart, wf, stg TO app_readonly;
        """
    )

    # 8) app_public — masking view + 일부 mart 테이블 SELECT (RLS 적용).
    #    raw 컬럼 직접 노출 금지 — 운영 코드는 view 만 사용.
    op.execute(
        """
        GRANT SELECT ON
              mart.product_master,
              mart.standard_code,
              mart.product_mapping,
              mart.seller_master,
              mart.price_fact,
              mart.retailer_master
              TO app_public;
        """
    )

    # 9) Masking views — current_role 기반 평문/마스크 분기.
    #    `security_invoker=true` (PG 15+) — 기본은 view 소유자 권한으로 실행되어
    #    RLS 가 invoker 가 아닌 owner 역할로 평가됨. invoker 의 SET LOCAL ROLE 이
    #    내부 RLS 정책에 반영되려면 본 옵션이 필수.
    op.execute(
        """
        CREATE OR REPLACE VIEW mart.retailer_master_view
        WITH (security_invoker = true) AS
        SELECT
            retailer_id,
            retailer_code,
            retailer_name,
            retailer_type,
            CASE
                WHEN current_role IN ('app_public', 'app_readonly')
                    THEN regexp_replace(business_no, '\\d', '*', 'g')
                ELSE business_no
            END AS business_no,
            CASE
                WHEN current_role IN ('app_public', 'app_readonly') THEN NULL
                ELSE head_office_addr
            END AS head_office_addr,
            meta_json,
            created_at
        FROM mart.retailer_master;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW mart.seller_master_view
        WITH (security_invoker = true) AS
        SELECT
            seller_id,
            retailer_id,
            seller_code,
            seller_name,
            channel,
            region_sido,
            region_sigungu,
            CASE
                WHEN current_role IN ('app_public', 'app_readonly') THEN NULL
                ELSE address
            END AS address,
            geo_point,
            meta_json,
            created_at
        FROM mart.seller_master;
        """
    )
    op.execute(
        """
        GRANT SELECT ON mart.retailer_master_view, mart.seller_master_view
              TO app_rw, app_mart_write, app_readonly, app_public;
        """
    )

    # 10) RLS — retailer_id 기반 row 필터 (app_public / app_readonly).
    #     app_rw / app_mart_write 는 BYPASSRLS 가 아니므로 정책으로 별도 통과 보장.
    for tbl in ("mart.seller_master", "mart.product_mapping"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")

    # 11) 정책: app_rw / app_mart_write — 모두 통과.
    op.execute(
        """
        CREATE POLICY rls_seller_full
            ON mart.seller_master
            FOR ALL
            TO app_rw, app_mart_write
            USING (true)
            WITH CHECK (true);
        """
    )
    op.execute(
        """
        CREATE POLICY rls_mapping_full
            ON mart.product_mapping
            FOR ALL
            TO app_rw, app_mart_write
            USING (true)
            WITH CHECK (true);
        """
    )

    # 12) 정책: app_public / app_readonly — current_setting 기반 retailer_allowlist.
    #     allowlist 비어 있으면 0 row (보안 기본값).
    op.execute(
        """
        CREATE POLICY rls_seller_allowlist
            ON mart.seller_master
            FOR SELECT
            TO app_public, app_readonly
            USING (
                retailer_id IS NOT NULL
                AND retailer_id = ANY (
                    NULLIF(current_setting('app.retailer_allowlist', true), '')::bigint[]
                )
            );
        """
    )
    op.execute(
        """
        CREATE POLICY rls_mapping_allowlist
            ON mart.product_mapping
            FOR SELECT
            TO app_public, app_readonly
            USING (
                retailer_id = ANY (
                    NULLIF(current_setting('app.retailer_allowlist', true), '')::bigint[]
                )
            );
        """
    )

    # 13) future-proofing — 새 mart 테이블 자동 GRANT.
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA mart
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw, app_mart_write;
        ALTER DEFAULT PRIVILEGES IN SCHEMA mart
            GRANT SELECT ON TABLES TO app_readonly;
        """
    )


def downgrade() -> None:
    # 정책 + RLS 해제.
    op.execute("DROP POLICY IF EXISTS rls_mapping_allowlist ON mart.product_mapping;")
    op.execute("DROP POLICY IF EXISTS rls_mapping_full ON mart.product_mapping;")
    op.execute("DROP POLICY IF EXISTS rls_seller_allowlist ON mart.seller_master;")
    op.execute("DROP POLICY IF EXISTS rls_seller_full ON mart.seller_master;")
    op.execute("ALTER TABLE mart.product_mapping DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE mart.product_mapping NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE mart.seller_master DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE mart.seller_master NO FORCE ROW LEVEL SECURITY;")

    # masking views 제거.
    op.execute("DROP VIEW IF EXISTS mart.seller_master_view;")
    op.execute("DROP VIEW IF EXISTS mart.retailer_master_view;")

    # default privileges 회수.
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA mart
            REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_rw, app_mart_write;
        ALTER DEFAULT PRIVILEGES IN SCHEMA mart
            REVOKE SELECT ON TABLES FROM app_readonly;
        """
    )

    # ctl.api_key.retailer_allowlist 제거.
    op.execute("ALTER TABLE ctl.api_key DROP COLUMN IF EXISTS retailer_allowlist;")

    # NOTE: PG role 은 보존 — 다른 환경에 grant 가 남아 있을 수 있고 cascade 위험.
