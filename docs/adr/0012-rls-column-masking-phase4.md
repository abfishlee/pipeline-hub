# ADR-0012 — RLS + 컬럼 마스킹 (Phase 4.2.4): 4 PG role 분리 + masking VIEW

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.2.4 (도입), 4.2.5 Public API / 4.2.8b NKS 운영 시 활용
- **참고 ADR:** ADR-0010 (RBAC 8 role) 의 § 3 대안 C (PG SET ROLE) 부분 채택.

## 1. 컨텍스트

Phase 4.2.5 의 Public API 가 외부 소비자에게 mart 데이터를 노출하기 직전, 두 가지
보안 표면이 정리되어야 한다:

1. **컬럼 마스킹** — 사업자번호 / 본사 주소 / 매장 상세 주소처럼 *내부에선 평문이지만
   외부 키에는 마스킹/제거되어야 할* 컬럼이 다수.
2. **행 단위 격리 (Row-level security)** — `api_key` 별로 *허용된 retailer 의 row
   만* 보여야 함 (예: 마트 A 의 자체 키는 자기 retailer 만 조회 가능).

Phase 1~3 의 backend 는 connection user 1개 (`app`) 로 모든 권한을 가졌다. 외부
키와 내부 사용자가 같은 connection 을 쓰면 권한 분리는 *애플리케이션 레이어* 에서만
가능 — 한 줄 실수로 전체 mart 가 노출될 위험.

## 2. 결정

**ADR-0010 § 3 대안 C 의 PG SET ROLE 안을 부분 채택**:

| PG Role | 용도 | 권한 표면 |
|---|---|---|
| `app_rw` | 일반 API (기존 동작 유지) | 모든 schema CRUD |
| `app_mart_write` | LOAD_MASTER + APPROVED SQL 의 mart upsert | mart.* CRUD |
| `app_readonly` | SQL Studio sandbox (replica 라우팅 후 read-only) | mart/wf/stg SELECT |
| `app_public` | 외부 API key 의 mart 조회 | masking view + RLS-제한 SELECT |

핵심 메커니즘:

1. **single connection user (`app`) 가 4 role 의 멤버**. 마이그 `0024` 가 GRANT.
   라우트마다 `SET LOCAL ROLE` 로 권한 표면 전환.
2. **Masking 은 SECURITY INVOKER VIEW** 로 처리. `current_role` 분기 CASE 식으로
   평문/마스크를 반환. 운영 코드는 view 만 SELECT.
3. **RLS 는 retailer_id 컬럼 보유 테이블** (`mart.seller_master`,
   `mart.product_mapping`) 에 적용. 정책은 `current_setting('app.retailer_allowlist')`
   를 읽어 row 필터.
4. **api_key 별 retailer_allowlist** — `ctl.api_key` 에 BIGINT[] 컬럼 추가. 키 발급
   시 운영자가 부여, Public API 가 SET LOCAL 로 GUC 주입.

### 핵심 결정 1 — Masking VIEW vs 컬럼 GRANT

원래 옵션 A: `GRANT SELECT (col1, col2) ON mart.retailer_master TO app_public` 으로
컬럼 단위 권한 분리. **기각.**
- ORM (SQLAlchemy) 가 자동으로 모든 컬럼을 SELECT 하면 *permission denied for column*
  이 운영 시 폭발. 모든 SELECT 를 `select(table.col1, table.col2)` 로 좁혀야 함.
- 신규 컬럼 추가 시마다 GRANT 갱신 필요 — 운영 부담.

채택 옵션 B: **VIEW 가 모든 컬럼을 노출하되 일부 컬럼은 masking CASE**. ORM 호환성
유지 + 신규 컬럼은 view 정의에 추가하면 자동 마스킹 정책 통과.

### 핵심 결정 2 — RLS 빈 allowlist = 0 row (deny by default)

RLS 정책의 `USING` 식이 `retailer_id = ANY(NULLIF(current_setting('app.retailer_allowlist',
true), '')::bigint[])` 로 평가됨. allowlist 가 비어 있으면 ANY(NULL) → FALSE → 0 row.

즉 *retailer_allowlist 가 비어 있는 api_key 는 어떤 retailer 도 조회 못함*. 신규
키 발급 직후 의도치 않게 전체 노출되는 사고 방지. 운영자가 명시적으로 allowlist 채워야
조회 가능.

대안: 빈 allowlist = unrestricted. **기각** — 보안 사고 잠재력 큼.

### 핵심 결정 3 — `SET LOCAL ROLE` (트랜잭션 단위)

- `SET ROLE` 은 세션 전체에 영향 — connection pool 재사용 시 다른 요청에 leak.
- `SET LOCAL ROLE` 은 트랜잭션 단위 — commit/rollback 시 자동 해제. **채택**.
- 라우트는 *명시적 트랜잭션* 안에서 SET LOCAL ROLE 후 SELECT.

세션 전반에 PG role 을 강제로 잠그고 싶으면 connection pool 의 `connect_args` 에
`options="-c role=app_public"` 를 박는 방법도 있지만, *공통 connection pool 에
다른 라우트가 SET ROLE 변경 시 충돌*. 본 ADR 은 *라우트 단위 SET LOCAL ROLE* 만
표준으로 둔다.

## 3. 대안

### 대안 A — Casbin / OPA + 애플리케이션 ABAC
- **장점**: 세밀 권한 (resource × action × scope). Phase 5 generic platform 의
  도메인 × resource 분리에 자연스러움.
- **기각 사유**: ADR-0010 § 3 와 동일 — Phase 4 시점에 OPA sidecar / Casbin 인프라
  추가 학습 곡선이 비용 대비 효율 낮음. PG RLS 가 이미 row/column 단위 격리를
  *원자 트랜잭션 안에서* 보장하는 가장 안전한 표면.

### 대안 B — PostgreSQL 사용자별 별도 Database User
- **장점**: 권한 분리 가장 명확 (Pg 의 native 분리).
- **기각 사유**: connection pool 이 사용자 단위로 분기 → 개수 폭발. Phase 4 의
  "single connection pool 운영" 원칙 위반. 본 ADR 은 *single connection + role
  switch* 로 동일 효과 + 풀 1개 유지.

### 대안 C — application-layer mask (View 없이 SELECT 후 dict 에서 컬럼 제거)
- **장점**: DDL 변경 0.
- **기각 사유**: SQL injection / 라우트 누락 시 leak. *DB 가 평문 row 를 backend 로
  전송한 시점부터 leak 위험*. 본 ADR 은 *DB 가 처음부터 마스크된 값을 반환* 하는
  policy-by-default 채택.

## 4. 결과

**긍정적**:
- Phase 4.2.5 Public API 가 본 ADR 의 view + RLS 만 사용하면 추가 보안 코드 거의 0.
- SQL Studio sandbox 도 동일 메커니즘 — `app_readonly` role 로 라우팅하면 마스킹/RLS
  자동 적용.
- ADR-0008 의 NCP managed replica 도입 시 connection_url 분기와 결합해 *replica 는
  app_readonly 로만 SET ROLE 가능* 강제 (운영 시 추가 가드).

**부정적**:
- 라우트마다 `set_session_role()` + `set_retailer_allowlist()` 호출 필요 → 잊으면
  app_rw 그대로 (= 전체 노출). 표준 dependency 로 추출 + audit log 와 결합 필요.
- masking VIEW 의 `current_role` 분기는 PG plan 에 영향 작음 (CASE 가 row 단위) 이지만
  대량 SELECT 시 컬럼 변환 cost. 측정 시 view materialize 또는 column 단위 GRANT
  hybrid 검토.
- migration downgrade 시 PG role 을 보존하는 정책. 다른 환경에 grant 가 남아있을
  위험성 회피용 — 운영자가 명시적 DROP 결정.

**중립**:
- RLS 와 ORM 의 `expire_on_commit=False` 조합 시 commit 후 같은 세션이 다른 role 에서
  동일 row 를 다시 fetch 할 수도 있음. Phase 4.2.4 의 라우트 단위 SET LOCAL ROLE 은
  단일 트랜잭션 안에서만 의미 → 이 위험은 없음.

## 5. 검증

- [x] migration `0024_rls_column_masking.py` 가 4 role 생성 + GRANT + RLS 정책 +
  masking view 일괄 처리.
- [x] `tests/integration/test_rls.py` (5 케이스):
  - ADMIN connection user 가 평문 business_no 조회.
  - app_public 으로 SET ROLE 하면 마스크 (`***-**-****` 등) 반환.
  - allowlist 비어 있으면 mart.seller_master 0 row.
  - allowlist 부분 매칭 시 해당 retailer row 만 보임.
  - app_rw 로 RESET ROLE 하면 다시 모든 row 보임.
- [x] `backend/app/api/v1/public.py` stub: `GET /public/v1/retailers` /
  `/public/v1/sellers` (api_key 헤더 → SET LOCAL ROLE app_public + allowlist GUC 주입).
- [ ] Phase 4.2.5 정식 Public API 도입 시: rate limit + audit + cache 결합 (본 ADR
  스코프 외, 후속 ADR 참고).
- [ ] Phase 4.2.8b (NKS 이관) 시 connection pool 별 connect_args 로 *기본 role*
  하드닝 검토.

## 6. 회수 조건

다음 *어떤 것* 이라도 발생하면 후속 ADR 작성 + 모델 변경:

1. **세밀 권한 요구가 RLS 만으로 표현 어려움** — 예: 동일 retailer 안에서도 일부
   sales_channel 만 노출, 또는 sale_unit 별 차등 마스킹 → OPA 도입 검토 (대안 A).
2. **RLS 의 plan 비용** — 대량 SELECT 시 RLS 정책 USING 평가가 SeqScan 강제로 만들면
   응답 시간 SLA 위반 → policy 단순화 또는 materialized view 전환.
3. **api_key 가 1,000+ 발급** — allowlist 관리 부담 증가 → key × tenant × retailer
   group 매트릭스로 도입.

## 7. 참고

- `migrations/versions/0024_rls_column_masking.py` — 4 role + RLS + masking view.
- `backend/app/db/session.py` — `set_session_role` / `set_retailer_allowlist`.
- `backend/app/api/v1/public.py` — stub (Phase 4.2.5 에서 본격 확장).
- `backend/app/models/ctl.py` — `ApiKey.retailer_allowlist`.
- `tests/integration/test_rls.py` — 5 케이스.
- ADR-0010 — RBAC 8 role (PUBLIC_READER 의 PG role 대응).
- PostgreSQL docs: [Row Security Policies](https://www.postgresql.org/docs/16/ddl-rowsecurity.html),
  [SET ROLE](https://www.postgresql.org/docs/16/sql-set-role.html).
