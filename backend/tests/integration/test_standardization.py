"""표준화 도메인 통합 테스트 — 실 PG (pg_trgm + pgvector), mock embedding client.

3분기 분기를 결정적으로 검증:
  1) trigram_hit — 시드 standard_code 의 item_name_ko 와 80%+ 유사 라벨
  2) embedding_hit — trigram 임계 미달이지만 embedding cosine 임계 충족
  3) crowd — 둘 다 미달
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain.standardization import StdResolution, resolve_std_code
from app.models.mart import StandardCode


class _StubEmbedder:
    """결정적 vector 를 반환. 테스트마다 dimension 맞춤 (DB 컬럼이 1536 가정)."""

    name = "stub-embed"

    def __init__(self, *, dimension: int, pattern: list[float] | None = None) -> None:
        self.dimension = dimension
        # pattern 이 짧으면 0 으로 padding, 길면 잘라냄.
        base = pattern or [1.0] + [0.0] * (dimension - 1)
        if len(base) < dimension:
            base = list(base) + [0.0] * (dimension - len(base))
        self._vec = base[:dimension]
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return list(self._vec)


@pytest.fixture
def cleanup_std_codes() -> Iterator[list[str]]:
    codes: list[str] = []
    yield codes
    if not codes:
        return
    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(delete(StandardCode).where(StandardCode.std_code.in_(codes)))
        session.commit()
    dispose_sync_engine()


def _seed_std_code(
    session: object,
    *,
    std_code: str,
    item_name_ko: str,
    aliases: list[str] | None = None,
    embedding: list[float] | None = None,
) -> None:
    row = StandardCode(
        std_code=std_code,
        category_lv1="과일",
        item_name_ko=item_name_ko,
        aliases=aliases or [],
        is_active=True,
        embedding=embedding,
    )
    session.add(row)  # type: ignore[attr-defined]
    session.commit()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 1. trigram_hit
# ---------------------------------------------------------------------------
def test_trigram_hit_returns_high_similarity(
    cleanup_std_codes: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"IT-STD-{secrets.token_hex(4).upper()}"
    cleanup_std_codes.append(code)
    with sm() as session:
        _seed_std_code(session, std_code=code, item_name_ko="후지사과")

    embedder = _StubEmbedder(dimension=1536)
    with sm() as session:
        # 임베딩 vector 없는 row 라 embedding 단계는 무력. trigram 으로 끝나야 함.
        result: StdResolution = resolve_std_code(
            session,
            "후지 사과",  # 공백 차이만 — trigram 유사도 높음
            embedding_client=embedder,
            trigram_threshold=0.5,
            embedding_threshold=0.85,
        )

    assert result.strategy == "trigram"
    assert result.std_code == code
    assert result.confidence >= 0.5
    # trigram 에서 hit 했으므로 embedding API 호출이 안 일어났어야 함.
    assert embedder.calls == 0


# ---------------------------------------------------------------------------
# 2. embedding_hit (trigram 임계 미달)
# ---------------------------------------------------------------------------
def test_embedding_hit_when_trigram_misses(
    cleanup_std_codes: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"IT-STD-{secrets.token_hex(4).upper()}"
    cleanup_std_codes.append(code)

    # embedding [1, 0, 0, ...] 시드 → 같은 vector 로 query 하면 cosine sim = 1.0
    seed_vec = [1.0] + [0.0] * 1535
    with sm() as session:
        _seed_std_code(
            session,
            std_code=code,
            item_name_ko="제주감귤박스",
            embedding=seed_vec,
        )

    # 라벨은 item_name_ko 와 trigram 거의 안 겹침 ('asdf' 등 무관).
    embedder = _StubEmbedder(dimension=1536, pattern=seed_vec)

    with sm() as session:
        result = resolve_std_code(
            session,
            "asdfqwer-no-match",
            embedding_client=embedder,
            trigram_threshold=0.95,  # 사실상 불가능하게 높임
            embedding_threshold=0.85,
        )

    assert result.strategy == "embedding"
    assert result.std_code == code
    assert result.confidence >= 0.85
    assert embedder.calls == 1


# ---------------------------------------------------------------------------
# 3. crowd (둘 다 미달)
# ---------------------------------------------------------------------------
def test_crowd_when_both_strategies_miss(
    cleanup_std_codes: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    code = f"IT-STD-{secrets.token_hex(4).upper()}"
    cleanup_std_codes.append(code)

    # 직교 vector — 입력 vector 와 cosine sim ~0.
    orthogonal = [0.0, 1.0] + [0.0] * 1534
    with sm() as session:
        _seed_std_code(
            session,
            std_code=code,
            item_name_ko="제주감귤박스",
            embedding=orthogonal,
        )

    # 라벨도 trigram 안 겹침, embedding 도 [1,0,0,...] 라 sim ~ 0.
    embedder = _StubEmbedder(dimension=1536, pattern=[1.0] + [0.0] * 1535)

    with sm() as session:
        result = resolve_std_code(
            session,
            "asdfqwer-no-match",
            embedding_client=embedder,
            trigram_threshold=0.95,
            embedding_threshold=0.85,
        )

    assert result.strategy == "crowd"
    assert result.std_code is None
    assert result.confidence == 0.0
    # embedding 호출은 일어났지만 매칭 미달.
    assert embedder.calls == 1


# ---------------------------------------------------------------------------
# 4. embedding_client = None → 즉시 crowd (외부 API 비활성)
# ---------------------------------------------------------------------------
def test_no_embedding_client_falls_to_crowd(
    cleanup_std_codes: list[str],
) -> None:
    sm = get_sync_sessionmaker()
    # std_code 시드 없음 — trigram 후보 자체가 0 row.
    with sm() as session:
        result = resolve_std_code(
            session,
            "no-such-label-anywhere",
            embedding_client=None,
            trigram_threshold=0.7,
            embedding_threshold=0.85,
        )
    assert result.strategy == "crowd"
    assert result.std_code is None


# ---------------------------------------------------------------------------
# 5. pg_trgm extension 정합 — similarity() 가 실제 동작하는지
# ---------------------------------------------------------------------------
def test_pg_trgm_extension_is_loaded() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        v = session.execute(text("SELECT similarity('apple', 'aple')")).scalar_one()
    assert isinstance(v, float)
    assert v > 0
