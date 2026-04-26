# ADR-0013 — CDC PoC: 경로 A (wal2json + logical replication slot) 채택

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.2.3 (도입)
- **참고:** PHASE_4_ENTERPRISE.md § 4.2.3 (경로 A vs 경로 B), `CLAUDE.md` § 3 — Kafka는
  Phase 4 조건부 (CDC 소스 3개 초과 시 재평가).

## 1. 컨텍스트

Phase 4 의 외부 데이터 소스 중 일부는 *우리가 직접 운영하지 않는 RDB* (마트 ERP / 로컬푸드
플랫폼의 PG/MySQL replica) — 이들은 일별 snapshot 만으로 변경 이력을 잡기 어렵다. 가격이
하루 안에 수차례 바뀌면 snapshot 시점만 받아 mart 가 반영해서는 *뭐가 언제 바뀌었는지*
추적이 끊긴다.

요구:
1. *우리 PG 클러스터의 mart 마스터 테이블* 변경을 외부에 공개하기 전에 자기 검증할 수
   있어야 함 (자기 CDC 가 다운스트림 정합성 회귀 테스트의 기반).
2. 향후 외부 RDB CDC 가 들어와도 같은 파이프라인으로 흡수.
3. 운영 단순성 우선 — Phase 4 시점에 운영자 6~7명 합류 직전, 새로운 인프라 학습 곡선을
   최소화.

## 2. 결정

**경로 A — wal2json + PostgreSQL logical replication slot 직접 구독** 채택.

```
PG (wal2json) ──[slot stream]──> Python consumer ──> raw.db_cdc_event
                                          │
                                          └──> outbox `cdc.event` ──> Dramatiq transform 큐
```

핵심 메커니즘:
- 소스 PG 에 `wal_level=logical`, `shared_preload_libraries=wal2json` 사전 설정.
- `scripts/setup_cdc_slot.sql` 가 superuser 로 1회 slot + publication 생성.
- `cdc_consumer_worker.dispatch_cdc_batch` actor 가 slot 에서 1배치 polling →
  `parse_wal2json_change` 가 format-version=2 JSON → `CdcChange` → `persist_cdc_changes` 가
  `raw.db_cdc_event` INSERT (`(source_id, lsn) UNIQUE` 로 중복 차단).
- `(source_id, lsn)` UNIQUE 가 idempotency 의 1차 방어. 같은 LSN 재시도 시 ON CONFLICT
  DO NOTHING.
- `airflow_dags/cdc_lag_monitor.py` 가 매 5분 `pg_replication_slots.confirmed_flush_lsn`
  기준 lag_bytes 측정 + 임계 (10 MB) 초과 시 outbox NOTIFY → notify_worker → Slack.
- `cdc_merge.py` 가 snapshot+CDC 머지 — `cdc_subscription.snapshot_lsn` 이후의 이벤트만
  적용해 snapshot 이 이미 반영한 row 의 중복 덮어쓰기 차단.

### 핵심 결정 1 — Kafka/Debezium 미도입

- Kafka 추가 = 새 broker 인프라 + Schema Registry + Connect 운영 + Strimzi/Helm 학습.
  Phase 4 시점의 사람 수 (6~7명) + 소스 수 (1~2개 예상) 에는 부담 큼.
- wal2json 은 PG 16 의 contrib 패키지. PG 와 *같은 DB* 에서 동작 — 별도 broker 불필요.
- 이벤트 fan-out 이 필요해도 *outbox publisher → Redis Streams* 의 기존 경로를 재사용
  (`docs/02_ARCHITECTURE.md` 2.9). Kafka 의 *고용량 분산 fan-out* 가치는 현재 트래픽에
  과잉.

### 핵심 결정 2 — `(source_id, lsn) UNIQUE` 가 idempotency

- LSN 은 PG 가 단조 증가 보장. 같은 transaction 의 같은 row 변경이라도 LSN 은 유일.
- Worker 가 batch 처리 중 죽어도 다음 polling 에서 ON CONFLICT DO NOTHING 으로 자연 통과.
- `last_committed_lsn` 을 별도로 기록해 다음 polling 시작점 결정.

### 핵심 결정 3 — Reorder buffer 단순화 (PoC 한계)

- format-version=2 의 BEGIN (`B`) / COMMIT (`C`) 는 `parse_wal2json_change` 가 None
  반환 — 트랜잭션 boundary 무시.
- production 에서는 트랜잭션 atomicity 가 중요한 케이스 (예: 두 row 의 동시 변경) 가
  존재 — buffer 후 COMMIT 시점에만 flush 가 필요.
- 본 PoC 는 *row-level idempotency 만 보장*, transaction-level atomicity 는 mart 측의
  upsert 가 자체적으로 처리해야 함을 명시.

## 3. 대안

### 대안 B — Kafka + Debezium (PHASE_4 § 4.2.3 의 경로 B)

- **장점**:
  - 표준 표면 (Debezium PG/MySQL/MSSQL/Oracle 통일).
  - Kafka 의 retention 으로 *replay* 자유로움.
  - Phase 5 generic platform 으로 갈 때 자연스러움.
- **기각 사유**:
  - Phase 4 시점 인프라 부담 큼 (KRaft Kafka + Connect + Schema Registry + 모니터링).
  - 소스 1~2개로는 ROI 낮음.
  - Phase 4 진입 게이트의 "산업 표준 운영 체계 + GitOps" 와 별개로, Kafka 도입은 *운영팀*
    Helm/Strimzi 경험을 전제 — 합류 직후 도입 위험.
- **재평가 트리거**: § 6 회수 조건 참고.

### 대안 C — 트리거 기반 audit 테이블 + 외부 polling

- **장점**: superuser/replication 권한 불필요. 응용 레벨에서 INSERT/UPDATE/DELETE 트리거
  가 audit 테이블에 row 적재.
- **기각 사유**:
  - 소스 DB 스키마에 *우리 트리거 설치* 협상 필요 — 외부 운영 주체와의 정치적 비용 큼.
  - 트리거가 같은 트랜잭션에 추가되어 소스 DB 의 쓰기 latency 증가.
  - 마스터 테이블 마이그레이션 시 트리거 재배포 동기화 부담.

### 대안 D — Logical replication 의 SUBSCRIPTION (PG → PG mirror)

- **장점**: PG 표준 기능. wal2json 같은 plugin 불필요.
- **기각 사유**:
  - subscription 은 *physical mirror* — JSON event 로 받지 않고 *행을 우리 DB 에 동일
    스키마로 복제*. 우리는 raw event log 가 필요 (운영자가 history 추적).
  - JSON 변환 + outbox 발행을 하려면 추가 trigger 가 다시 필요.

## 4. 결과

**긍정적**:
- 인프라 추가 0 (PG + Python 만으로 동작).
- 같은 PG 클러스터의 read 회귀 테스트가 sudo 없이 가능 — 본 PoC 의 통합 테스트가
  raw event 적재까지 검증.
- `audit.public_api_usage` (Phase 4.2.5) / mart upsert 쪽이 동일한 outbox 컨슈머
  패턴 재사용 — *DB CDC 가 우리 시스템에서 또 하나의 이벤트 source* 로 자연 합류.

**부정적**:
- wal2json 은 PG 클러스터 사이드 의존성 (binary 설치 + shared_preload_libraries).
  NCP managed PG 사용 시 plugin 사용 가능 여부 사전 확인 필요 (NCP Cloud DB for
  PostgreSQL 16 docs § wal2json).
- 트랜잭션 atomicity 가 row-level 이라, 두 row 사이의 cross-row invariants 는 적용
  로직이 명시적으로 처리해야 함.
- slot 은 *하나의 consumer 만 attach* — HA 시 leader 선출 필요.

**중립**:
- airflow `cdc_lag_monitor` 는 *Airflow 에서 PG 직접 접속* 패턴을 재사용 (Phase 4.0.4 의
  scheduled_pipelines DAG 와 동일). 별도 backend internal endpoint 추가 안 함 — 단순화.

## 5. 검증

- [x] migration `0025_cdc_poc.py` — raw.db_cdc_event + ctl.cdc_subscription +
  ctl.data_source.cdc_enabled.
- [x] `app/integrations/cdc/wal2json_consumer.py` — 파서 + INSERT + lag 측정.
- [x] `app/workers/cdc_consumer_worker.py` — dispatch_cdc_batch actor.
- [x] `scripts/setup_cdc_slot.sql` — slot/publication 1회 셋업 (idempotent).
- [x] `infra/airflow/dags/cdc_lag_monitor.py` — 5분 간격 lag 측정 + Slack 알람.
- [x] `app/domain/cdc_merge.py` — snapshot+CDC LSN 비교 + business_key upsert.
- [x] `tests/integration/test_cdc_consumer.py` — 5 케이스: parser I/U/D + 빈/잘못된
  메시지 / persist_cdc_changes idempotency / lag 임계 초과 NOTIFY / merge LSN 분기.
- [ ] (운영 시점) 실제 wal2json plugin 설치된 PG 에 slot 가동 + 부하 테스트.
- [ ] (운영 시점) HA leader election 설계 — slot 하나에 한 consumer 만 붙는 제약 대응.

## 6. 회수 조건 (= 경로 B Kafka 도입 트리거)

다음 *어떤 것* 이라도 발생하면 ADR 후속 + 경로 B 채택 검토:

1. **CDC 소스 3개 초과** — 슬롯 관리/모니터링 복잡도 폭발.
2. **fan-out 수요 ≥ 3 컨슈머 그룹** — 같은 CDC 이벤트를 transform / search index /
   warehouse 로 동시에 보내는 시나리오 등장.
3. **이벤트 retention 1주+ 요구** — slot 의 무한 보존 시 PG WAL 디스크 압박.
4. **재처리/replay 빈도 높음** — slot 재생성으로 LSN 거꾸로 가는 작업이 잦으면 운영 부담.
5. **스키마 진화** — 외부 소스의 스키마 변경 빈도가 잦아 Schema Registry 가 절실한 경우.

## 7. 참고

- `migrations/versions/0025_cdc_poc.py` — 스키마.
- `backend/app/integrations/cdc/wal2json_consumer.py` — 파서 + 적재.
- `backend/app/workers/cdc_consumer_worker.py` — dispatch_cdc_batch actor.
- `scripts/setup_cdc_slot.sql` — 1회 slot 셋업 SQL.
- `infra/airflow/dags/cdc_lag_monitor.py` — lag 측정 DAG.
- `backend/app/domain/cdc_merge.py` — snapshot+CDC LSN 비교 + upsert.
- `backend/tests/integration/test_cdc_consumer.py` — 회귀.
- PHASE_4_ENTERPRISE.md § 4.2.3 — 경로 A/B 정의.
- ADR-0008 (SQL Studio sandbox) — replica 라우팅이 도입되면 CDC 와 결합 가능.
- wal2json README — https://github.com/eulerto/wal2json
