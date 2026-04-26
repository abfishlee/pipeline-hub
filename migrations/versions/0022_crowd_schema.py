"""Phase 4.2.1 — crowd schema 정식 + run.crowd_task → view 호환.

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-26 13:00:00+00:00

ADR-0011 의 마이그 정책:
  1. crowd schema 신설 + 6 table.
  2. 기존 run.crowd_task row 를 crowd.task 로 INSERT.
  3. run.crowd_task 를 DROP 후 같은 이름의 VIEW 로 재생성 — Phase 2.2.10 의 기존 코드/
     query 가 6개월간 호환 (downgrade 시점은 Phase 4 종료 시).

Phase 2 의 run.crowd_task placeholder 컬럼을 정식 모델로 매핑:
  reason         → crowd.task.task_kind (extension: OCR_REVIEW / PRODUCT_MATCHING /
                   RECEIPT_VALIDATION / ANOMALY_CHECK / std_low_confidence /
                   ocr_low_confidence / price_fact_low_confidence / sample_review)
  status         → crowd.task.status (PENDING/REVIEWING/CONFLICT/APPROVED/REJECTED)
  payload_json   → crowd.task.payload (JSONB)
  ocr_result_id  → crowd.task.ocr_result_id
  raw_object_id  → crowd.task.raw_object_id
  assigned_to    → crowd.task_assignment 의 첫 row 로 변환
  reviewed_by    → crowd.review 의 단일 row 로 변환
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- crowd schema -------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS crowd AUTHORIZATION app;")

    # task — 검수 단위
    op.execute(
        """
        CREATE TABLE crowd.task (
            crowd_task_id     BIGSERIAL PRIMARY KEY,
            task_kind         TEXT NOT NULL,
            priority          INTEGER NOT NULL DEFAULT 5,
            raw_object_id     BIGINT,
            partition_date    DATE,
            ocr_result_id     BIGINT,
            std_record_id     BIGINT,
            payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
            status            TEXT NOT NULL DEFAULT 'PENDING',
            requires_double_review BOOLEAN NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_crowd_task_kind CHECK (
                task_kind IN (
                    'OCR_REVIEW','PRODUCT_MATCHING','RECEIPT_VALIDATION','ANOMALY_CHECK',
                    'std_low_confidence','ocr_low_confidence',
                    'price_fact_low_confidence','sample_review'
                )
            ),
            CONSTRAINT ck_crowd_task_status CHECK (
                status IN ('PENDING','REVIEWING','CONFLICT','APPROVED','REJECTED','CANCELLED')
            ),
            CONSTRAINT ck_crowd_task_priority CHECK (priority BETWEEN 1 AND 10)
        );
        """
    )
    op.execute(
        "CREATE INDEX crowd_task_status_priority "
        "ON crowd.task (status, priority DESC, created_at) "
        "WHERE status IN ('PENDING','REVIEWING','CONFLICT');"
    )
    op.execute(
        "CREATE INDEX crowd_task_kind_status_idx "
        "ON crowd.task (task_kind, status, created_at DESC);"
    )

    # task_assignment — 다중 검수자 배정
    op.execute(
        """
        CREATE TABLE crowd.task_assignment (
            assignment_id   BIGSERIAL PRIMARY KEY,
            crowd_task_id   BIGINT NOT NULL REFERENCES crowd.task(crowd_task_id) ON DELETE CASCADE,
            reviewer_id     BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
            assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            due_at          TIMESTAMPTZ,
            released_at     TIMESTAMPTZ,
            CONSTRAINT uq_assignment UNIQUE (crowd_task_id, reviewer_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX crowd_assignment_reviewer_open "
        "ON crowd.task_assignment (reviewer_id) WHERE released_at IS NULL;"
    )

    # review — 검수자 1인의 결정 (이중 검수 시 row 2개)
    op.execute(
        """
        CREATE TABLE crowd.review (
            review_id       BIGSERIAL PRIMARY KEY,
            crowd_task_id   BIGINT NOT NULL REFERENCES crowd.task(crowd_task_id) ON DELETE CASCADE,
            reviewer_id     BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
            decision        TEXT NOT NULL,
            decision_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            comment         TEXT,
            time_spent_ms   INTEGER,
            decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_crowd_review_decision CHECK (
                decision IN ('APPROVE','REJECT','SKIP')
            ),
            CONSTRAINT uq_review UNIQUE (crowd_task_id, reviewer_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX crowd_review_reviewer_time "
        "ON crowd.review (reviewer_id, decided_at DESC);"
    )

    # task_decision — 합의 결과 + 비즈니스 효과
    op.execute(
        """
        CREATE TABLE crowd.task_decision (
            crowd_task_id   BIGINT PRIMARY KEY REFERENCES crowd.task(crowd_task_id) ON DELETE CASCADE,
            final_decision  TEXT NOT NULL,
            decided_by      BIGINT REFERENCES ctl.app_user(user_id),
            consensus_kind  TEXT NOT NULL,
            effect_payload  JSONB NOT NULL DEFAULT '{}'::jsonb,
            decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_crowd_decision_final CHECK (
                final_decision IN ('APPROVE','REJECT')
            ),
            CONSTRAINT ck_crowd_decision_consensus CHECK (
                consensus_kind IN ('SINGLE','DOUBLE_AGREED','CONFLICT_RESOLVED')
            )
        );
        """
    )

    # payout — 검수 보상 (외주)
    op.execute(
        """
        CREATE TABLE crowd.payout (
            payout_id       BIGSERIAL PRIMARY KEY,
            review_id       BIGINT NOT NULL REFERENCES crowd.review(review_id) ON DELETE CASCADE,
            amount_krw      NUMERIC(10,2) NOT NULL DEFAULT 0,
            currency        TEXT NOT NULL DEFAULT 'KRW',
            status          TEXT NOT NULL DEFAULT 'PENDING',
            paid_at         TIMESTAMPTZ,
            CONSTRAINT ck_crowd_payout_status CHECK (
                status IN ('PENDING','PAID','VOIDED')
            )
        );
        """
    )

    # skill_tag — 검수자 전문 분야
    op.execute(
        """
        CREATE TABLE crowd.skill_tag (
            skill_id        BIGSERIAL PRIMARY KEY,
            reviewer_id     BIGINT NOT NULL REFERENCES ctl.app_user(user_id) ON DELETE CASCADE,
            tag             TEXT NOT NULL,
            confidence      NUMERIC(4,3) NOT NULL DEFAULT 0.5,
            CONSTRAINT uq_skill_tag UNIQUE (reviewer_id, tag),
            CONSTRAINT ck_skill_confidence CHECK (confidence BETWEEN 0 AND 1)
        );
        """
    )

    # reviewer_stats — 운영자별 통계 (집계 view 가 아닌 cache 테이블, 매일 갱신)
    op.execute(
        """
        CREATE TABLE ctl.reviewer_stats (
            reviewer_id           BIGINT PRIMARY KEY REFERENCES ctl.app_user(user_id) ON DELETE CASCADE,
            reviewed_count_30d    INTEGER NOT NULL DEFAULT 0,
            avg_decision_ms_30d   INTEGER,
            conflict_rate_30d     NUMERIC(5,4),
            regression_rate_30d   NUMERIC(5,4),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # ---- 데이터 마이그 — run.crowd_task → crowd.task ---------------------
    # task_kind 매핑: 기존 reason 그대로 (CHECK 제약이 양쪽 호환).
    op.execute(
        """
        INSERT INTO crowd.task (
            crowd_task_id, task_kind, priority,
            raw_object_id, partition_date, ocr_result_id,
            payload, status, requires_double_review,
            created_at, updated_at
        )
        SELECT
            crowd_task_id,
            reason                                       AS task_kind,
            5                                            AS priority,
            raw_object_id, partition_date, ocr_result_id,
            payload_json                                 AS payload,
            CASE
                WHEN status = 'APPROVED' THEN 'APPROVED'
                WHEN status = 'REJECTED' THEN 'REJECTED'
                WHEN status = 'REVIEWING' THEN 'REVIEWING'
                ELSE 'PENDING'
            END                                          AS status,
            FALSE                                        AS requires_double_review,
            created_at,
            COALESCE(reviewed_at, created_at)            AS updated_at
        FROM run.crowd_task
        ON CONFLICT (crowd_task_id) DO NOTHING;
        """
    )
    # crowd.task 의 PK sequence 를 마이그 후 max + 1 로 맞춤.
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('crowd.task', 'crowd_task_id'),
            COALESCE((SELECT MAX(crowd_task_id) FROM crowd.task), 1),
            (SELECT MAX(crowd_task_id) IS NOT NULL FROM crowd.task)
        );
        """
    )
    # assigned_to 가 있던 row 를 task_assignment 1 row 로 변환.
    op.execute(
        """
        INSERT INTO crowd.task_assignment (crowd_task_id, reviewer_id, assigned_at)
        SELECT crowd_task_id, assigned_to, COALESCE(reviewed_at, created_at)
          FROM run.crowd_task
         WHERE assigned_to IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )
    # reviewed_by + status (APPROVED/REJECTED) 가 있던 row 를 review 1 row 로 변환.
    op.execute(
        """
        INSERT INTO crowd.review (crowd_task_id, reviewer_id, decision, decided_at)
        SELECT
            crowd_task_id,
            reviewed_by,
            CASE status WHEN 'APPROVED' THEN 'APPROVE' WHEN 'REJECTED' THEN 'REJECT' END,
            COALESCE(reviewed_at, created_at)
          FROM run.crowd_task
         WHERE reviewed_by IS NOT NULL
           AND status IN ('APPROVED','REJECTED')
        ON CONFLICT DO NOTHING;
        """
    )
    # 종결된 task 는 task_decision 도 함께 채움.
    op.execute(
        """
        INSERT INTO crowd.task_decision (crowd_task_id, final_decision, decided_by, consensus_kind, decided_at)
        SELECT
            crowd_task_id,
            CASE status WHEN 'APPROVED' THEN 'APPROVE' ELSE 'REJECT' END,
            reviewed_by,
            'SINGLE',
            COALESCE(reviewed_at, created_at)
          FROM run.crowd_task
         WHERE status IN ('APPROVED','REJECTED')
        ON CONFLICT DO NOTHING;
        """
    )

    # ---- run.crowd_task DROP + view 재생성 (호환) ---------------------
    op.execute("DROP TABLE run.crowd_task CASCADE;")
    op.execute(
        """
        CREATE VIEW run.crowd_task AS
        SELECT
            t.crowd_task_id,
            t.raw_object_id,
            t.partition_date,
            t.ocr_result_id,
            t.task_kind                          AS reason,
            CASE
                WHEN t.status = 'CONFLICT' THEN 'REVIEWING'
                WHEN t.status = 'CANCELLED' THEN 'REJECTED'
                ELSE t.status
            END                                   AS status,
            t.payload                             AS payload_json,
            (SELECT a.reviewer_id
               FROM crowd.task_assignment a
              WHERE a.crowd_task_id = t.crowd_task_id
                AND a.released_at IS NULL
              ORDER BY a.assigned_at ASC
              LIMIT 1)                            AS assigned_to,
            t.created_at,
            d.decided_at                          AS reviewed_at,
            d.decided_by                          AS reviewed_by
          FROM crowd.task t
          LEFT JOIN crowd.task_decision d ON d.crowd_task_id = t.crowd_task_id;
        """
    )
    op.execute("COMMENT ON VIEW run.crowd_task IS 'Phase 4.2.1 호환 view. Phase 5 에서 제거.';")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS run.crowd_task;")
    # crowd.task 데이터 → run.crowd_task 표 복원.
    op.execute(
        """
        CREATE TABLE run.crowd_task (
            crowd_task_id  BIGSERIAL PRIMARY KEY,
            raw_object_id  BIGINT NOT NULL,
            partition_date DATE NOT NULL,
            ocr_result_id  BIGINT,
            reason         TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'PENDING',
            payload_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
            assigned_to    BIGINT REFERENCES ctl.app_user(user_id),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_at    TIMESTAMPTZ,
            reviewed_by    BIGINT REFERENCES ctl.app_user(user_id),
            CONSTRAINT ck_crowd_task_status CHECK (
                status IN ('PENDING','REVIEWING','APPROVED','REJECTED')
            ),
            CONSTRAINT ck_crowd_task_reason CHECK (length(reason) BETWEEN 1 AND 200)
        );
        """
    )
    # crowd schema drop.
    op.execute("DROP TABLE IF EXISTS ctl.reviewer_stats CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS crowd CASCADE;")
