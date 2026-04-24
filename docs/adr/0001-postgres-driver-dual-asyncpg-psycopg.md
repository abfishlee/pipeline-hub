# ADR-0001 — PostgreSQL 드라이버 이중 채택 (asyncpg + psycopg3)

- **Status:** Accepted
- **Date:** 2026-04-25
- **Deciders:** abfishlee + Claude
- **Phase:** 1.2.3 (DB & Migration)

## 1. 컨텍스트

운영팀 6~7명이 9월 합류 예정. Phase 1~3는 사용자(Windows, Python 3.14) + Claude로 개발하고, Phase 4부터 NKS 운영 이관(Docker 이미지 기준 Python 3.12)이다.

PostgreSQL 비동기 드라이버는 두 가지 표준이 있다.

| 드라이버 | 장점 | 단점 |
|---|---|---|
| **asyncpg 0.30** | 30~40% 빠른 raw query, low-latency LISTEN/NOTIFY, 직접 binary protocol | 새 Python 버전 wheel 지연. 3.14 wheel 미공개 시 MSVC build 필요 |
| **psycopg[binary] 3.2** | 모든 Python 버전 binary wheel 안정, sync/async 동시 지원, COPY 풍부한 API | asyncpg 대비 raw 처리량 낮음 |

운영 시나리오에 두 드라이버 강점이 모두 필요한 경우:

1. **마트/유통사 webhook 폭주** — 행사 시작 시각에 push 1,000건/초 가능 → asyncpg latency 우위
2. **Kafka XREADGROUP fan-out** (Phase 4 CDC) — asyncpg consumer pool 효율 높음
3. **OCR/CDC 대량 COPY** — 양쪽 모두 가능하나 asyncpg copy_records_to_table 직관적
4. **Phase 2 Outbox LISTEN/NOTIFY** — asyncpg 채널 API가 깔끔

반면 **Python 3.14 환경**(현재 로컬)에서는 asyncpg가 prebuilt wheel 부재로 빌드 실패한다.

## 2. 결정

**둘 다 의존성에 포함시킨다. URL 스킴으로 환경별 분기.**

```toml
# pyproject.toml
dependencies = [
  "sqlalchemy[asyncio]>=2.0.35,<2.1",
  "alembic>=1.13,<1.15",
  # Docker 운영 (Python 3.12) 기본 — 빠른 raw I/O
  "asyncpg>=0.30; python_version < '3.14'",
  # 로컬 (Python 3.14) 또는 LISTEN/NOTIFY/COPY 보강용
  "psycopg[binary]>=3.2",
]
```

| 환경 | URL | 드라이버 |
|---|---|---|
| Docker 운영 (Python 3.12) | `postgresql+asyncpg://...` | asyncpg |
| 로컬 dev (Python 3.14) | `postgresql+psycopg://...` | psycopg3 |
| CI (Python 3.12, Linux) | `postgresql+asyncpg://...` | asyncpg |

설정 위치:
- `.env.example`: 두 옵션 모두 주석으로 명시. 기본 활성화는 `asyncpg`
- 로컬 `.env`: 사용자가 `postgresql+psycopg://` 로 override (이미 git 제외)
- `app/config.py`: URL 스킴 선택 로직 없음. 단순히 `database_url` 그대로 SQLAlchemy 에 전달

ORM/쿼리 코드는 **드라이버 비의존**. `text("SELECT 1")` / `select(...)` / ORM 모두 SQLAlchemy 추상화 안에서 동일 동작.

## 3. 대안

### 대안 A — psycopg3 단일 채택
- **장점**: 단일 driver, 환경 분기 없음, 운영 단순
- **단점**: webhook 폭주/CDC fan-out 시 latency 손해
- **기각 사유**: 외부 가격 데이터 push가 사업 모델의 핵심. 미래 확장성 보호

### 대안 B — asyncpg 단일 채택
- **장점**: 최고 성능
- **단점**: Python 3.14 로컬 빌드 실패 → 사용자 개발 불가
- **기각 사유**: 9월까지 사용자 개발 계속해야 함

### 대안 C — 환경변수 분기 코드
- **장점**: 명시적
- **단점**: 코드 if/else 분기 → 테스트 매트릭스 증가
- **기각 사유**: SQLAlchemy URL 스킴만으로 자동 분기 가능

## 4. 결과

**긍정적:**
- 로컬 즉시 개발 가능 (Python 3.14에서도 막힘 없음)
- 운영(Docker 3.12)은 asyncpg 성능 그대로
- Phase 4 webhook 폭주/CDC 시나리오 대비 헤드룸 확보
- 운영팀 인계 시 두 드라이버 모두 알아둘 가치 있음 (학습 자산)

**부정적:**
- 의존성 트리 +1 (psycopg) 약 5MB
- ORM이 아닌 raw SQL 사용 시 두 드라이버 호환 의식 필요 (당분간 raw SQL 거의 없음)

**중립:**
- 테스트는 한 환경에서 1번만 (Linux CI = asyncpg). 로컬에서 추가로 psycopg 회귀 가능

## 5. 검증

- [x] 로컬(Python 3.14)에서 `psycopg[binary]` 만으로 `uv sync` 성공
- [x] `postgresql+psycopg://app:app@localhost:5432/datapipeline` 로 `SELECT 1` 통과
- [ ] Docker 빌드(Python 3.12)에서 `asyncpg` 설치 + 동작 (Phase 1.2.10에서 검증 예정)

## 6. 회수 조건

다음 중 하나 발생 시 본 결정 재검토:

- asyncpg가 Python 3.14 wheel 정식 배포 → 단일 드라이버 단순화 검토
- psycopg3 성능이 asyncpg에 근접 (≤10% 차이) → 단일 드라이버 단순화 검토
- 분기로 인한 운영 사고 발생 → 단일 드라이버 강제

## 7. 참고

- [SQLAlchemy psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)
- [SQLAlchemy asyncpg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg)
- [psycopg 3 async examples](https://www.psycopg.org/psycopg3/docs/basic/async.html)
- [asyncpg performance benchmarks](https://magic.io/blog/asyncpg-1m-rows-from-postgres-to-python/)
