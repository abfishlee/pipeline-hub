# ADR-0014 — Public API (Phase 4.2.5): sub-app 분리 + scope 모델 + Redis 캐시

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.2.5 (도입), 4.2.6 Gateway 와 결합
- **선결조건:** ADR-0010 (RBAC 8 role), ADR-0012 (RLS + 마스킹)

## 1. 컨텍스트

Phase 4.2.4 의 stub `/public/v1/{retailers,sellers}` 위에 정식 외부 API 5종 (standard-codes,
products, prices.latest, prices.daily, prices.series) 을 얹어야 함. 동시에:

- 외부 소비자 OpenAPI (`/public/docs`) 가 *내부 라우트와 섞여 노출되면 안 됨* — 운영자가
  내부 IP/Body/스키마를 외부에 노출시키는 사고 가능성.
- API key 별로 *분당 호출 제한* + *허용 retailer* + *scope (prices.read 등)* 가 모두 다름.
- 사용량 추적이 BI / 청구 / 악용 탐지의 입력 — 일별 집계 + 임계 알람 필요.

## 2. 결정

### 핵심 결정 1 — FastAPI sub-app mount (`/public`)

```python
public_app = FastAPI(title="Pipeline Hub Public API",
                     openapi_url="/openapi.json", docs_url="/docs")
public_app.include_router(public_v1_router)  # prefix="/v1"
app.mount("/public", public_app)
```

- 외부 OpenAPI = `/public/docs` + `/public/openapi.json` — 내부 라우트 미포함.
- 내부 OpenAPI (`/docs`) 는 그대로 유지.
- DomainError 핸들러는 sub-app 에도 명시 등록 (FastAPI mount 가 부모 핸들러를 자동 상속하지
  않음 — 핵심 함정).

대안 — main app 에 `/public/v1/*` 라우트만 두고 OpenAPI 필터링: 가능하지만 운영자가
실수로 내부 라우트에 `tags=['public']` 을 단 순간 외부 노출. *물리적 sub-app 분리* 가 더
방어적.

### 핵심 결정 2 — scope 매트릭스는 endpoint label 단위 OR (1+ 매칭)

| endpoint label | required (any of) |
|---|---|
| `retailers`, `sellers`, `standard_codes`, `products` | `products.read` |
| `prices.latest` | `prices.read` |
| `prices.daily`, `prices.series` | `aggregates.read` |

- `require_endpoint(label)` dependency 가 한 곳에서 인증 + scope + rate limit + role +
  GUC 일괄 처리. 라우트 함수는 scope 인지 *없이* 비즈니스만 작성.
- 발급된 키의 scope 가 `prices.read` 인데 `/public/v1/products` 호출 시 → 403
  (PermissionError → 403 + 코드 `FORBIDDEN`).

### 핵심 결정 3 — Redis fixed-window rate limit (slowapi 미채택)

- 의존성 추가 0 — 기존 `redis>=5.2` 만 사용.
- 키: `dp:public_api:rl:<api_key_id>:<YYYYMMDDHHMM>` INCR + 첫 INCR 시 EXPIRE 60s.
- 제한 정밀도는 *분 단위* (sliding window 가 아님) — 30초 안에 limit 두 배 호출 가능.
  PoC 단계에서는 이 정밀도면 충분, 운영 부하 과도 시 Lua 스크립트 sliding window 로 교체.
- Redis 미가동 시 *fail-open* — 사용량은 늘지만 서비스 중단은 회피.
- `RateLimitError(retry_after_seconds=...)` 가 응답 헤더 `Retry-After` 자동 부착.

대안 — slowapi: 학습 곡선 + 의존성. 본 PoC 의 fixed-window 가 simpler 우선.

### 핵심 결정 4 — Redis 응답 캐시

| endpoint | TTL |
|---|---|
| standard-codes | 300s |
| products | 300s |
| prices.daily | 300s |
| prices.latest | 60s |
| prices.series | 180s |

- 캐시 키는 `dp:public_api:cache:<endpoint>:<param-fingerprint>` — query string 의 모든
  파라미터 + retailer_allowlist (api_key 단위) 를 fingerprint 에 포함해 캐시 누설 방지.
  (PoC: 본 ADR 시점은 retailer_allowlist 무관 endpoint 만 캐시; allowlist 의존 endpoint
  는 fingerprint 에 추가 예정.)
- 캐시 hit/miss 메트릭 — Phase 4.2.6 Grafana 패널 추가 후속.

### 핵심 결정 5 — audit.public_api_usage 미들웨어 + 일별 view

- `PublicApiUsageMiddleware` 가 `/public/*` 응답 종료 시 `asyncio.create_task` 로 INSERT
  (fire-and-forget) — 응답 latency 영향 0.
- view `audit.public_api_usage_daily` 가 percentile_cont 로 p50/p99 계산.
- airflow `public_api_usage_daily` DAG 가 매일 00:30 — count 100K 또는 error rate 10%
  초과 row 발견 시 outbox NOTIFY → Slack.

## 3. 대안

### 대안 A — NCP API Gateway + 내부 backend 직접 노출
- **장점**: rate limit / 인증을 NCP 가 처리 → backend 코드 0 추가.
- **기각 사유**: scope 매트릭스 / RLS 통합 / audit 적재가 backend 단에 *반드시* 있어야
  함. NCP API Gateway 는 인증/quota 만 처리, 도메인 로직은 backend 로 떨어짐 — 즉
  NCP API Gateway 만으로는 부족하고 backend 도 결국 동일 코드 작성. 본 ADR 채택 후
  Phase 4.2.6 (ADR-0015) 에서 NCP Gateway 도입 트레이드오프 별도 평가.

### 대안 B — GraphQL endpoint 단일
- **장점**: 외부 소비자가 필요 컬럼만 선택 가능 → 응답 크기 최적화.
- **기각 사유**: 캐시 정책 복잡 (쿼리 형태가 매번 다름) + 과도한 query depth 공격 가드
  필요. REST 5 endpoint 면 충분.

### 대안 C — 모든 외부 호출을 internal endpoint 로 흡수 (token 기반)
- **장점**: 내부/외부 라우트 코드 통일.
- **기각 사유**: 외부 OpenAPI 분리 어려움 + scope 모델이 RBAC 와 섞임. *외부 API key*
  는 internal user 와 다른 인증 표면이라는 본 시스템의 1급 분류를 유지.

## 4. 결과

**긍정적**:
- 외부 OpenAPI 분리 → Phase 4.2.6 의 nginx 별 도메인 분리와 자연스러움 (api.* 도메인은
  /public 만 노출).
- scope 매트릭스가 1곳 (`ENDPOINT_REQUIRED_SCOPES` dict) — 신규 endpoint 추가 시 한 줄.
- audit 미들웨어가 *비동기 INSERT* — public 응답 latency 0 영향 검증.

**부정적**:
- sub-app 의 DomainError 핸들러가 별도 등록 필요 — 누락 시 sub-app 에서 500 폭주
  (운영 사고 가능성). 본 ADR 의 main.py 가 명시적으로 같은 핸들러 등록.
- Redis 미가동 시 rate limit fail-open — 운영 시 Redis 가용성 SLA 확보 + Sentry 알람.

**중립**:
- 캐시 fingerprint 가 retailer_allowlist 를 포함하지 않음 (PoC). 캐시 hit 시 다른
  api_key 가 같은 데이터 보게 되는 우려는 *현재 endpoint 가 retailer_id 무관 (예:
  standard-codes/products 의 마스터 데이터)* 이므로 안전. retailer_allowlist 의존 endpoint
  (sellers, prices.latest) 는 *캐시 미적용 또는 fingerprint 에 포함* 해야 함.
  prices.latest 는 retailer_id query param 을 fingerprint 로 포함 → OK. sellers 는
  현재 캐시 안 함.

## 5. 검증

- [x] migration `0026_public_api.py` — api_key 메타 + audit.public_api_usage + 일별 view.
- [x] `app/api/v1/api_keys.py` — POST/GET/DELETE 발급/조회/취소.
- [x] `app/api/v1/public.py` — 5 endpoints + scope check + rate limit + cache + role/GUC.
- [x] `app/main.py` — sub-app mount (`/public`) + DomainError 핸들러 명시.
- [x] `app/core/rate_limit.py` — Redis fixed-window helper.
- [x] `PublicApiUsageMiddleware` — fire-and-forget INSERT.
- [x] `infra/airflow/dags/public_api_usage_daily.py` — 매일 00:30 임계 알람.
- [x] frontend `ApiKeysPage` — 발급/목록/취소 + 평문 1회 노출 modal.
- [x] `tests/integration/test_public_api.py` 7 케이스: 발급 → 평문 1회 / 정상 호출 200 /
  scope 불일치 403 / rate limit 429 / 만료 키 401 / revoke 후 401 / audit 적재.

## 6. 회수 조건

다음 *어떤 것* 이라도 발생하면 후속 ADR + 모델 변경:

1. **Slowapi 또는 Envoy/Kong 으로 rate limit 외주** — 분당 fixed window 정밀도가
   sliding window 보다 2배 허용 노출이 실측 확인 + 비즈니스 영향 클 때.
2. **Public API endpoint 10개 초과** — sub-app 의 router 분할 필요 (예:
   `/public/v1/prices/*`, `/public/v1/products/*` 별도 router).
3. **scope 모델이 resource × action 매트릭스로 확장** — Casbin/OPA 도입 (ADR-0010 §
   대안 A 재평가 트리거).
4. **외부 키 5,000+ 발급** — Argon2 verify 의 CPU 비용이 응답 latency 의 dominant
   factor 가 되면 `key_prefix` lookup → cache 결과를 redis 에 짧게 캐시.

## 7. 참고

- `migrations/versions/0026_public_api.py` — 스키마.
- `backend/app/api/v1/public.py` — 라우터 + dependency.
- `backend/app/api/v1/api_keys.py` — 관리 라우터.
- `backend/app/core/rate_limit.py` — Redis fixed-window.
- `backend/app/main.py` — sub-app mount + 미들웨어 + 핸들러.
- `infra/airflow/dags/public_api_usage_daily.py` — 일별 임계 알람.
- `frontend/src/pages/ApiKeysPage.tsx` — 발급 UI.
- `frontend/src/api/api_keys.ts` — react-query hooks.
- `tests/integration/test_public_api.py` — 회귀.
- ADR-0010 (RBAC) / ADR-0012 (RLS + 마스킹) — 본 ADR 의 선결조건.
- ADR-0015 (Phase 4.2.6 — 예정) — nginx 별 도메인 + 보안 헤더.
