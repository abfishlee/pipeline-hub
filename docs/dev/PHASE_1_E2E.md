# Phase 1 E2E 검증 시나리오

**대상:** 운영팀 (2026-09-01 합류 예정) — 이 문서를 처음부터 끝까지 따라가면 Phase 1 의 핵심 동작이 모두 살아 있는지 30분 안에 확인할 수 있다.
**전제:** Windows / macOS / Linux 어디든 OK. Docker Desktop + Python 3.12+ + Node 20+ + pnpm + uv 설치 완료.

> 이 문서는 [PHASE_1_CORE.md](../phases/PHASE_1_CORE.md) 1.3 "샘플 시나리오" 의 실행 가능한 형태이다. 1.3 의 10단계와 정확히 1:1 대응.

---

## 0. 사전 준비

```bash
# 0-1. 환경변수
cp .env.example .env

# 0-2. 인프라 일괄 기동 (PG / Redis / MinIO / Prometheus / Grafana)
make dev-up

# 0-3. DB 마이그레이션
make db-migrate

# 0-4. 부트스트랩 admin 사용자 (Phase 1 1.2.11 추가)
cd backend
uv run python ../scripts/seed_admin.py
# → [seed_admin] OK: user_id=1 login_id=admin role=ADMIN

# 0-5. Backend 기동 (별도 터미널)
uv run uvicorn app.main:app --reload --port 8000

# 0-6. Frontend 기동 (별도 터미널)
cd ../frontend
pnpm install
pnpm dev   # http://localhost:5173
```

기동 직후 헬스체크가 200 인지 확인:

```bash
curl -s http://localhost:8000/healthz
# {"status":"ok"}
curl -s http://localhost:8000/readyz
# {"status":"ready","checks":{"db":"ok","object_storage":"ok"}}
```

---

## 1. 사용자가 로그인한다

```bash
curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login_id":"admin","password":"admin"}' | jq .
```

기대 응답:

```json
{
  "access_token":  "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type":    "bearer",
  "expires_in":    3600
}
```

이후 모든 호출은 이 `access_token` 을 환경변수에 넣고 `Authorization: Bearer $TOKEN` 으로 전달.

```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login_id":"admin","password":"admin"}' | jq -r .access_token)
```

웹 UI 검증: http://localhost:5173 → 같은 자격 증명으로 로그인 → 대시보드 진입.

---

## 2. 신규 소스 `EMART_OPEN_API` 를 등록한다 (type=API)

```bash
curl -s -X POST http://localhost:8000/v1/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "source_code": "EMART_OPEN_API",
    "display_name": "이마트 OPEN API",
    "kind": "API",
    "is_active": true,
    "config_json": {"base_url":"https://example.emart/api","auth":"bearer"}
  }' | jq .
```

기대: `201 Created`, `source_id` 가 부여된 객체 반환.

웹 UI 검증: 좌측 "데이터 소스" → 목록에 `EMART_OPEN_API` 가 보임.

---

## 3. curl 로 `POST /v1/ingest/api/EMART_OPEN_API` 에 JSON 본문을 보낸다

```bash
curl -s -X POST http://localhost:8000/v1/ingest/api/EMART_OPEN_API \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 2026-04-25-batch-001' \
  -d '{
    "items":[
      {"sku":"E-001","name":"국산 사과 5kg","price":24900,"unit":"box"},
      {"sku":"E-002","name":"제주 감귤 3kg","price":12900,"unit":"box"}
    ]
  }' | jq .
```

기대 응답:

```json
{
  "raw_object_id": 1,
  "partition_date": "2026-04-25",
  "dedup": false,
  "object_uri": null,
  "bytes_size": 142
}
```

---

## 4. 같은 Idempotency-Key 로 다시 보내면 `dedup=true`

3번과 **완전히 동일한 명령**을 한 번 더 실행:

```bash
curl -s -X POST http://localhost:8000/v1/ingest/api/EMART_OPEN_API \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 2026-04-25-batch-001' \
  -d '{ ...3번과 동일... }' | jq .
```

기대 응답:

```json
{ "raw_object_id": 1, "partition_date": "2026-04-25", "dedup": true, ... }
```

`raw_object_id` 가 동일하다는 점이 핵심. DB 검증:

```sql
-- make dev-psql
SELECT count(*) FROM raw.raw_object WHERE source_id = 1;
-- → 1
```

---

## 5. 다른 본문(다른 content_hash) → 새 raw_object 생성

```bash
curl -s -X POST http://localhost:8000/v1/ingest/api/EMART_OPEN_API \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 2026-04-25-batch-002' \
  -d '{"items":[{"sku":"E-003","name":"청양고추 200g","price":3900,"unit":"pack"}]}' | jq .
```

기대: `raw_object_id` 가 **새 값**, `dedup=false`.

DB 검증:

```sql
SELECT count(*) FROM raw.raw_object WHERE source_id = 1;
-- → 2
SELECT count(*) FROM raw.content_hash_index;
-- → 2  (글로벌 dedup 인덱스도 함께 증가)
SELECT count(*) FROM run.event_outbox WHERE status = 'PENDING';
-- → 2  (Phase 2 publisher 가 소비 예정)
```

---

## 6. 웹 UI "수집 작업" 페이지에 방금 요청이 나타남

브라우저에서 http://localhost:5173 → 좌측 메뉴 "수집 작업" 진입.

기대:
- 표 상단에 방금 요청 2건이 시간순 내림차순으로 보임.
- 컬럼: `발생시각`, `소스`, `종류(api)`, `상태(SUCCESS)`, `dedup 여부`, `bytes`, `raw_object_id`.
- 행 클릭 시 우측 패널에 요청 ID, request_id, 페이로드 미리보기.

REST 기준 검증:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/v1/jobs?limit=10' | jq '.[].source_code'
# → "EMART_OPEN_API" 가 최소 2개
```

---

## 7. "원천 조회" 에서 payload JSON 확인

웹 UI: 좌측 "원천 조회" → `EMART_OPEN_API` 필터 → 테이블 행 클릭 → 페이로드 JSON 뷰어 표시.

REST 기준:

```bash
RAW_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/v1/raw-objects?source_code=EMART_OPEN_API&limit=1' \
  | jq -r '.[0].raw_object_id')

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/raw-objects/$RAW_ID" | jq .
```

기대: `payload_json` 에 3번에서 보낸 JSON 본문 그대로 보존.

---

## 8. 10MB 이미지 업로드 → object_uri 기록 + presigned 다운로드

10MB 파일 준비:

```bash
# 임의 10MB 바이너리
dd if=/dev/urandom of=/tmp/sample-10mb.bin bs=1M count=10
```

업로드:

```bash
curl -s -X POST http://localhost:8000/v1/ingest/file/EMART_OPEN_API \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: 2026-04-25-file-001' \
  -F "file=@/tmp/sample-10mb.bin" | jq .
```

기대 응답: `object_uri` 가 `s3://datapipeline-raw/...` 또는 `nos://datapipeline-raw/...` (운영 환경) 으로 채워져 있음.

```bash
RAW_ID=$(curl -s -X POST http://localhost:8000/v1/ingest/file/EMART_OPEN_API \
  ... | jq -r .raw_object_id)

# presigned 다운로드 URL 발급 (raw 상세 응답에 download_url 포함)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/raw-objects/$RAW_ID" | jq -r .download_url \
  | xargs curl -sS -o /tmp/round-trip.bin

# 동일성 확인
sha256sum /tmp/sample-10mb.bin /tmp/round-trip.bin
# → 두 해시가 정확히 같아야 함
```

MinIO Console 검증: http://localhost:9001 → `datapipeline-raw` 버킷 → 파일 존재 확인.

---

## 9. Grafana 대시보드에 수집 건수 증가 반영

브라우저: http://localhost:3000 → admin / admin (`.env` 의 `GRAFANA_ADMIN_PASSWORD` 변경 권장).

좌측 Dashboards → **"Pipeline Hub — Core"** 진입.

기대 패널 변화 (5~10초 내):
- **수집 QPS (1m)** 가 0 에서 잠깐 솟았다가 잦아듦
- **24시간 누적 적재** 패널 +3 (3·5·8 시나리오 합)
- **수집 source × kind** 패널에 `EMART_OPEN_API / api / created` + `EMART_OPEN_API / file / created` 분류로 표시
- **HTTP p95 by path** 에 `/v1/ingest/api/{source_code}`, `/v1/ingest/file/{source_code}` 가 라우트 템플릿 형태로 보임 (cardinality 정책 — `docs/ops/MONITORING.md` 1.3)

> 화면이 비어 있으면: Prometheus 가 백엔드를 스크레이프하고 있는지 http://localhost:9090/targets 에서 `host.docker.internal:8000` 의 state 가 `UP` 인지 확인.

---

## 10. Prometheus 에서 `ingest_requests_total` 직접 확인

```bash
curl -s 'http://localhost:9090/api/v1/query?query=sum(ingest_requests_total)' | jq .
```

기대:

```json
{"status":"success","data":{"resultType":"vector","result":[{"metric":{},"value":[<ts>,"3"]}]}}
```

값이 최소 3 이상(3·5·8 시나리오에서 created 한 횟수). 4번 dedup 요청은 `ingest_requests_total{status="dedup"}` + `ingest_dedup_total` 에 1 이 추가된다:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=ingest_dedup_total' | jq '.data.result[].value[1]'
# → "1"
```

`/metrics` raw 도 확인:

```bash
curl -s http://localhost:8000/metrics | grep -E '^ingest_' | head -20
```

---

## 11. (보너스) audit.access_log 검증

```sql
-- make dev-psql
SELECT method, path, status_code, request_id, duration_ms, occurred_at
  FROM audit.access_log
 WHERE occurred_at >= now() - interval '10 minutes'
 ORDER BY occurred_at DESC
 LIMIT 20;
```

기대: 위 시나리오에서 보낸 모든 `/v1/*` 요청이 한 행씩 기록됨. `/healthz`, `/metrics` 는 제외 (노이즈 회피 — `docs/ops/MONITORING.md` 3.1).

---

## 통과 기준 (Definition of Done)

| 단계 | 검증 | 결과 |
|---|---|---|
| 0 | `make dev-up` + `db-migrate` + `seed_admin` 무에러 | □ |
| 1 | `/v1/auth/login` → access/refresh 토큰 발급 | □ |
| 2 | `/v1/sources` POST → 201 + 목록 노출 | □ |
| 3 | `/v1/ingest/api` POST → `dedup=false` | □ |
| 4 | 동일 Idempotency-Key 재전송 → `dedup=true`, raw 1건만 | □ |
| 5 | 본문 변경 + 새 키 → raw 2건, content_hash_index 2건, outbox PENDING 2건 | □ |
| 6 | 웹 UI "수집 작업" 에 2건 노출 | □ |
| 7 | "원천 조회" 에서 payload_json 정상 표시 | □ |
| 8 | 10MB 파일 업로드 → object_uri + presigned 다운로드 SHA-256 일치 | □ |
| 9 | Grafana 대시보드 9 패널 모두 데이터 보임 | □ |
| 10 | Prometheus `ingest_requests_total` ≥ 3, `ingest_dedup_total` = 1 | □ |
| 11 | `audit.access_log` 가 위 호출들을 기록 | □ |

10/11 이상 ✅ 면 Phase 1 의 Core Foundation 이 살아 있는 것이다.

---

## 자주 막히는 곳

| 증상 | 원인 | 해결 |
|---|---|---|
| `make dev-up` 직후 `connection refused` | Docker Desktop 가 부팅되었지만 엔진 미준비 | `docker info` 가 200 줄 출력할 때까지 30~120초 대기 |
| `/v1/auth/login` 401 | seed_admin 미실행 또는 비밀번호 오타 | `scripts/seed_admin.py --login_id admin --password admin` 재실행 |
| `/v1/ingest/file` 413 | reverse-proxy 가 본문 크기 제한 (운영 NKS) | NKS Ingress `nginx.ingress.kubernetes.io/proxy-body-size: 50m` |
| Grafana 대시보드가 비어있음 | Prometheus 가 backend 를 스크레이프 못함 | `http://localhost:9090/targets` 확인 → `host.docker.internal:8000` UP 인지 |
| Windows 에서 `host.docker.internal` 못 찾음 | Docker Desktop Linux engine 미사용 | Docker Desktop 재시작 + WSL2 백엔드 활성화 |
| `pnpm dev` 가 5174 로 띄움 | 5173 점유 중 | 다른 vite 프로젝트 종료 또는 `vite.config.ts` 의 `BACKEND_URL` 만 8000 으로 맞추면 OK |

---

## 다음 단계

이 시나리오가 ✅ 된 다음, Phase 2 부터는 **수집된 raw 가 자동으로 staging → mart 까지 흐른다**. 그 검증 시나리오는 `docs/dev/PHASE_2_E2E.md` (Phase 2.2.11 에서 작성 예정).
