# 5. 보안 / 권한 / RLS / API Key

## 권한 모델 (3 계층)

```
Auth (JWT)              ── 사용자 신원 (ctl.app_user)
   │
Global Role             ── ADMIN / APPROVER / OPERATOR / VIEWER (ctl.role)
   │
Domain × Role Matrix    ── (user, domain) → VIEWER/EDITOR/APPROVER/ADMIN
                            (Phase 5.2.4 — ctl.user_domain_role)
```

### 위계 (Phase 5.2.4 STEP 7)

| Role | 권한 |
|---|---|
| VIEWER | 도메인 read + dry-run preview |
| EDITOR | + field_mapping / dq_rule DRAFT 작성 + REVIEW 요청 |
| APPROVER | + APPROVED 결재 (publish 가능) |
| ADMIN | + cutover / domain registry / api_key 발급 / 권한 grant |

전역 ADMIN (`ctl.role.role_code='ADMIN'`) 은 **모든 도메인에 자동 ADMIN** —
별도 `user_domain_role` row 불필요.

### grant 예시

```bash
# 사용자 42 에게 pos 도메인 EDITOR 부여 (전역 ADMIN 만 가능).
curl -X POST http://localhost:8000/v2/permissions/grant \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"user_id": 42, "domain_code": "pos", "role": "EDITOR"}'

# user 의 모든 도메인 권한 조회.
curl http://localhost:8000/v2/permissions/domains/42

# 도메인의 모든 grantee 조회.
curl http://localhost:8000/v2/permissions/domain/pos
```

## RLS (Row-Level Security)

### v1 (Phase 4.2.4 부터)
- `app_public` PG role + `set_retailer_allowlist` GUC 로 row 필터링.
- `mart.price_fact_view` 같은 *masking view* 가 retailer_allowlist 에 포함된 row 만 노출.

### v2 (Phase 5.2.7 STEP 10)
- `domain_resource_allowlist` JSONB 가 도메인 × resource × specific id (예:
  `retailer_ids`, `shop_ids`) 권한 매트릭스.
- Public API v2 (`/public/v2/{domain}/...`) 가 `extract_domain_allowlist` 호출
  → `DomainScope` → `has_id` 검사.

```python
# 예: api_key 의 domain_resource_allowlist
{
  "agri": {
    "resources": {
      "prices": {"retailer_ids": [1, 2]}     # retailer 1, 2 만 보임
    }
  },
  "pos": {
    "resources": {
      "TRANSACTION": {"shop_ids": [100]}     # store 100 만 보임
    }
  }
}
```

### v1 ↔ v2 호환 매핑 (Phase 5)
- 기존 `retailer_allowlist` 는 자동으로 `agri.resources.prices.retailer_ids` 로 매핑됨
  (migration 0044 + `map_v1_to_v2_compat`).
- Phase 7 에서 `retailer_allowlist` 컬럼 제거 검토.

## API Key 발급 + 운영

### 발급 (ADMIN)
```bash
curl -X POST http://localhost:8000/v1/api-keys \
  -d '{
    "client_name": "external-portal-pharma",
    "scope": ["products.read", "prices.read"],
    "rate_limit_per_min": 120,
    "expires_at": "2027-04-26T00:00:00Z",
    "domain_resource_allowlist": {
      "pharma": {"resources": {"DRUG_PRICE": {}}}
    }
  }'
# 응답: {"raw_key":"prefix.xxxxxx", ...}  ← 1회만 노출. 분실 시 revoke + 재발급.
```

### 사용 (외부 소비자)
```
GET /public/v2/pharma/DRUG_PRICE/latest?limit=100
X-API-Key: prefix.xxxxxx
```

### 운영
- **revoke**: `POST /v1/api-keys/{id}/revoke`
- **rate-limit**: 도메인 × api_key 별 (Phase 4.2.5 의 `core.rate_limit`).
- **audit**: 모든 호출이 `audit.public_api_usage` 에 1행.
- **abuse 감지**: Phase 4.2.6 의 `abuse_detector` (도메인 인지 — Phase 5.2.7).

## 비밀 관리 (Secret)

### 정책
- **DB 에 평문 저장 금지**. `provider_definition.secret_ref` 는 *참조 이름* 만.
- 실제 값 = env (개발/staging) 또는 NCP Secret Manager (운영).
- `.env` 는 git ignored. `.env.example` 만 commit.

### 관리 대상 비밀
| 종류 | 위치 | 회전 주기 |
|---|---|---|
| `CLOVA_OCR_SECRET` | env / Secret Manager | 6개월 |
| `UPSTAGE_API_KEY` | env / Secret Manager | 6개월 |
| `JWT_SECRET_KEY` | env / Secret Manager | 12개월 |
| `DATABASE_URL` (passwd) | env / Secret Manager | 6개월 |
| api_key (외부 발급) | DB hash 만 (Argon2) | 12개월 |

## audit log 5종

| 테이블 | 적재 |
|---|---|
| `audit.access_log` | 모든 HTTP 요청 (status, ip, user_agent, duration) |
| `audit.public_api_usage` | `/public/*` 호출 별 endpoint + scope match |
| `audit.sql_execution_log` | SQL Studio 실행 1건 (BLOCKED/APPROVED/EXECUTED) |
| `audit.shadow_diff` | Phase 5.2.5 dual-path 비교 |
| `audit.sql_explain_log` | Phase 5.2.8 Performance Coach 결과 |

검색은 PG 직접 또는 Loki (Phase 4 합류 후).

## 개인정보/PII 처리

- **수집 단계**: raw 그대로 저장 (Phase 1 정책 — 재처리 가능성).
- **mart 단계**: 마스킹 view (`mart.*_view`) 만 외부 노출. 원본은 `app_rw` 만 접근.
- **삭제 요청**: 사용자 별 raw + mart 행을 cascade 로 삭제하는 `scripts/gdpr_delete.py`
  (Phase 6 backlog).

## 위험 신호 (즉시 escalation)

| 신호 | 조치 |
|---|---|
| api_key 의 5xx 비율 30%+ in 5min | 자동 revoke + Slack alert |
| RLS GUC 설정 실패 (set_session_role error) | 해당 요청 즉시 503 + 알림 |
| audit.shadow_diff 의 *value_mismatch* 가 임계 초과 | cutover 자동 차단 (Phase 5.2.5) |
| ctl.api_key 에 `expires_at` 만료된 키 사용 | 401 + 알림 |
| 비정상 SQL 시도 (DROP/TRUNCATE) | 422 + audit + 사용자별 카운터 |
