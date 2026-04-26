# ADR-0020 — Kafka 도입 트리거 (조건부; 현재 미도입)

- **Status**: ACCEPTED — *DEFERRED* (조건부)
- **Date**: 2026-04-27
- **Phase**: 5.2.8 STEP 11
- **Author**: Claude / 사용자

---

## 결정

> **현재 Kafka 미도입.** Redis Streams + Dramatiq 로 충분.
> 단, 아래 *4가지 트리거 중 하나 이상이 충족되면* Kafka(또는 NATS Streaming /
> RedPanda) + Debezium 도입을 재검토.

---

## 컨텍스트

Phase 1~4 동안 메시지 인프라는:
- **이벤트 broker**: Redis Streams (`dp:events:*`) + Pub/Sub.
- **작업 큐**: Dramatiq + Redis broker (`dp:queue:*`).
- **CDC**: PostgreSQL `wal2json` logical replication slot → cdc_consumer_worker.

이 구성은 *2 ~ 3인 운영팀* + *10만 ~ 30만 rows/일* 수준에서 충분히 안정.
Kafka 의 추가 분산 broker 운영 비용 (Zookeeper/KRaft, broker 3+ HA, 모니터링,
schema registry, MirrorMaker 등) 은 현 시점에 불필요.

---

## 도입 트리거 (Q2 답변)

다음 4 가지 중 **하나 이상** 발생 시 Kafka 도입을 재검토:

### Trigger 1 — Redis Streams lag 지속 임계 초과

조건:
- `redis_lag_ms` SLO 가 **30 분 이상 30,000ms 초과** (audit.perf_slo).
- Dramatiq queue depth 가 hourly p95 > 10,000.

**조치**: Redis Streams 의 *retention* 한계 (`MAXLEN ~`) 와 partition 부재가
원인이라면 Kafka 가 적합. Phase 4 의 outbox publisher 를 *publish to Kafka topic*
으로 변경.

### Trigger 2 — 1주일 이상의 replay/retention 필요

조건:
- 운영팀이 이벤트 1주 이상 거슬러 *재처리* 를 자주 요구.
- Redis 의 메모리 비용 (`MAXLEN`) 이 disk 기반 broker 보다 비싸짐.

**조치**: Kafka 의 log compaction + 무제한 retention 으로 전환. 단, S3/NCP
Object Storage 에 별도 raw 보존 (Phase 1 부터 적용) 이 이미 있으므로 *replay 가
정말 broker 에서만 가능한가* 를 우선 확인.

### Trigger 3 — 외부 시스템이 Kafka topic 을 요구

조건:
- 도메인 partner (예: 사업측 내 데이터 lake, 다른 부서) 가 *Kafka topic 으로
  publish* 를 명시 요구.
- 또는 공공데이터포털/통계청 등이 Kafka 로 데이터 제공.

**조치**: 외부 인터페이스에 한정해 Kafka 도입. 내부는 Redis Streams 유지하되
*bridge worker* (Kafka ↔ Redis Streams) 신설.

### Trigger 4 — CDC 기반 대규모 multi-DB 동기화

조건:
- v1 의 PG → mart 한 방향 CDC 외에, *N 개 source DB 에서 N 개 target* 으로
  실시간 fan-out 필요.
- 또는 다른 도메인이 *PG 외 RDBMS* (MySQL/Oracle 등) source 도입.

**조치**: Debezium + Kafka Connect 가 표준. wal2json + cdc_consumer_worker 의
도메인별 N×M 토폴로지를 직접 구현하는 비용 vs Kafka 도입 비용 비교.

---

## 도입 시 액션 플랜 (참고용)

트리거 충족 후 *7주 이내* 도입 가능하게 하기 위한 사전 준비:

| 주차 | 작업 |
|---|---|
| W1 | docker-compose 에 Kafka (KRaft mode) + Schema Registry 추가 |
| W2 | outbox publisher 에 Kafka 분기 (feature flag `APP_KAFKA_ENABLED`) |
| W3 | Kafka 와 Redis Streams 의 *dual-publish* (Q1 의 shadow 패턴 차용) |
| W4 | consumer 1종 (notify_worker) 만 Kafka 로 전환 |
| W5 | 나머지 consumer (cdc / pipeline) 점진 전환 |
| W6 | NCP 운영 환경 — managed Kafka (NCP CKaaS) 또는 자체 cluster 결정 |
| W7 | Redis Streams retention 을 1일로 축소 (cost reduction) |

---

## 비도입 정당화 (현 시점)

| 항목 | Redis Streams 현황 | Kafka 도입 시 |
|---|---|---|
| broker 인스턴스 수 | 1 (NCP Managed Redis) | 최소 3 (HA quorum) |
| 운영 인력 부담 | 낮음 (Phase 4 운영팀 친숙) | 높음 (KRaft + topic + partition + ACL) |
| 메시지 retention | TTL/MAXLEN 가능 | log compaction + indef. |
| consumer group | 별도 구현 필요 | native |
| schema 호환성 | 없음 (JSON) | Schema Registry 강제 |
| 비용 | 낮음 | 중~높음 |

→ 4 가지 트리거 중 하나도 충족하지 않은 현재, **Kafka 의 운영 부담이 이득보다 큼**.

---

## 회수 액션

3개월 마다 본 ADR 의 *트리거 충족 여부* 점검:
- `audit.perf_slo` 의 `redis_lag_ms` p95 ≥ 30,000ms 30분 이상?
- 운영팀 incident log 에 *replay* 키워드 빈도?
- 외부 partner 의 Kafka 요청?
- 신규 도메인이 multi-DB CDC?

→ 모두 No 면 본 ADR 유효 + Phase 6/7 도 Redis Streams 유지.
