# ADR-0003 — Outbox 패턴 + 분리된 content_hash_index (글로벌 dedup)

- **Status:** Accepted
- **Date:** 2026-04-25
- **Deciders:** abfishlee + Claude
- **Phase:** 1.2.7 (수집 API) — 결정 / 1.2.10 (관제) — 검증

## 1. 컨텍스트

수집 파이프라인은 두 가지 보장이 동시에 필요하다.

1. **Exactly-once 처리(외부 관점)** — 같은 페이로드를 재전송해도 다운스트림(price_observation, mart, 분석)에는 한 번만 흐른다.
2. **Transactional Event Publishing** — `raw_object` INSERT 와 "수집 발생" 이벤트 발행이 같은 DB 트랜잭션에서 묶여야 한다. 한쪽만 성공하고 다른 쪽이 실패하면 데이터 정합성이 깨진다.

또한 운영 제약으로:
- `raw.raw_object` 는 **월별 RANGE 파티션** (partition_date 기반). 데이터량이 평시 10만/일·피크 30만/일 → 12개월 단일 테이블은 인덱스 부풀이 + VACUUM 비용 폭발.
- PostgreSQL 파티션 테이블의 PK/UNIQUE 제약은 **파티션 키를 반드시 포함**해야 한다. → `(id, partition_date)` 합성키 필수.
- 그런데 dedup 의 의미는 "**전 파티션을 가로지르는 글로벌 유일성**" — `content_hash` 가 어떤 월에 들어왔는지와 무관하게 1번만 존재해야 한다.

이 두 요구가 정면 충돌한다. UNIQUE(content_hash) 를 파티션 테이블에 직접 걸 수 없다.

또 외부 클라이언트가 명시적 dedup 키(`Idempotency-Key`)를 보내는 케이스가 있고(POS 재전송 등), 본문 미세 변동(EOL, 공백) 으로 hash 만 다른데 의도는 같은 케이스도 있다 → **두 종류의 dedup 키**를 동시에 다뤄야 한다.

## 2. 결정

### 2.1 Outbox 패턴 (Transactional Event Publishing)

`run.event_outbox` 테이블에 이벤트를 raw INSERT 와 **같은 트랜잭션** 내에서 적재. 별도 publisher (Phase 2 Dramatiq actor) 가 PENDING 행을 폴링해 Redis Streams 로 발행하고 `published_at` 으로 마킹.

```sql
CREATE TABLE run.event_outbox (
    id              BIGSERIAL PRIMARY KEY,
    aggregate_type  TEXT      NOT NULL,        -- 'raw_object'
    aggregate_id    TEXT      NOT NULL,        -- '{raw_object_id}:{partition_date}'
    event_type      TEXT      NOT NULL,        -- 'raw_object.created'
    payload         JSONB     NOT NULL,
    status          TEXT      NOT NULL DEFAULT 'PENDING',
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    attempts        INT       NOT NULL DEFAULT 0,
    last_error      TEXT
);
CREATE INDEX ix_event_outbox_pending
  ON run.event_outbox (occurred_at) WHERE status = 'PENDING';
```

Phase 1 에서는 publisher 가 없으므로 PENDING 으로만 쌓이고, Phase 2 에서 소비를 시작한다 — 그동안 이벤트 손실은 없다.

### 2.2 분리된 `content_hash_index` 테이블 (글로벌 유일성)

```sql
-- raw_object: 파티션 테이블, PK = (id, partition_date)
CREATE TABLE raw.raw_object (
    id              BIGSERIAL,
    partition_date  DATE NOT NULL,
    source_id       BIGINT NOT NULL,
    content_hash    BYTEA NOT NULL,            -- SHA-256
    idempotency_key TEXT,
    payload_json    JSONB,
    object_uri      TEXT,
    bytes_size      BIGINT,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, partition_date)
) PARTITION BY RANGE (partition_date);

-- 분리된 글로벌 유니크 인덱스 — 파티션이 아닌 일반 테이블
CREATE TABLE raw.content_hash_index (
    content_hash    BYTEA      PRIMARY KEY,    -- 글로벌 UNIQUE
    raw_object_id   BIGINT     NOT NULL,
    partition_date  DATE       NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- idempotency_key 는 source_id 스코프로 충분 → 파티션 내 partial index
CREATE INDEX ix_raw_object_idem
  ON raw.raw_object (source_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

수집 흐름:

1. 클라이언트 요청 → `content_hash` 계산 (서버 측 SHA-256, 본문 정규화 후).
2. `idempotency_key` 가 있으면 **먼저** `(source_id, idempotency_key)` partial index 조회 — 히트 시 기존 raw_object 반환 (`dedup=true`).
3. 그 다음 `content_hash_index` 조회 — 히트 시 기존 raw_object 반환.
4. 둘 다 미스면 한 트랜잭션 안에서:
   - `raw_object` INSERT
   - `content_hash_index` INSERT (PK 충돌 시 race condition → ROLLBACK 후 step 3 재시도)
   - `event_outbox` INSERT (`raw_object.created`)

## 3. 대안

### 대안 A — content_hash 를 raw_object PK 의 일부로
- **장점**: 추가 테이블 없음
- **단점**: 파티션 PK 가 `(content_hash, partition_date)` 가 되어 **같은 hash 가 다른 월 파티션에 중복 적재 가능**. 글로벌 유일성 깨짐
- **기각 사유**: dedup 의미 자체가 무너짐

### 대안 B — UNIQUE 인덱스를 파티션마다 따로
- **장점**: 파티션 정합 유지
- **단점**: `content_hash` 가 12개월 후 다시 들어오면 새 파티션에 UNIQUE 통과 → 글로벌 dedup 실패
- **기각 사유**: 영수증/마트 OPEN API 는 1년 후 같은 상품 페이로드 재출현이 흔함

### 대안 C — 외부 KV (Redis) 로 글로벌 dedup
- **장점**: 빠름
- **단점**: Redis 영속성/백업/장애 시 dedup 게이트 무력화. PG 트랜잭션 경계 밖
- **기각 사유**: dedup 은 **데이터 정합성 보증**이라 강한 일관성(PG ACID) 필요

### 대안 D — Debezium / Outbox 미사용 (직접 Redis Streams 발행)
- **장점**: 단순
- **단점**: INSERT 성공 + 발행 실패 = 이벤트 유실. 발행 성공 + INSERT ROLLBACK = 유령 이벤트
- **기각 사유**: 두 케이스 모두 운영 사고로 직결됨. Outbox 가 표준 해법

## 4. 결과

**긍정적:**
- 글로벌 dedup 정확성 (대안 A/B 의 함정 회피)
- 파티션 운영 제약 충돌 없음 (월별 DETACH/ARCHIVE 자유로움)
- 트랜잭션 보장으로 이벤트 유실/유령 0건
- Phase 2 publisher 가 도입되기 전에도 PENDING 으로 안전하게 누적 → 점진적 마이그레이션 가능
- 1.2.7 통합 테스트 7건 (실 PG) 모두 통과 — content_hash 충돌·idempotency 재전송·둘 다 미스 케이스 검증

**부정적:**
- 추가 테이블 1 + 인덱스 1 → 디스크 약간 증가 (10만 row/일 기준 month 30M 디스크 ~약 1GB 추정, 실측 후 갱신)
- 분리 테이블이라 `JOIN raw_object` 시 파티션 프루닝 + index lookup 두 단계 필요 → ms 단위 비용 (부담 없음)
- Outbox publisher 부재 시 `event_outbox` 가 무한 누적 → Phase 2 도입 전엔 dev 환경에서 주기적 TRUNCATE 권장 (운영은 Phase 2 도입과 동시)

**중립:**
- `content_hash_index` 가 일반 테이블이라 자체 VACUUM 필요. 행 수가 raw_object 와 동일하므로 동일 주기로 관리하면 됨
- Phase 4 에서 13개월 이상 raw_object 파티션을 Object Storage 로 archive + DETACH 할 때 `content_hash_index` 도 함께 archive 해야 dedup 무결 (운영 절차 문서화 필요 — Phase 4 에서)

## 5. 검증

- [x] `tests/integration/test_ingest.py` — 동일 페이로드 재전송 시 `dedup=true` 응답, raw_object 1건만 존재 (Phase 1.2.7)
- [x] `tests/integration/test_ingest.py` — `Idempotency-Key` 동일 + 본문 다름 → 첫 요청만 적재, 둘째는 dedup
- [x] `tests/integration/test_ingest.py` — `Idempotency-Key` 다름 + 본문 동일 → 첫 요청만 적재, 둘째는 content_hash dedup
- [x] `event_outbox` PENDING 카운트가 raw_object created 카운트와 일치 (Phase 1.2.10 수동 SQL)
- [ ] Phase 2 outbox publisher 도입 후 `published_at` 마킹 정합성 (Phase 2 검증 예정)

## 6. 회수 조건

- Object Storage 가 자체 dedup 을 강하게 제공해 `content_hash_index` 가 중복이 됨 → 단순화 검토 (현 NCP/MinIO 미제공)
- 글로벌 dedup 요구가 사라지고 파티션 단위 dedup 으로 충분해짐 → 분리 테이블 폐지
- Outbox 폴링 lag 가 Phase 2 도입 후에도 1분 SLA 를 위협 → Debezium CDC 로 교체 검토 (Phase 4 Kafka 도입 트리거와 같이 결정)

## 7. 참고

- [Outbox Pattern — microservices.io](https://microservices.io/patterns/data/transactional-outbox.html)
- [PostgreSQL partitioning constraints](https://www.postgresql.org/docs/16/ddl-partitioning.html#DDL-PARTITIONING-DECLARATIVE-LIMITATIONS)
- `docs/03_DATA_MODEL.md` — raw_object 파티션 정책 / content_hash_index DDL
- `docs/02_ARCHITECTURE.md` 2.9 — Redis Streams 토픽 정의 (Phase 2 publisher 입력)
