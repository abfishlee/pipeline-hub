"""mart.standard_code 에 pgvector embedding 컬럼 + IVFFLAT cosine 인덱스 추가.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-25 19:00:00+00:00

Phase 2.2.5 표준화 파이프라인:
  - 1차: pg_trgm `similarity()` ≥ 0.7 (이미 0006 에 GIN 인덱스 존재)
  - 2차: HyperCLOVA 임베딩 `<=>` cosine top-1 ≥ 0.85 — 이 migration 이 컬럼/인덱스 도입.
  - 3차: 둘 다 미달이면 `run.crowd_task` placeholder.

dimension 1536 은 OpenAI text-embedding-3-small / HyperCLOVA HCX-Embedding-Med 호환
기본값. 모델을 바꾸면 컬럼 재생성 필요 (pgvector 의 vector(N) 은 dimension immutable).

IVFFLAT 은 학습된 lists 가 필요 — 초기 데이터 0 row 일 때는 학습 불가라 100 lists
세팅만 하고, 운영 시 데이터가 1000+ row 쌓인 후 `REINDEX` 필요.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE mart.standard_code
            ADD COLUMN IF NOT EXISTS embedding vector(1536);
        """
    )
    # cosine 거리 인덱스. lists=100 은 row 수가 작을 때도 안전.
    # row 가 매우 많아지면 (>10K) lists=sqrt(rows) 로 REINDEX 권장.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS std_code_embedding_ivfflat
            ON mart.standard_code USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS mart.std_code_embedding_ivfflat;")
    op.execute("ALTER TABLE mart.standard_code DROP COLUMN IF EXISTS embedding;")
    # vector extension 은 다른 곳에서도 쓸 수 있어 drop 하지 않음.
