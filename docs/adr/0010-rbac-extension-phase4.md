# ADR-0010 — RBAC 확장 (Phase 4.0.5): 5 → 8 role

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.0.5 (도입), 4.2.4 RLS / 4.2.5 Public API / 4.2.8b NKS 에서 활용

## 1. 컨텍스트

Phase 1~3 의 RBAC 는 5 role: `ADMIN / APPROVER / OPERATOR / REVIEWER / VIEWER`. Phase 4
가 다음 3 가지 새 시나리오를 추가:

1. **외부 API Public** (4.2.5) — 외부 소비자가 API Key 로 mart 데이터 조회. 내부 사용자
   role 과 다른 권한 표면.
2. **mart write 분리** (4.2.6 nginx + 4.2.4 RLS) — LOAD_MASTER 노드 + APPROVED SQL 자산이
   mart 에 직접 INSERT/UPDATE. 현재는 ADMIN/APPROVER 가 가지지만 *워크플로 작성자가 mart
   write 권한 없이* 도 워크플로 등록 가능해야 함 (최소 권한 원칙).
3. **sandbox 격리** (ADR-0008 의 마이그 트리거) — Phase 4.x 에서 NCP managed replica
   도입 후 SQL Studio sandbox 가 replica 로 라우팅. 그 라우팅을 받는 *오로지 sandbox 만*
   읽는 role.

기존 5 role 은 *권한 묶음* 형태였고, Phase 4 의 3 시나리오는 *기능 axis 별 분리*. 단순히
이름 추가가 아니라 "권한 모델이 기능별로 쪼개진다" 는 패러다임 변화.

## 2. 결정

**Phase 3 의 `require_roles(*codes)` dependency 와 4 + 5 = 9 그래프 호환성을 유지하면서
3 role 추가:**

| Role | 추가 이유 | 부여 대상 |
|---|---|---|
| `PUBLIC_READER` | 외부 API 키 (Public /public/v1/* 조회 전용) | `ctl.api_key` 의 발급 시 자동 부여 |
| `MART_WRITER` | LOAD_MASTER 노드 + APPROVED SQL 의 mart write 분리 | 기존 ADMIN/APPROVER 외에 운영자 1~2명 |
| `SANDBOX_READER` | SQL Studio sandbox replica 라우팅 후 그쪽 read-only | OPERATOR/APPROVER 가 sandbox 조회할 때 자동 |

### 핵심 결정 1 — 기존 dependency 호환

`require_roles("ADMIN", "APPROVER")` 같은 기존 호출은 **그대로 동작**. 새 role 은 *추가
조건* 으로만 작동. 예:

```python
# Phase 3 → Phase 4 호환:
@router.post(..., dependencies=[Depends(require_roles("ADMIN", "APPROVER"))])
# 이 endpoint 는 PUBLIC_READER / MART_WRITER 를 가진 사용자에게 여전히 403.

# Phase 4 신규 endpoint 의 권한:
@router.post("/internal/load_master", dependencies=[Depends(require_roles("MART_WRITER"))])
# 명시적으로 MART_WRITER 만 통과.
```

`require_roles` 의 검증 로직은 *intersection* (교집합 ≥ 1) 이라 새 role 추가가 기존
endpoint 의 권한을 *완화* 하지 않음. *제한* 만 가능.

### 핵심 결정 2 — Public 키와 내부 사용자 분리 X

원래 옵션: api_key 와 app_user 를 별도 테이블로 분리. **기각.**
- api_key 는 이미 Phase 1 에 `ctl.api_key` 테이블로 존재 — app_user 와 동등한 인증 주체.
- Phase 4.2.5 의 Public API 는 api_key 인증 후 *부여된 role* 로 권한 검증. 즉 PUBLIC_READER
  role 을 직접 들고 다님.
- 결과: app_user 와 api_key 모두 같은 `require_roles` dependency 로 권한 통제.

### 핵심 결정 3 — 자동 부여 안 함

기존 사용자에게 자동으로 새 role 을 부여하지 않음. ADMIN 이 명시적으로 grant — *정책
변경의 가시성* 보장.

마이그레이션 정책:
- `0021_phase4_roles.py` 는 `ctl.role` 에 row 만 추가, `ctl.user_role` 에는 0 row 변경.
- ADMIN 이 `PUT /v1/users/{id}/roles` 또는 `POST /{id}/roles` 로 grant.
- 실수 grant → `DELETE /v1/users/{id}/roles/{role_code}` 로 revoke.

## 3. 대안

### 대안 A — Permission 단위 RBAC (Casbin / Open Policy Agent)
- **장점:** 세밀 권한 (resource × action × scope). Phase 5 generic platform 의 도메인 ×
  resource 분리에 자연스러움.
- **기각 사유 (Phase 4):**
  - 학습 곡선 + 인프라 추가 (OPA sidecar / Casbin storage).
  - Phase 4 의 8 role 로 충분히 표현됨. **Phase 5 에서 도메인 × role 매트릭스가 등장하면
    재평가** (재평가 트리거 § 6 참조).

### 대안 B — Scope-based RBAC (OAuth2 scopes)
- **장점:** OAuth2 표준 호환. 외부 API key 가 자연스럽게 `scope=prices.read,products.read`.
- **기각 사유 (Phase 4):**
  - 내부 사용자 5 role 은 scope 로 표현하기 어색 (검수자 = scope=crowd.review.* 가 직관성
    낮음).
  - Phase 4.2.5 Public API 가 OAuth2 도입하면 scope 가 추가되긴 하지만 **role + scope 이중
    체크** 패턴으로 결합 (role 이 큰 묶음, scope 이 세밀).

### 대안 C — DB role (PG SET ROLE) 직접 사용
- **장점:** Phase 4.2.4 RLS 와 자연스럽게 결합 — RLS policy 가 PG role 로 작동.
- **기각 사유 (부분 채택):**
  - 사용자별 PG role 생성은 운영 부담. 대신 `app_rw` / `app_mart_write` / `app_readonly`
    / `app_public` 4 PG role 을 만들고 application 의 role 과 매핑.
  - Application role (PUBLIC_READER) → DB role (app_public) 매핑은 backend 의 SET ROLE
    분기로 (ADR-0011 — Phase 4.2.4 에서 명세).

## 4. 결과

**긍정적:**
- 기존 8 + (Phase 4.0.4 후 9) endpoint 의 require_roles 호출 모두 동작 (회귀 0).
- Phase 4.2.4 (RLS) / 4.2.5 (Public API) 진입 시 새 권한 표면이 명확.
- Phase 5 generic platform 에서 **도메인 × role 매트릭스** 도입 시 본 ADR 의 8 role 이
  *공통 axis* 로 재사용 — 도메인별 (agri/iot/pharma) `MART_WRITER` 가 자연스럽게 분기.

**부정적:**
- 운영자가 8 role 의 의미를 익히는 학습 비용. → frontend 의 `RolePicker` 가 description
  tooltip 표시 + Phase 4 신규 role 은 `v4` 라벨로 구분.
- Phase 5 도메인 분리 시 **role × 도메인 곱** 이 늘어남 (예: `agri:MART_WRITER` /
  `iot:MART_WRITER`). 본 ADR 은 그 시점에 다음 옵션:
  1. role_code 에 prefix 추가 (`AGRI_MART_WRITER`)
  2. 별도 `domain_role_assignment` 테이블
  3. Casbin 도입 (대안 A 재평가)

**중립:**
- backend 의 `require_roles` 검증은 DB lookup 1회 (캐시 안 함). Phase 4 트래픽 (외부 API
  포함) 100K req/min 넘으면 Redis 캐시 도입 검토 — 본 ADR 범위 외.

## 5. 검증

- [x] `migrations/versions/0021_phase4_roles.py` 적용 후 `ctl.role` 에 8 row.
- [x] `GET /v1/users/roles` — 8 row 모두 반환 (frontend RolePicker 가 사용).
- [x] `tests/integration/test_users_rbac.py` (8 케이스): role 카탈로그 / JWT claim /
  PUBLIC_READER 만 가진 사용자 ADMIN endpoint 403 / unknown role 404 / 기존 5 role 회귀
  / Phase 4 의 3 role 각각 단독 grantable.
- [x] frontend `UsersPage` 의 RolePicker 가 백엔드 카탈로그 동적 로드 + Phase 4 role 에
  `v4` 라벨.
- [ ] Phase 4.2.4 RLS 도입 시 PUBLIC_READER role 과 `app_public` PG role 매핑 검증 (ADR-0011
  에서 명세).
- [ ] Phase 4.2.5 Public API 의 api_key 발급 시 PUBLIC_READER 자동 부여 + scope 결합.

## 6. 회수 조건 (= 본 8-role 모델 한계 노출)

다음 *어떤 것* 이라도 발생하면 후속 ADR 작성 + 모델 변경:

1. **Phase 5 도메인 × role 곱 폭발** — 도메인 5+ × role 8 = 40+ 권한 row. 본 모델로
   관리 불가 → Casbin 또는 도메인별 role prefix 도입.
2. **세밀 권한 요구** — "운영자 A 는 mart.price_fact 의 retailer_id=1 만 INSERT" 같은
   row-level 권한이 RLS 만으로 표현 어려움 → OPA sidecar.
3. **운영자 100명+** — 8 role 부여/회수 운영 비용이 ADMIN 1명에게 부담 → 부서별 위임
   (delegated admin) 도입.

## 7. 참고

- `migrations/versions/0021_phase4_roles.py` — 3 role 추가.
- `backend/app/api/v1/users.py` — `GET /v1/users/roles` 카탈로그.
- `backend/app/deps.py` — `require_roles` 의 검증 로직 (변경 없음).
- `frontend/src/pages/UsersPage.tsx` — RolePicker (description tooltip + v4 라벨).
- `tests/integration/test_users_rbac.py` — 8 케이스.
- ADR-0008 (SQL Studio sandbox) — SANDBOX_READER 의 마이그 트리거 정의.
- ADR-0011 (Phase 4.2.4 — 예정) — RLS + 컬럼 마스킹 + PG role 매핑.
- `docs/phases/PHASE_5_GENERIC_PLATFORM.md` § 5.2.4 — 도메인 × role 분기 설계.
