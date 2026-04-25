# ADR-0008 — SQL Studio sandbox: read-only TX vs 임시 스키마 격리

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 3.2.5 — SQL Studio sandbox / EXPLAIN / 승인 (도입)

## 1. 컨텍스트

운영자 / 분석가가 SQL Studio 화면에서 임의 SELECT 를 작성하고 *결과를 미리 보는* 기능
이 필요하다. 이 sandbox 가 만족해야 하는 안전성 요구는 다음 4개.

1. **데이터 변형 0** — 사용자가 의도하든 실수든 INSERT/UPDATE/DELETE/COPY/DDL 이 mart
   에 닿으면 안 된다.
2. **격리** — 큰 SELECT 가 다른 사용자 / 운영 트래픽에 영향 (lock / connection 점유)
   주지 말아야 한다.
3. **타임아웃** — 비효율 SQL 이 무한 실행되어 connection pool 을 점유 못 하게.
4. **결과 미리보기 + EXPLAIN** — 처음 1000 행과 plan_json 양쪽이 필요.

세 가지 접근법이 있다.

## 2. 결정

**Phase 3.2.5 = read-only 트랜잭션 + statement_timeout + LIMIT 자동 부착 + 명시 ROLLBACK.
Phase 4 에서 *대량 자료 저장 시나리오* (재현 가능 결과 / 승인 후 재실행) 가 등장하면
임시 스키마 격리로 마이그레이션.**

### 현재 정책 (3.2.5)

`app/domain/sql_studio.py::preview` 의 핵심 4줄:

```python
with session.begin_nested():
    session.execute(text(f"SET LOCAL statement_timeout = {ms}"))
    session.execute(text("SET LOCAL transaction_read_only = ON"))
    result = session.execute(text(_attach_limit(sql, limit)))   # LIMIT 1000 자동
    raise _RollbackSentinel()  # 명시적 ROLLBACK — 본문엔 변형 없지만 의도 분명히.
```

3중 방어:
1. **sqlglot 화이트리스트** (1차): SELECT/UNION/CTE 만, mart/stg/wf schema 만, 위험
   함수 차단.
2. **read_only TX** (2차): PG 가 강제. 우회 불가.
3. **ROLLBACK** (3차): 어떤 부수효과도 commit 안 됨.

audit row 만 별도 sub-tx (`_commit_audit`) 로 commit — preview ROLLBACK 의 영향에서
독립.

## 3. 대안

### 대안 A — `sql_sandbox_{user_id}_{uuid}` 임시 스키마 + `CREATE TABLE AS SELECT`
- **흐름:** `CREATE SCHEMA sql_sandbox_42_abcd; CREATE TABLE sql_sandbox_42_abcd.r AS
  SELECT ...; SELECT * FROM r LIMIT 1000; DROP SCHEMA sql_sandbox_42_abcd CASCADE`.
- **장점:**
  - 결과를 다시 SELECT 가능 — 페이지네이션 / 정렬 변경 시 재실행 없이.
  - 큰 결과(LIMIT 부재) 을 안전하게 cap (CREATE TABLE AS 가 디스크에 쓰지만 schema
    drop 으로 청소).
- **기각 사유 (Phase 3.2.5):**
  - `CREATE SCHEMA` / `CREATE TABLE AS` 권한 = DDL 권한 — 사용자 connection 에 부여
    하면 transaction_read_only 정책과 충돌. 별도 권한 분리 필요.
  - sandbox schema 누수 (process kill / OOM / pool reset 시) — schema GC 별도
    장치(매 dawn 에 `sql_sandbox_*` 스캔 + DROP) 필요.
  - 재실행 / 큰 결과 가치는 *분석가의 ad-hoc* 시나리오 — 본 단계 사용자(개발 1명) 에
    게는 과한 인프라.
- **재평가 트리거 (Phase 4 마이그):**
  - APPROVED SQL 을 mart 에 직접 `INSERT … SELECT` 로 적재하는 흐름 도입.
  - 분석가 30+명, ad-hoc SQL 결과 페이지네이션 요구.
  - 결과 row > 100k 에서 LIMIT 1000 미리보기로 부족하다는 사용자 피드백.

### 대안 B — read-only replica 분리
- **장점:** 운영 트래픽과 완전히 분리. 큰 SELECT 가 mart 에 영향 0.
- **기각 사유 (Phase 3.2.5):**
  - 로컬 / Phase 3 docker-compose 환경에선 PG 1대만 운영. NCP Cloud DB for
    PostgreSQL replica 는 Phase 4 NKS 이관 시점에 같이 띄울 예정 (`docs/01_TECH_STACK
    .md` 4. 참조).
  - 현재 트래픽(개발 1명) 에서 replica 분리 가치 없음.
- **재평가 트리거 (Phase 4):** Phase 4.x 에서 NCP managed replica 도입 시 sandbox
  preview 만 그쪽으로 라우팅.

### 대안 C — 외부 query engine (DuckDB / Trino) 로 격리
- **장점:** PG 와 완전 분리. 권한 / 리소스 폭주 영향 0.
- **기각 사유:**
  - mart 데이터 사본을 두는 비용. CDC pipeline 추가 (Phase 4 Kafka 도입 조건과 결합
    하면 검토 가능).
  - 현재 sandbox 가치가 "정합한 mart 위에서 dry-run" 인데 별 engine 위면 dry-run 의
    타당성이 떨어짐 (실제 pipeline 은 PG 위에서 도는데 sandbox 는 DuckDB 면 plan
    차이가 큼).

## 4. 결과

**긍정적:**
- 인프라 추가 0 — 기존 PG sync session + sqlglot 만으로 안전한 sandbox.
- 평균 elapsed 가 통상 SELECT 와 같은 수준 (3.4 표 측정 예정).
- audit.sql_execution_log 가 VALIDATE / PREVIEW / EXPLAIN 모두 1행씩 기록 — 컴플라이언스
  시각화 그대로 활용.
- 마이그 경로 명확 — 트리거 조건이 발생하면 임시 스키마로 *추가 확장* (현재 흐름은 그대로
  유지).

**부정적:**
- LIMIT 1000 으로 잘림 — 운영자가 "아, 결과 더 보고 싶은데" 같은 use case 에서 새
  LIMIT 으로 재실행. (UI 가 truncated=true 시 안내.)
- 같은 sandbox SQL 을 두 번 호출하면 두 번 실행 — 캐싱 없음. 향후 Phase 4 결과 캐시
  도입 시 임시 스키마 + cache key 결합.
- statement_timeout = 30s 가 운영 환경 전역과 다를 수 있음 — `SET LOCAL` 이라
  세션-scope, 영향 없음. 다만 운영자 SQL 이 실수로 30s 넘는 경우 단순 FAILED 로 마무리
  되어 디버깅 정보가 부족 — Phase 4 에서 `pg_stat_statements` 결합한 진단 패널 도입
  검토.

**중립:**
- read-only TX 로 성공한 SELECT 도 항상 ROLLBACK — 트랜잭션 ID 가 burnt 됨. PG 는
  txid wraparound 이슈 무시할 수준이지만 모니터링 시 sandbox 가 큰 비율을 차지하면
  운영 metric 이 "트랜잭션 처리량" 측면에서 노이즈.

## 5. 검증

- [x] sqlglot 정책 12종 — `tests/integration/test_sql_studio.py` (DROP/pg_read/pg_catalog
  /DELETE/COPY/disallowed-schema/whitespace + auth)
- [x] sandbox preview rows / truncate / read-only 격리(INSERT 후 row count 불변) /
  EXPLAIN JSON / VIEWER 403 — `tests/integration/test_sql_studio_sandbox.py`
- [x] 승인 lifecycle (create→submit→approve / self-approval 차단 / reject 후 새 DRAFT
  version_no 증가) — 같은 파일
- [ ] 100회 연속 preview 후 row count 불변 + 평균 elapsed — `tests/perf/test_sandbox
  _isolation.py` (`PERF=1` 환경에서 측정)

## 6. 회수 조건 (= 임시 스키마 마이그 트리거)

다음 *어떤 것* 이라도 발생하면 ADR-0008 후속 (예: 0008.A) 으로 임시 스키마 격리 도입.

1. APPROVED SQL 을 매 cron 에서 자동 mart 적재하는 흐름 도입 (현재 LOAD_MASTER 노드는
   sandbox 결과를 사용 안 함 — APPROVED SQL 이 SQL_TRANSFORM config 에 들어갈 뿐. 직접
   사용 시점부터는 결과 영속 필요).
2. SQL Studio 활성 사용자 30명 이상 — ad-hoc 페이지네이션 / 정렬 요구 누적.
3. preview 평균 elapsed > 1s — 결과 캐시 + 임시 스키마 결합으로 latency 감소 시도.
4. NCP managed read-only replica 가 운영팀에 의해 띄워지면 (Phase 4 인프라) — sandbox
   라우팅을 replica 로 이전 + 임시 스키마는 replica 측에 둬 운영 영향 0.

## 7. 참고

- `backend/app/domain/sql_studio.py` — preview / explain / 승인 상태머신.
- `backend/app/integrations/sqlglot_validator.py` — 1차 정책 (statement type / schema /
  function).
- `backend/tests/perf/test_sandbox_isolation.py` — read-only 격리 부하 측정.
- ADR-0001 (PG 드라이버 듀얼) — sync session 선택 근거 결합.
- `docs/phases/PHASE_4_ENTERPRISE.md` 4.x — replica + 임시 스키마 마이그 시점.
