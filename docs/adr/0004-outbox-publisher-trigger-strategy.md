# ADR-0004 — Outbox Publisher 트리거 전략 (Actor Enqueue + Phase 4 Debezium 검토)

- **Status:** Accepted
- **Date:** 2026-04-25
- **Deciders:** abfishlee + Claude
- **Phase:** 2.2.1 / 2.2.9 (백로그 게이지) — 결정·검증

## 1. 컨텍스트

ADR-0003 으로 도입한 Outbox 패턴은 **DB 트랜잭션과 이벤트 발행을 묶어** at-least-once
를 보장한다. 적재된 PENDING 행을 Redis Streams 로 옮기는 책임은 별도의 *publisher*
가 담당한다. 트리거 방법은 운영 lag / 운영 비용 / 신뢰성에 직결되는 결정이다.

후보:

| 전략 | 트리거 | 평균 lag | 운영 비용 |
|---|---|---|---|
| **A. Actor Enqueue** | API 가 raw INSERT commit 후 `publish_outbox_batch.send()` | <100ms | 낮음 (브로커만) |
| **B. 폴링 데몬** | 별도 cron-like 프로세스가 N초마다 SELECT | N초 | 중 (1 process) |
| **C. PG LISTEN/NOTIFY** | DB 트리거가 `NOTIFY outbox` 발행 → publisher LISTEN | <50ms | 중 (PG 의존도↑) |
| **D. Debezium CDC** | PG WAL → Kafka → Streams bridge | <100ms | 높음 (Kafka 운영) |

Phase 2 의 운영 인력은 사용자 1명 + 9월 합류 후 6~7명. 운영 비용 감수성이 매우 높다.

## 2. 결정

**A. Actor Enqueue 채택. 폴링 데몬은 catch-up 용으로 Phase 2.2.x 후속 도입 예정.**

구현:
- `app/workers/outbox_publisher.py::publish_outbox_batch` actor (queue=`outbox`).
- 호출 시점:
  - **즉시 트리거** — API 의 ingest 경로 commit 직후 `.send()` (현재 구현은
    publisher 가 별도 enqueue 안 받아도 catch-up 가능 — 운영자/Airflow 가
    fan-out 으로 enqueue 해도 동일).
  - **Airflow 보강 트리거 (Phase 2.2.3 후속)** — `system_outbox_drain` DAG 가 매
    1분 enqueue 해서 fail-safe.
- `outbox_pending_total` Gauge (Phase 2.2.9) 가 알람 트리거. 임계 1000 초과 5분
  지속되면 Alertmanager → Slack.

선택 이유:
- **운영 단순함** — Redis 브로커는 이미 Dramatiq 가 의존하므로 신규 컴포넌트 0.
- **at-most-once 강건** — actor 자체가 dramatiq retry/DLQ 위에 있어 실패 시 자동
  복구 + DLQ replay UI 로 수동 보정 (Phase 2.2.10).
- **확장 곡선이 자연스러움** — 처음엔 actor 한 개, 부하가 늘면 dramatiq threads/
  processes 만 늘리면 됨. PostgreSQL 부하 (B) 또는 NOTIFY 채널 한계 (C) 같은
  단일 병목 없음.

## 3. 대안

### 대안 B — 폴링 데몬
- **장점**: actor 시스템 외부에서도 동작 (브로커 장애 시에도 PG 만 살아 있으면 OK)
- **단점**: 평균 lag = poll interval / 2. interval 을 짧게 하면 PG 부하 ↑.
  별도 프로세스 lifecycle (이미 dramatiq worker 가 있음) 추가 부담.
- **부분 채택**: 향후 polling 데몬은 *catch-up only* 로 도입 — 평상시 lag 는 actor
  가 처리하고, 배포 직후·장애 복구 후 잔여 PENDING 만 정리.

### 대안 C — PG LISTEN/NOTIFY
- **장점**: 추가 인프라 0. 매우 낮은 lag.
- **단점**: NOTIFY 채널은 **세션 단위** — 운영 시 connection drop 시 메시지 유실.
  PG 가 SPOF. asyncpg 의 LISTEN 안정화는 운영 시 burn-in 필요.
- **기각 사유**: 운영 인력 6~7명이 PG 트리거 디버깅까지 배워야 함. 학습 비용 ↑.

### 대안 D — Debezium CDC + Kafka
- **장점**: 가장 신뢰성 높음. CDC 파이프라인 표준.
- **단점**: Kafka + Debezium + Connect cluster 운영 — 운영 인력 6~7명이 다룰 영역
  이 한 단계 늘어남.
- **기각 사유 (Phase 2)**: 운영 부담이 비례하지 않음. **Phase 4 의 Kafka 도입
  트리거 (CDC 소스 3+ 또는 500K rows/일 초과) 와 함께 재검토**.

## 4. 결과

**긍정적:**
- Phase 2 출시까지 인프라 추가 0 — Redis 만으로 운영.
- DLQ + 백로그 게이지 (Phase 2.2.9) 가 잘못된 트리거를 운영자에게 즉시 노출.
- Phase 2.2.10 의 운영자 DLQ replay UI 로 수동 catch-up 가능 — 위 단순함을 보완.

**부정적:**
- API ingest 가 publisher 트리거를 빠뜨리면 outbox 가 stream 으로 이송되지 않고
  쌓임 → `outbox_pending_total` 알람 발사 후 운영자가 수동 enqueue 필요.
  이 위험은 Phase 2.2.x 후속 폴링 데몬 도입 시 자동 해결.
- API 경로에 `actor.send()` 가 들어가면 broker 장애 시 ingest API 도 실패 가능.
  → `try/except` 로 swallow 하고 PENDING 적재는 그대로 유지 (publisher 가 다음
  enqueue 또는 폴링에서 처리).

**중립:**
- Streams 토픽(`dp:events:<aggregate_type>`) 별 길이는 `dramatiq_queue_lag_seconds`
  Gauge 로 노출 — Group lag 정밀 추적은 Phase 2.2.x 후속 (XINFO GROUPS PEL).

## 5. 검증

- [x] `tests/integration/test_outbox_publisher.py` — 시드 PENDING 3건 → 도메인 호출 →
  Streams XLEN 3 + DB status=PUBLISHED. 실패 stub → attempt_no 증가 + max 도달 시 FAILED
- [x] Runtime 대시보드 `Outbox PENDING` Stat 패널이 정확한 값 노출 (Phase 2.2.9)
- [ ] Phase 2.2.x 후속 폴링 데몬(`system_outbox_drain` Airflow DAG) 도입 — 운영 시점
- [ ] Phase 4 Debezium 검토 — Kafka 도입 트리거가 만족될 때 같이 결정

## 6. 회수 조건

- API 경로에서 `publish_outbox_batch.send()` 가 broker 장애로 ingest 실패율을 1%
  이상 끌어올리는 사례 발생 → 즉시 try/except 강제 + 폴링 데몬으로 fallback
- Streams 평균 lag p95 가 30s 이상 지속 → 폴링 interval 단축 또는 Debezium 진입
- CDC 소스 3+ 또는 500K rows/일 초과 → ADR-0007 작성 후 Debezium 도입

## 7. 참고

- `app/workers/outbox_publisher.py` — actor 정의 + 백로그 게이지 갱신
- `app/domain/outbox.py` — SELECT FOR UPDATE SKIP LOCKED 로 다중 worker 안전
- `docs/02_ARCHITECTURE.md` 2.9.1 — Streams 토픽 표
- `docs/airflow/INTEGRATION.md` — Airflow vs Dramatiq vs Visual ETL 책임 분담
- ADR-0003 — Outbox + content_hash_index (이 결정의 전제)
