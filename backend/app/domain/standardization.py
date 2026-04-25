"""표준화 도메인 (Phase 2.2.5).

입력: 한국어 원시 라벨(예: "국산 사과 5kg")
출력: `mart.standard_code.std_code` + confidence + 매칭 전략

전략 우선순위:
  1) **trigram_hit** — `pg_trgm` `similarity(item_name_ko, label) ≥ std_trigram_threshold`
     또는 `aliases @> ARRAY[label]`. 같은 row 후보가 여러 개면 similarity 가 가장 높은 1건.
  2) **embedding_hit** — HyperCLOVA 임베딩 호출 후 `embedding <=> :v` (cosine 거리) 가
     `1 - std_embedding_threshold` 이하인 top-1.
  3) **crowd** — 둘 다 미달. 호출자가 `run.crowd_task("std_low_confidence")` 적재.

이 모듈 자체는 DB INSERT 안 함 — 결정만 반환. 호출자(transform 도메인)가 적재 책임.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core import metrics
from app.integrations.hyperclova import EmbeddingClient

DEFAULT_TRIGRAM_THRESHOLD = 0.7
DEFAULT_EMBEDDING_THRESHOLD = 0.85


@dataclass(slots=True, frozen=True)
class StdResolution:
    std_code: str | None
    confidence: float  # 0~1
    strategy: str  # 'trigram' | 'embedding' | 'crowd'


def _trigram_lookup(
    session: Session, label_ko: str, *, threshold: float
) -> tuple[str, float] | None:
    """pg_trgm `similarity()` top-1. aliases 도 GIN 으로 빠르게 후보 축소."""
    sql = text(
        """
        SELECT std_code,
               GREATEST(
                 similarity(item_name_ko, :label),
                 COALESCE((
                   SELECT MAX(similarity(a, :label))
                     FROM unnest(aliases) AS a
                 ), 0)
               ) AS sim
          FROM mart.standard_code
         WHERE is_active = TRUE
           AND (
             item_name_ko % :label
             OR EXISTS (SELECT 1 FROM unnest(aliases) AS a WHERE a % :label)
           )
         ORDER BY sim DESC
         LIMIT 1
        """
    ).bindparams(bindparam("label", label_ko))
    row = session.execute(sql).first()
    if row is None:
        return None
    code, sim = row[0], float(row[1] or 0.0)
    if sim < threshold:
        return None
    return code, sim


def _embedding_lookup(
    session: Session, vector: list[float], *, threshold: float
) -> tuple[str, float] | None:
    """pgvector cosine top-1. `embedding <=> :v` = cosine distance (0~2). similarity = 1 - d."""
    if not vector:
        return None
    # pgvector 의 vector literal 표현: ARRAY → cast::vector. asyncpg/psycopg 모두 지원.
    sql = text(
        """
        SELECT std_code, 1 - (embedding <=> :v::vector) AS sim
          FROM mart.standard_code
         WHERE is_active = TRUE
           AND embedding IS NOT NULL
         ORDER BY embedding <=> :v::vector
         LIMIT 1
        """
    ).bindparams(bindparam("v", str(vector)))
    row = session.execute(sql).first()
    if row is None:
        return None
    code, sim = row[0], float(row[1] or 0.0)
    if sim < threshold:
        return None
    return code, sim


def resolve_std_code(
    session: Session,
    label_ko: str,
    *,
    embedding_client: EmbeddingClient | None,
    trigram_threshold: float = DEFAULT_TRIGRAM_THRESHOLD,
    embedding_threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
) -> StdResolution:
    """3-단계 매칭 — 첫 hit 즉시 반환."""
    if not label_ko or not label_ko.strip():
        metrics.standardization_requests_total.labels(outcome="error").inc()
        return StdResolution(std_code=None, confidence=0.0, strategy="crowd")

    # 1) trigram
    hit = _trigram_lookup(session, label_ko, threshold=trigram_threshold)
    if hit is not None:
        code, sim = hit
        metrics.standardization_requests_total.labels(outcome="trigram_hit").inc()
        metrics.standardization_confidence.labels(strategy="trigram").observe(sim)
        return StdResolution(std_code=code, confidence=sim, strategy="trigram")

    # 2) embedding (외부 API). client 가 없거나 실패하면 crowd.
    if embedding_client is None:
        metrics.standardization_requests_total.labels(outcome="crowd").inc()
        return StdResolution(std_code=None, confidence=0.0, strategy="crowd")

    try:
        import time

        started = time.perf_counter()
        # async embed → sync 컨텍스트(워커)에서 asyncio.run.
        vec = asyncio.run(embedding_client.embed(label_ko))
        metrics.hyperclova_embedding_duration_seconds.observe(time.perf_counter() - started)
    except Exception:
        metrics.standardization_requests_total.labels(outcome="error").inc()
        return StdResolution(std_code=None, confidence=0.0, strategy="crowd")

    hit2 = _embedding_lookup(session, vec, threshold=embedding_threshold)
    if hit2 is not None:
        code, sim = hit2
        metrics.standardization_requests_total.labels(outcome="embedding_hit").inc()
        metrics.standardization_confidence.labels(strategy="embedding").observe(sim)
        return StdResolution(std_code=code, confidence=sim, strategy="embedding")

    metrics.standardization_requests_total.labels(outcome="crowd").inc()
    return StdResolution(std_code=None, confidence=0.0, strategy="crowd")


__all__ = [
    "DEFAULT_EMBEDDING_THRESHOLD",
    "DEFAULT_TRIGRAM_THRESHOLD",
    "StdResolution",
    "resolve_std_code",
]
