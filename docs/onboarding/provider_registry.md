# Provider Registry 운영법

> Phase 5.2.1.1 — OCR / CRAWLER / HTTP_TRANSFORM provider 의 *DB 등록 + binding +
> circuit breaker* 통합 운영. AI_TRANSFORM 은 Phase 6.

## 등록된 provider (default seed)

| code | kind | impl | secret_ref | 설명 |
|---|---|---|---|---|
| `clova_v2` | OCR | internal_class | `CLOVA_OCR_SECRET` | Phase 1.2.4 baseline |
| `upstage` | OCR | internal_class | `UPSTAGE_API_KEY` | Phase 2.2.4 fallback |
| `external_ocr_api` | OCR | external_api | — | placeholder |
| `httpx_spider` | CRAWLER | internal_class | — | Phase 2.2.8 baseline |
| `playwright` | CRAWLER | internal_class | — | placeholder |
| `external_scraping_api` | CRAWLER | external_api | — | placeholder |
| `generic_http` | HTTP_TRANSFORM | external_api | — | 외부 정제 API base |

## binding 운영 (source 별 priority)

```bash
# source 12 의 OCR 바인딩 — clova 1순위, upstage 2순위.
curl -X POST /v2/providers/bindings -d '{
  "source_id": 12, "provider_code": "clova_v2", "priority": 1, "fallback_order": 1
}'
curl -X POST /v2/providers/bindings -d '{
  "source_id": 12, "provider_code": "upstage", "priority": 2, "fallback_order": 1
}'

# 우선순위 변경.
curl -X PATCH /v2/providers/bindings/{binding_id} -d '{"priority": 3, "is_active": true}'

# binding 목록.
curl /v2/providers/bindings?source_id=12
```

## Circuit Breaker (Phase 5.2.1.1 Q4 — 자체 구현)

상태:
- **CLOSED** — 정상. 모든 요청 통과.
- **OPEN** — 차단. fallback provider 자동 사용.
- **HALF_OPEN** — 1건 probe.

기본 정책 (Q5):
- max_retries = 2
- exponential backoff 1s → 3s
- open_after = 5건 연속 5xx/timeout
- open_seconds = 60
- retry_after_max = 300s

```bash
# circuit 상태 조회.
curl /v2/providers/circuit/clova_v2/12
# → {"state":"OPEN","failure_count":7,"last_error":"timeout","opened_at":"..."}

# ADMIN: OPEN 강제 reset.
curl -X POST /v2/providers/circuit/clova_v2/12/reset
```

## secret_ref 정책 (Phase 5.2.1.1 Q3)

- **DB 평문 저장 금지**. provider_definition.secret_ref 는 *참조 이름* 만.
- 실제 값:
  - 개발/staging — `.env` (`CLOVA_OCR_SECRET=xxx`)
  - 운영 — NCP Secret Manager (`os.environ` 으로 주입)
- 회전: 6개월 (`docs/onboarding/05_security_rls_apikey.md`).

## shadow runner (v1 → v2 점진 전환)

```python
# Phase 5.2.1.1 STEP 4 — v1 OcrProvider chain 와 v2 registry 결과 병렬 비교.
from app.domain.providers.shadow import shadow_run_async

result = await shadow_run_async(
    v1_callable=lambda: clova_ocr.recognize(image),
    v2_callable=lambda: registry_provider.recognize(image),
)
# diff → audit.provider_health 적재.
```

1주 shadow 후 ADMIN 명시 cutover (`/v2/cutover/apply`).

## 운영 모니터링

| 지표 | 임계 |
|---|---|
| OPEN circuit 수 | ≥ 1 → Slack alert |
| provider 별 5xx 비율 (5min) | ≥ 30% → fallback 강제 |
| `audit.provider_health` 의 OPEN 이력 | 일일 보고 |
| secret_ref 미해결 비율 | 즉시 escalation |

## Phase 6 추가 예정

- AI_TRANSFORM provider_kind (LLM-based 정제).
- frontend ProvidersPage (현재는 backend API + manual SQL).
- provider 비용 budget cap (도메인 monthly).
- Multi-region failover (NCP region 별).
