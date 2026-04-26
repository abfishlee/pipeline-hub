"""Phase 5.2.6 STEP 9 — pos_mart.* schema + payment_method 표준코드 + 샘플 mock 데이터.

Revision ID: 0043
Revises: 0042
Create Date: 2026-04-27 05:00:00+00:00

추상화 검증 (PHASE_5_PROMPTS.md STEP 9):
  * 본 migration 은 *코드 수정 0* 으로 새 도메인을 받을 수 있는지 검증의 일부.
  * pos.yaml + 본 migration 만으로 v2 generic engine 이 동작해야 함.

테이블:
  pos_mart.pos_store              — 매장 마스터
  pos_mart.pos_terminal           — POS 터미널 마스터
  pos_mart.pos_transaction        — 거래 fact (append, ymd partition 권장)
  pos_mart.std_payment_method     — 결제수단 표준코드 + alias
  pos_mart.std_store_channel      — 매장 채널 표준코드

mock seed:
  * payment_method 7종 (CARD/CASH/MOBILE_PAY/POINT/VOUCHER/COUPON/OTHER) +
    한국어/영어 alias 약 15종.
  * 매장 3곳 / 터미널 5대 / 거래 50건.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text

revision: str = "0043"
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- schema ----
    op.execute("CREATE SCHEMA IF NOT EXISTS pos_mart;")
    op.execute("GRANT USAGE ON SCHEMA pos_mart TO app_rw, app_mart_write;")

    # ---- master tables ----
    op.execute(
        """
        CREATE TABLE pos_mart.pos_store (
            store_id        BIGSERIAL PRIMARY KEY,
            store_code      TEXT NOT NULL UNIQUE,
            store_name      TEXT NOT NULL,
            store_channel   TEXT,
            sido            TEXT,
            sigungu         TEXT,
            opened_at       DATE,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE pos_mart.pos_terminal (
            terminal_id     BIGSERIAL PRIMARY KEY,
            terminal_code   TEXT NOT NULL UNIQUE,
            store_id        BIGINT NOT NULL REFERENCES pos_mart.pos_store(store_id),
            terminal_kind   TEXT,
            installed_at    TIMESTAMPTZ,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # ---- transaction fact ----
    op.execute(
        """
        CREATE TABLE pos_mart.pos_transaction (
            txn_id              BIGSERIAL PRIMARY KEY,
            store_id            BIGINT NOT NULL REFERENCES pos_mart.pos_store(store_id),
            terminal_id         BIGINT REFERENCES pos_mart.pos_terminal(terminal_id),
            txn_at              TIMESTAMPTZ NOT NULL,
            ymd                 TEXT NOT NULL,
            payment_method_raw  TEXT NOT NULL,
            payment_method_std  TEXT,
            amount_won          NUMERIC(14,2) NOT NULL,
            discount_won        NUMERIC(14,2) NOT NULL DEFAULT 0,
            tax_won             NUMERIC(14,2) NOT NULL DEFAULT 0,
            item_count          INTEGER NOT NULL DEFAULT 1,
            customer_id         TEXT,
            extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_pos_txn_amount_nonneg CHECK (amount_won >= 0)
        );
        """
    )
    op.execute(
        "CREATE INDEX pos_mart_txn_ymd_idx ON pos_mart.pos_transaction (ymd, store_id);"
    )
    op.execute(
        "CREATE INDEX pos_mart_txn_payment_idx "
        "ON pos_mart.pos_transaction (payment_method_std, ymd);"
    )

    # ---- 표준코드 ----
    op.execute(
        """
        CREATE TABLE pos_mart.std_payment_method (
            std_code        TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            description     TEXT,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE pos_mart.std_payment_method_alias (
            alias_id        BIGSERIAL PRIMARY KEY,
            std_code        TEXT NOT NULL REFERENCES pos_mart.std_payment_method(std_code),
            alias           TEXT NOT NULL,
            CONSTRAINT uq_payment_alias UNIQUE (alias)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE pos_mart.std_store_channel (
            std_code        TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            description     TEXT,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE
        );
        """
    )

    # ---- 권한 ----
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pos_mart TO app_rw; "
        "GRANT SELECT ON ALL TABLES IN SCHEMA pos_mart TO app_mart_write; "
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA pos_mart TO app_rw;"
    )

    # ---- domain registry seed ----
    op.execute(
        """
        INSERT INTO domain.domain_definition
            (domain_code, name, description, schema_yaml, status, version)
        VALUES
            ('pos', 'POS 거래 로그',
             'Phase 5.2.6 추상화 검증용 시험지 도메인 (mock data)',
             '{}'::jsonb, 'PUBLISHED', 1)
        ON CONFLICT DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO domain.standard_code_namespace
            (domain_code, name, description, std_code_table)
        VALUES
            ('pos', 'PAYMENT_METHOD',
             '결제수단 7종 + alias',
             'pos_mart.std_payment_method'),
            ('pos', 'STORE_CHANNEL',
             '매장 채널 (HYPERMARKET/SUPERMARKET/CONVENIENCE/ONLINE)',
             'pos_mart.std_store_channel')
        ON CONFLICT DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO domain.resource_definition
            (domain_code, resource_code, fact_table, canonical_table,
             standard_code_namespace, status, version)
        VALUES
            ('pos','TRANSACTION','pos_mart.pos_transaction', NULL,
             'PAYMENT_METHOD','PUBLISHED',1),
            ('pos','STORE', NULL, 'pos_mart.pos_store',
             'STORE_CHANNEL','PUBLISHED',1),
            ('pos','TERMINAL', NULL, 'pos_mart.pos_terminal',
             NULL,'PUBLISHED',1)
        ON CONFLICT DO NOTHING;
        """
    )

    # ---- payment_method 표준코드 7종 + alias ----
    pm_seed = (
        ("CARD", "신용/체크카드", "신용카드 + 체크카드 + 직불카드 통합", 1),
        ("CASH", "현금", "현금 결제", 2),
        ("MOBILE_PAY", "간편결제", "네이버페이/카카오페이/페이코 등", 3),
        ("POINT", "포인트", "OK캐쉬백/멤버십 포인트", 4),
        ("VOUCHER", "상품권", "지류/모바일 상품권", 5),
        ("COUPON", "쿠폰", "할인쿠폰 (현금성)", 6),
        ("OTHER", "기타", "분류되지 않은 결제수단", 99),
    )
    bind = op.get_bind()
    pm_stmt = text(
        "INSERT INTO pos_mart.std_payment_method "
        "(std_code, display_name, description, sort_order) "
        "VALUES (:c, :n, :d, :o) ON CONFLICT DO NOTHING"
    ).bindparams(
        bindparam("c"), bindparam("n"), bindparam("d"), bindparam("o")
    )
    for code, name, desc, order in pm_seed:
        bind.execute(pm_stmt, {"c": code, "n": name, "d": desc, "o": order})

    aliases = (
        ("CARD", "CARD"),
        ("CARD", "신용카드"),
        ("CARD", "카드"),
        ("CARD", "credit_card"),
        ("CARD", "체크카드"),
        ("CASH", "CASH"),
        ("CASH", "현금"),
        ("CASH", "cash"),
        ("MOBILE_PAY", "간편결제"),
        ("MOBILE_PAY", "네이버페이"),
        ("MOBILE_PAY", "카카오페이"),
        ("MOBILE_PAY", "페이코"),
        ("MOBILE_PAY", "삼성페이"),
        ("POINT", "포인트"),
        ("POINT", "OK캐쉬백"),
        ("POINT", "멤버십포인트"),
        ("VOUCHER", "상품권"),
        ("VOUCHER", "voucher"),
        ("COUPON", "쿠폰"),
        ("COUPON", "coupon"),
        ("OTHER", "기타"),
        ("OTHER", "OTHER"),
    )
    alias_stmt = text(
        "INSERT INTO pos_mart.std_payment_method_alias (std_code, alias) "
        "VALUES (:c, :a) ON CONFLICT DO NOTHING"
    ).bindparams(bindparam("c"), bindparam("a"))
    for code, alias in aliases:
        bind.execute(alias_stmt, {"c": code, "a": alias})

    # ---- store channel 표준코드 ----
    op.execute(
        """
        INSERT INTO pos_mart.std_store_channel (std_code, display_name, description) VALUES
            ('HYPERMARKET','대형마트','이마트/홈플러스/롯데마트 등'),
            ('SUPERMARKET','SSM','GS더프레시/롯데슈퍼/홈플러스익스프레스'),
            ('CONVENIENCE','편의점','GS25/CU/세븐일레븐/이마트24'),
            ('TRADITIONAL','전통시장','지역 시장'),
            ('ONLINE','온라인','쿠팡/마켓컬리/SSG.COM'),
            ('OTHER','기타','분류되지 않음')
        ON CONFLICT DO NOTHING;
        """
    )

    # ---- mock 매장 3곳 ----
    op.execute(
        """
        INSERT INTO pos_mart.pos_store (store_code, store_name, store_channel, sido, sigungu)
        VALUES
            ('S001','이마트 강남점','HYPERMARKET','서울특별시','강남구'),
            ('S002','GS25 역삼사거리','CONVENIENCE','서울특별시','강남구'),
            ('S003','홈플러스 분당','HYPERMARKET','경기도','성남시')
        ON CONFLICT DO NOTHING;
        """
    )
    # ---- mock 터미널 5대 ----
    op.execute(
        """
        INSERT INTO pos_mart.pos_terminal (terminal_code, store_id, terminal_kind)
        SELECT t.tc, s.store_id, t.tk
          FROM (VALUES
                  ('T-S001-01','S001','LANE'),
                  ('T-S001-02','S001','LANE'),
                  ('T-S002-01','S002','SELF'),
                  ('T-S003-01','S003','LANE'),
                  ('T-S003-02','S003','SELF')) AS t(tc, sc, tk)
          JOIN pos_mart.pos_store s ON s.store_code = t.sc
        ON CONFLICT DO NOTHING;
        """
    )
    # ---- mock 거래 50건 ----
    op.execute(
        """
        INSERT INTO pos_mart.pos_transaction
            (store_id, terminal_id, txn_at, ymd, payment_method_raw,
             payment_method_std, amount_won, discount_won, tax_won, item_count)
        SELECT
            s.store_id,
            t.terminal_id,
            now() - (g.gs || ' minutes')::interval,
            to_char(now() - (g.gs || ' minutes')::interval, 'YYYY-MM-DD'),
            CASE g.gs % 5
                WHEN 0 THEN '신용카드'
                WHEN 1 THEN '현금'
                WHEN 2 THEN '카카오페이'
                WHEN 3 THEN '쿠폰'
                ELSE 'OK캐쉬백'
            END,
            NULL,  -- payment_method_std 는 정규화 노드가 채움
            (1000 + (g.gs * 137 % 50000))::numeric,
            (g.gs * 13 % 500)::numeric,
            (1000 + (g.gs * 137 % 50000) * 0.1)::numeric,
            1 + g.gs % 5
          FROM generate_series(1, 50) AS g(gs)
          JOIN LATERAL (
                SELECT store_id FROM pos_mart.pos_store
                ORDER BY (g.gs * store_id) % 7 LIMIT 1
          ) s ON TRUE
          JOIN LATERAL (
                SELECT terminal_id FROM pos_mart.pos_terminal
                WHERE pos_terminal.store_id = s.store_id
                ORDER BY pos_terminal.terminal_id LIMIT 1
          ) t ON TRUE
        ON CONFLICT DO NOTHING;
        """
    )

    # ---- cutover_flag seed (pos 는 v2-only — shadow 미적용) ----
    op.execute(
        """
        INSERT INTO ctl.cutover_flag
            (domain_code, resource_code, active_path, v2_read_enabled,
             v1_write_disabled, notes)
        VALUES
            ('pos','TRANSACTION','v2', TRUE, TRUE, 'STEP 9 새 도메인 — v2-only'),
            ('pos','STORE','v2', TRUE, TRUE, 'STEP 9 새 도메인 — v2-only'),
            ('pos','TERMINAL','v2', TRUE, TRUE, 'STEP 9 새 도메인 — v2-only')
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ctl.cutover_flag WHERE domain_code = 'pos';"
    )
    op.execute(
        "DELETE FROM domain.resource_definition WHERE domain_code = 'pos';"
    )
    op.execute(
        "DELETE FROM domain.standard_code_namespace WHERE domain_code = 'pos';"
    )
    op.execute(
        "DELETE FROM domain.domain_definition WHERE domain_code = 'pos';"
    )
    op.execute("DROP SCHEMA IF EXISTS pos_mart CASCADE;")
