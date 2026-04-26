# ADR-0022 — Inbound Push Receiver 표준 (HMAC SHA256 + Idempotency)

- **Status**: ACCEPTED
- **Date**: 2026-04-26
- **Phase**: 7 Wave 1A
- **Author**: Claude / 사용자

---

## 결정

> 외부 시스템 (크롤링 업체 / OCR 업체 / 소상공인 업로드 등) 이 우리에게 데이터를
> push 하는 표준 receiver 를 신설한다. **인증 = HMAC SHA256 + replay window ±5분**,
> **멱등성 = `(channel_code, idempotency_key)` UNIQUE 강제**, **저장 = 표준 envelope**.
> 외부 업체 진입장벽을 낮추기 위해 mTLS 는 *옵션* 으로만 두고 1차 의무 X.

---

## 컨텍스트

Phase 6 까지의 source 노드는 *우리가 fetch (pull) 하는 패턴* 1종 (`PUBLIC_API_FETCH`)
만 강했다. 사용자 요구사항 § 8.2 / 8.3 / 8.4 (외부 크롤링 / OCR / 소상공인 업로드)
는 *외부가 우리에게 push* 하는 패턴 — 기존 인프라로는 수용 불가.

Phase 7 Wave 1A 에서 Stripe Webhook / Singer / Airbyte inbound spec 의 글로벌
표준 패턴을 채택해 push receiver 를 만든다.

---

## 결정 상세

### 1. 인증 — HMAC SHA256 + replay window

**선택**: Stripe Webhook 패턴

```text
외부 시스템이 보낼 헤더:
  X-Signature: hmac-sha256=<hex>
  X-Timestamp: <unix epoch seconds>
  X-Idempotency-Key: <unique per event>

서명 대상 문자열:
  f"{timestamp}.{raw_body_bytes.decode('utf-8')}"

서명 계산:
  hex(HMAC-SHA256(secret, signed_string))

replay window:
  |now - timestamp| ≤ replay_window_sec (default 300 = ±5분)
  channel 별 30~3600 사이로 조정 가능
```

**대안 검토**:
- **mTLS** — 진입장벽 큼 (외부 업체가 클라이언트 인증서 발급/관리 필요).
  *옵션*으로만 ADR 부록에 명시. 금융/대기업 채널 한정 사용.
- **OAuth2 client_credentials** — token rotation 필요. 외부 업체 입장에서 webhook
  보내려고 매번 token 받는 것보다 HMAC 가 단순.
- **API key only** — replay 방지 부재. 보안 약함. *fallback 으로만* 지원
  (Phase 7 Wave 1B+).

**구현**: [`backend/app/core/hmac_verifier.py`](../../backend/app/core/hmac_verifier.py)
- `verify_hmac_signature(payload, signature_header, timestamp_header, secret, replay_window_sec)`
- `compute_signature(secret, timestamp, payload)` — 외부 업체용 reference impl
- `hmac.compare_digest()` 로 timing attack 방지

### 2. 멱등성 — `UNIQUE (channel_code, idempotency_key, received_at)`

**선택**: Idempotent Ingestion (Snowpipe / Singer pattern)

```sql
CREATE UNIQUE INDEX uq_inbound_event_idempotency
  ON audit.inbound_event (channel_code, idempotency_key, received_at);
```

- 외부 업체가 동일 `idempotency_key` 로 재전송 → DB UNIQUE 위반 → **409 Conflict**
- partition-aware (received_at 포함) — 월별 partition 안에서만 unique 보장
  (1년 후 같은 key 재사용 가능)

### 3. 표준 envelope — `audit.inbound_event`

```python
@dataclass
class IngestEnvelope:
    envelope_id: int                # PK
    channel_code: str               # /v1/inbound/{channel_code}
    channel_id: int                 # FK domain.inbound_channel
    domain_code: str
    idempotency_key: str            # UNIQUE
    sender_signature: str | None    # HMAC hex
    sender_ip: str | None
    user_agent: str | None
    request_id: str                 # 추적 ID
    content_type: str
    payload_size_bytes: int
    payload_object_key: str | None  # NCP Object Storage 위치
    payload_inline: dict | None     # ≤8KB JSON 만 인라인
    status: str                     # RECEIVED / PROCESSING / DONE / FAILED / DLQ
    workflow_run_id: int | None     # 어떤 workflow run 이 처리했는지
    received_at: datetime           # partition key
    processed_at: datetime | None
```

**디자인 결정**:
- 작은 (≤8KB) JSON 은 **inline** — 빠른 조회 + 별도 storage call 절약
- 큰 payload 는 **NCP Object Storage** — DB 부하 최소화
- partition by `received_at` (월별) — 1년 후 cold archive 가능 (Phase 4.2.7 활용)

### 4. Endpoint 패턴 — `POST /v1/inbound/{channel_code}`

```
POST /v1/inbound/{channel_code}        # JSON / XML / 일반
POST /v1/inbound/{channel_code}/upload # multipart (Phase 7 Wave 1B+)
```

응답:
- `202 Accepted` — RECEIVED 상태로 즉시 ACK (async 처리)
- `409 Conflict` — 동일 idempotency_key
- `401 Unauthorized` — HMAC 불일치 / replay window 초과
- `404 Not Found` — channel_code 없음 또는 비활성
- `413 Payload Too Large` — `max_payload_bytes` 초과
- `422 Unprocessable Entity` — content_type 불일치 / 헤더 누락

### 5. Channel 등록 정책

- `domain.inbound_channel` row 1건 = endpoint 1개
- `channel_code` 형식: `^[a-z][a-z0-9_]{1,62}$` (URL slug)
- 상태머신: DRAFT → REVIEW → APPROVED → PUBLISHED
  - **PUBLISHED + is_active=true 만 inbound 수신 가능**
  - DRAFT 채널로 push 시 → 404 (테스트 noise 방지)

### 6. 채널별 정책 튜닝

| 컬럼 | 기본값 | 범위 | 용도 |
|---|---|---|---|
| `max_payload_bytes` | 10,485,760 (10MB) | 1KB ~ 1GB | 채널별 한도 |
| `rate_limit_per_min` | 100 | 1 ~ 100,000 | DDoS 방지 (Phase 7 Wave 6 enforce) |
| `replay_window_sec` | 300 (±5분) | 30 ~ 3600 | 시간 동기화 여유 |
| `expected_content_type` | NULL | text | mismatch 시 422 |

---

## 구현 산출물 (Phase 7 Wave 1A)

### Backend
- `backend/app/core/hmac_verifier.py` — HMAC verifier
- `backend/app/api/v1/inbound.py` — `POST /v1/inbound/{channel_code}`
- `backend/app/api/v2/inbound_channels.py` — channel CRUD + transition
- `backend/app/models/domain.py` — `InboundChannel` ORM
- `migrations/versions/0049_inbound_envelope.py` — 두 테이블 + node CHECK 확장

### v2 Source 노드 3종 (캔버스에서 envelope 처리)
- `backend/app/domain/nodes_v2/webhook_ingest.py` — `WEBHOOK_INGEST`
- `backend/app/domain/nodes_v2/file_upload_ingest.py` — `FILE_UPLOAD_INGEST`
- `backend/app/domain/nodes_v2/db_incremental_fetch.py` — `DB_INCREMENTAL_FETCH`
  (db_incremental.py wrapper)

### Frontend
- `frontend/src/api/v2/inbound_channels.ts`
- `frontend/src/pages/v2/InboundChannelDesigner.tsx`
- `frontend/src/components/designer/NodePaletteV2.tsx` — 3종 추가
- `frontend/src/components/designer/NodeConfigPanelV2.tsx` — channel_code dropdown

---

## 외부 업체 onboarding 가이드 (간단 sample)

```python
# 외부 업체가 우리에게 push 할 때 reference impl (Python)
import hashlib
import hmac
import time
import requests
import uuid

def push_to_pipeline_hub(*, channel_code: str, secret: str, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    timestamp = int(time.time())
    signed = f"{timestamp}.".encode() + body
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()

    res = requests.post(
        f"https://api.pipeline-hub.example.com/v1/inbound/{channel_code}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": f"hmac-sha256={sig}",
            "X-Timestamp": str(timestamp),
            "X-Idempotency-Key": str(uuid.uuid4()),
        },
    )
    res.raise_for_status()
```

---

## acceptance (Wave 1A 종료 시)

- [x] migration 0049 적용 (audit.inbound_event + domain.inbound_channel + node CHECK 확장)
- [x] HMAC verifier unit-testable
- [x] `POST /v1/inbound/{channel_code}` 200/202/401/404/409/422 응답 검증
- [x] `WEBHOOK_INGEST` / `FILE_UPLOAD_INGEST` / `DB_INCREMENTAL_FETCH` 노드 dispatcher 등록 (17종)
- [x] frontend Inbound Channel Designer + 캔버스 palette 3종 추가
- [x] **KAMIS 회귀 5/5 통과** (PUBLIC_API_FETCH 기존 동작 보장)

---

## 부록 A — mTLS 옵션 (선택, Phase 7.5+)

금융권 / 대기업 채널 처럼 *추가 인증 계층* 이 필요한 경우:

1. NGINX / NCP Load Balancer 단에서 client cert 검증
2. backend 는 `request.scope["client"]` 의 cert subject 를 채널의 `mtls_subject` 와 비교
3. HMAC 와 *동시* 적용 가능 (defense in depth)

본 ADR 의 1차 범위는 HMAC only. mTLS 는 채널 등록 시 `auth_method='mtls'` 로
선택 가능한 옵션으로만 명시 (Phase 7 Wave 1A 에서 미구현, UI dropdown disabled).

---

## 부록 B — 글로벌 표준 참조

- **Stripe Webhook signature** — `Stripe-Signature` 헤더 + replay window 5분
- **GitHub Webhook signature** — `X-Hub-Signature-256` 헤더, `sha256=...` 형식
- **Slack Events API** — HMAC + replay window 5분
- **Microservices Patterns: Outbox** — Wave 6 에서 통합
- **Singer Tap inbound** — JSON Schema 표준 envelope
- **Airbyte Source Connector** — connector spec 표준화
- **OWASP API Security Top 10** — API3:2023 (Broken Object Property Level
  Authorization) 회피: channel_code 기반 격리 + scoped secret_ref

---

## 후속 (Phase 7 Wave 1B+)

- multipart upload (`POST /v1/inbound/{channel_code}/upload`)
- OCR_RESULT_INGEST / CRAWLER_RESULT_INGEST 노드 (Wave 1B)
- CDC_EVENT_FETCH 노드 (Wave 1B)
- Object Storage payload 의 노드 단계 fetch (현재는 inline JSON 만)
- Wave 6 의 outbox dispatcher → workflow 자동 trigger
- Wave 7 의 schema drift detection
