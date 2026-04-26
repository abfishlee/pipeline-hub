# ADR-0015 — Gateway / 보안 (Phase 4.2.6): nginx 별 도메인 분리 + 보안 헤더

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.2.6 (도입)
- **선결조건:** ADR-0014 (Public API sub-app)

## 1. 컨텍스트

Phase 4.2.5 의 Public API 가 `/public/v1/*` + `/public/docs` 로 분리되었지만, 외부
소비자가 *내부 운영 라우트를 같은 도메인에서 만나면 안 된다*. 또한 운영자가 실수로
내부 라우트에 외부 노출 정책을 바꿔도 *네트워크 경계에서 차단* 되는 가드가 필요.

요구:
1. 외부/내부 도메인 *물리 분리* (DNS + nginx layer).
2. HTTPS only + HSTS + 보안 헤더 표준 (X-Frame-Options/CSP/HSTS).
3. nginx layer 의 추가 rate limit (slowapi 와 별개) — backend 가 죽어도 단가 가드 유효.
4. 동일 IP × 다중 키 / 동일 키 × 다량 4xx 같은 *애플리케이션 레벨 abuse* 탐지.
5. 외부 노출 인증서 자동 갱신.

## 2. 결정

### 핵심 결정 1 — nginx 별 도메인 분리 (옵션 2 채택)

```
api.datapipeline.co.kr  → /public/v1/*, /public/docs   ← 외부 소비자만
app.datapipeline.co.kr  → /v1/*, /docs, frontend       ← 내부 운영
```

- `infra/nginx/api.datapipeline.co.kr.conf` 가 `/public/` 외 모든 path 를 404.
- `infra/nginx/app.datapipeline.co.kr.conf` 가 `/public/` 을 *역방향* 404.
- 두 conf 가 `infra/nginx/common.conf` include — TLS / 보안 헤더 / rate limit zone
  공통 정의.
- 내부 라우트가 실수로 외부 노출되어도 nginx layer 에서 *물리적으로 차단*.

대안 — NCP API Gateway (옵션 1): 인증/quota 가 NCP managed. **기각 사유**: scope/RLS/
audit 결합이 backend 단에 어차피 필요하고, NCP API Gateway 는 운영자가 적은 단계에서
별도 학습 곡선. 본 ADR 의 회수 조건에 명시.

### 핵심 결정 2 — nginx layer 의 이중 rate limit

slowapi (Phase 4.2.5) 와 별개로 nginx 단에서:
- `limit_conn_zone $binary_remote_addr zone=ip_conn:10m;` — IP 당 동시 connection.
- `limit_req_zone  $binary_remote_addr zone=ip_req:10m rate=50r/s;` — IP 당 burst.
- `limit_req_zone  $http_x_api_key zone=apikey_req:10m rate=10r/s;` — key 당 burst.

이중 가드로 *backend 가 다운되어도 nginx 가 폭주를 흡수*. slowapi 의 분당 rate (e.g.,
600/min) 보다 *더 엄격한 burst-friendly* 정책으로 동시 burst 가 backend 에 닿기 전에
완화.

### 핵심 결정 3 — abuse_detector (애플리케이션 레벨 탐지)

Redis 기반 sliding-window 카운터로:
- `IP_MULTI_KEY` — 동일 IP 가 분당 ≥ 5 distinct key 사용 → audit.security_event INSERT
  + outbox NOTIFY → notify_worker → Slack.
- `KEY_HIGH_4XX` — 동일 key 가 분당 ≥ 200 4xx 응답 → 동일 처리.
- 분당 알람 1건만 (Redis SETNX 패턴) — Slack 알람 폭주 방지.

`PublicApiUsageMiddleware` (Phase 4.2.5) 가 응답 종료 시 `evaluate_request` 호출. Redis
미가동 시 *fail-open* — 트래픽 처리에 영향 0.

대안 — backend 단에서 SQL `SELECT COUNT(*) FROM audit.public_api_usage WHERE ...`:
**기각 사유**: 매 요청마다 DB query 추가 → latency 회귀. Redis sliding window 가
적정.

### 핵심 결정 4 — 보안 헤더 표준

- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` — HSTS
  preload 등재 의도 (운영 단계).
- `X-Frame-Options: DENY` — clickjacking 방지.
- `X-Content-Type-Options: nosniff` — MIME sniffing 방지.
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()` — 지문 채집 방지.
- TLS 1.2+ only, ssl_stapling on.

### 핵심 결정 5 — Let's Encrypt 자동 갱신

`infra/nginx/certbot-renew.sh` 가 매일 04:00 cron 으로 갱신 시도. 갱신 후 nginx reload
(deploy-hook). 두 도메인 모두 동일 스크립트가 처리.

## 3. 대안

### 대안 A — NCP API Gateway 채택 (옵션 1)
- **장점**: NCP managed, OAuth2/quota 표준 표면.
- **기각 사유**: backend 도 같은 정책 (scope/RLS/audit) 을 처리해야 함 — gateway 도
  추가 작업 필요. 운영 단순성 측면에서 nginx 1대로 두 도메인 처리가 더 직관적.
- **재평가 트리거**: § 6 회수 조건.

### 대안 B — Cloudflare / AWS CloudFront 사용
- **장점**: WAF, DDoS 방어, edge cache.
- **기각 사유**: NCP 환경이라 외부 CDN 결합은 배치 정합성 고려 필요. Phase 4 단계에서
  과잉 — 후속 phase 에서 검토.

### 대안 C — abuse_detector 를 별도 sidecar 로 분리
- **장점**: backend 와 보안 정책 코드 분리, 독립 스케일.
- **기각 사유**: 정책이 *PG audit + Redis sliding* 양쪽을 만지기 때문에 backend 와
  같은 컨테이너에서 처리하는 게 단순. 추후 보안 정책이 5개+ 로 늘면 분리 검토.

## 4. 결과

**긍정적**:
- 외부 OpenAPI / 내부 OpenAPI 가 도메인 단에서 분리 — *internal 라우트 외부 노출 사고
  를 nginx 에서 물리 차단*.
- abuse_detector 가 backend 트래픽 폭주 전에 Slack 알람 — 운영 대응 시간 단축.
- HSTS preload 등재 가능 — 모바일 브라우저에서 HTTPS 우회 차단.

**부정적**:
- nginx conf 가 4개 (api/app/common + tests) — 운영자가 보안 헤더를 어디서 수정해야
  할지 헷갈릴 수 있음. common.conf 1곳에 모은 이유 = 일관성. README 에 수정 절차 명시
  필요 (NCP_DEPLOYMENT.md § Phase 4.2.6 갱신).
- abuse_detector 의 `IP_MULTI_KEY_THRESHOLD=5` 는 *마트 A 가 같은 NAT IP 로 5+ 키
  발급* 운영 패턴이면 false positive 가능. 운영자가 *whitelist 화* 가능한 추가 정책
  필요 (후속).
- Redis 가 abuse_detector 의 *진실 source* — Redis 죽으면 탐지 실패. PG 로 fallback
  하는 옵션도 검토.

**중립**:
- TLS 인증서는 NCP managed PKI 가 아닌 Let's Encrypt 사용. NCP 도메인 검증 자동화는
  certbot-dns-naver-cloud 플러그인 (커뮤니티) 또는 manual DNS challenge.

## 5. 검증

- [x] `infra/nginx/api.datapipeline.co.kr.conf` — /public/ 외 404.
- [x] `infra/nginx/app.datapipeline.co.kr.conf` — /public/ 차단 + 내부 라우트 + frontend.
- [x] `infra/nginx/common.conf` — TLS / 보안 헤더 / limit zone.
- [x] `infra/nginx/tests/test_headers.sh` — HSTS / X-Frame / X-Content / HTTP→301 검증.
- [x] `migrations/versions/0027_security_events.py` — audit.security_event.
- [x] `app/core/abuse_detector.py` — Redis 기반 sliding window + record_event.
- [x] `app/core/metrics.py` — `security_events_total{kind, severity}` Counter.
- [x] `app/api/v1/security_events.py` — ADMIN 전용 조회.
- [x] `app/main.py` — PublicApiUsageMiddleware 가 evaluate_request 호출.
- [x] frontend `SecurityEventsPage.tsx` (ADMIN 만) — 목록 + 필터 + 상세.
- [x] `infra/nginx/certbot-renew.sh` — 매일 04:00 자동 갱신.
- [x] `tests/integration/test_abuse_detector.py` 4 케이스: IP_MULTI_KEY 발화 / 200+
  4xx 발화 / 정상 트래픽 무알람 / 분당 중복 알람 억제.
- [ ] (운영 단계) HSTS preload 등재 신청.
- [ ] (운영 단계) 도메인 NS 설정 + Let's Encrypt 첫 발급.

## 6. 회수 조건 (= NCP API Gateway 도입 트리거)

다음 *어떤 것* 이라도 발생하면 후속 ADR + Gateway 도입 검토:

1. **Public API endpoint 30개+** — nginx conf 의 location 매트릭스 관리 부담.
2. **OAuth2 / SAML / JWT external auth 요구** — NCP API Gateway 의 표준 기능이 backend
   구현보다 빠름.
3. **CDN edge cache 필수** — 응답 redis cache 만으로 부족할 때.
4. **DDoS 공격이 nginx layer 만으로 처리 불능** — Cloudflare / AWS Shield 도입 검토.

## 7. 참고

- `infra/nginx/*.conf` — nginx 설정 4종.
- `migrations/versions/0027_security_events.py` — audit.security_event.
- `backend/app/core/abuse_detector.py` — Redis sliding window.
- `backend/app/api/v1/security_events.py` — ADMIN 조회.
- `frontend/src/pages/SecurityEventsPage.tsx` — 운영 UI.
- `tests/integration/test_abuse_detector.py` — 회귀 4 케이스.
- ADR-0014 (Public API sub-app) — 본 ADR 의 외부 라우트 정의.
