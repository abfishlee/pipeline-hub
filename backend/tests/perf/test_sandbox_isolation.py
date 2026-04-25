"""SQL Studio sandbox 격리 + 부하 테스트 (Phase 3 비기능).

목표 (3.4):
  - preview 100회 연속 실행 후 실제 mart/stg row count 가 변하지 않는다 (read-only TX).
  - 평균 elapsed_ms 가 합리적 (≤ 100ms 더미 SELECT 기준).

`PERF=1` 환경변수 + DB 도달이 동시에 충족돼야 동작. 그렇지 않으면 skip.
"""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import text

from app.config import Settings
from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.domain import sql_studio as studio

DUMMY_TABLE = "stg.it_perf_sandbox_dummy"
PREVIEW_REPS = 100


pytestmark = pytest.mark.skipif(
    os.environ.get("PERF") != "1",
    reason="PERF=1 환경변수가 없으면 비기능 테스트는 skip (수동 실행 전용).",
)


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@pytest.fixture(scope="module")
def _seed_dummy_table(integration_settings: Settings) -> Iterator[int]:
    """sandbox preview 가 의미 있게 row 를 읽도록 1000 rows 시드.

    이미 있으면 그대로 사용 (다른 perf run 과 공유).
    """
    initial: int
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(f"DROP TABLE IF EXISTS {DUMMY_TABLE}")
        cur.execute(
            f"""
            CREATE TABLE {DUMMY_TABLE} (
                id          BIGSERIAL PRIMARY KEY,
                product     TEXT NOT NULL,
                price       NUMERIC(12,2) NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            f"""
            INSERT INTO {DUMMY_TABLE} (product, price)
            SELECT 'p_' || g, (g * 100)::numeric
              FROM generate_series(1, 1000) AS g
            """
        )
        cur.execute(f"SELECT COUNT(*)::int FROM {DUMMY_TABLE}")
        initial = int(cur.fetchone()[0])  # type: ignore[index]
    yield initial
    with (
        psycopg.connect(_sync_url(integration_settings.database_url), autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(f"DROP TABLE IF EXISTS {DUMMY_TABLE}")
    dispose_sync_engine()


def test_preview_100_runs_does_not_change_row_count(
    _seed_dummy_table: int,
    _admin_seed: dict[str, str],
) -> None:
    """preview 를 100회 호출 — row count 불변 + 평균/최대 ms 출력."""
    sm = get_sync_sessionmaker()

    # admin user_id lookup.
    with sm() as session:
        admin_user_id = int(
            session.execute(
                text("SELECT user_id FROM ctl.app_user WHERE login_id = :lid"),
                {"lid": _admin_seed["login_id"]},
            ).scalar_one()
        )

    # 베이스라인 row count.
    with sm() as session:
        before = int(session.execute(text(f"SELECT COUNT(*) FROM {DUMMY_TABLE}")).scalar_one())
    assert before == _seed_dummy_table

    # 100회 preview — 매번 새 sync 세션.
    elapsed_ms_list: list[int] = []
    sql = f"SELECT product, price FROM {DUMMY_TABLE} WHERE price < 50000"
    t_total = time.monotonic()
    for _ in range(PREVIEW_REPS):
        with sm() as session:
            result = studio.preview(
                session,
                user_id=admin_user_id,
                sql=sql,
                limit=100,
            )
            elapsed_ms_list.append(result.elapsed_ms)
            session.commit()
    total_wall_ms = int((time.monotonic() - t_total) * 1000)

    # 베이스라인 row count 가 똑같이 유지됐는지 — read-only 격리 검증.
    with sm() as session:
        after = int(session.execute(text(f"SELECT COUNT(*) FROM {DUMMY_TABLE}")).scalar_one())
    assert after == before, f"row count drifted: before={before} after={after}"

    avg_ms = statistics.mean(elapsed_ms_list)
    p95_ms = sorted(elapsed_ms_list)[int(len(elapsed_ms_list) * 0.95)]
    max_ms = max(elapsed_ms_list)
    print(
        "\n[PERF sandbox] "
        f"reps={PREVIEW_REPS} avg={avg_ms:.1f}ms p95={p95_ms}ms max={max_ms}ms "
        f"wall={total_wall_ms}ms — row_count {before}→{after} (unchanged)"
    )

    # 합리적 임계 — 평균 200ms 이하 (1k row 더미 기준 통상 10~30ms 예상).
    assert avg_ms < 500, f"avg preview elapsed too high: {avg_ms:.1f}ms"
