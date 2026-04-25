# Phase 2 E2E 검증 시나리오

**대상:** 운영팀 (2026-09-01 합류 예정) — 이 문서를 처음부터 끝까지 따라가면 Phase 2
의 핵심 동작(수집 → outbox → OCR → 표준화 → price_fact → 운영자 화면) 이 모두 살아
있는지 60분 안에 확인할 수 있다.

**전제:**
- Phase 1 E2E (`docs/dev/PHASE_1_E2E.md`) 가 통과한 상태.
- Docker Desktop / Python 3.12+ / Node 20+ / pnpm / uv 설치.
- 외부 API 키:
  - `APP_CLOVA_OCR_URL` + `APP_CLOVA_OCR_SECRET` (NCP CLOVA OCR Document)
  - `APP_HYPERCLOVA_API_KEY` (NCP CLOVA Studio Embedding-Med)
  - `APP_UPSTAGE_API_KEY` (선택 — 폴백)
  키가 없으면 OCR/표준화 단계가 자동으로 crowd_task 로 떨어진다 (그래도 시나리오는
  통과 — placeholder 검증).

> Phase 1 E2E 가 단일 흐름(수집까지)이었다면 Phase 2 E2E 는 *수집 후 자동 파이프
> 라인이 mart 까지 흐르는지* + *운영자 화면 3종이 작동하는지* 두 축을 본다.

---

## 0. 사전 준비

```bash
# 0-1. 환경변수
cp .env.example .env
# OCR/임베딩 키 채우기 (선택 — 없어도 시나리오 통과 가능, crowd_task 로 흐름)
$EDITOR .env

# 0-2. 인프라 + 관제 + 워커 일괄 기동
make dev-up        # PG / Redis / MinIO / Prometheus / Grafana / Loki / Promtail
make airflow-up    # Airflow LocalExecutor (init → webserver → scheduler)
make worker-up     # 5종 워커 컨테이너 (outbox / ocr / transform / price_fact /
                   #   db_incremental / crawler) 빌드+기동

# 0-3. DB 마이그레이션 (Phase 2 까지 — 0001~0014 적용)
make db-migrate

# 0-4. 시드 (Phase 1 E2E 의 admin 사용자 + 표준코드 1건)
cd backend
uv run python ../scripts/seed_admin.py

# 표준코드 시드 — 운영팀 합류 후 정식 시드 스크립트(2.2.5.x) 도입 전, 1건만 수동:
make dev-psql <<SQL
INSERT INTO mart.standard_code
  (std_code, category_lv1, item_name_ko, aliases, default_unit, source_authority, is_active)
VALUES
  ('FRT-FUJI-APPLE', '과일', '후지사과', ARRAY['사과','후지'], 'box', 'aT KAMIS', true)
ON CONFLICT DO NOTHING;
SQL

# 0-5. Backend / Frontend 기동 (별도 터미널)
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd ../frontend && pnpm install && pnpm dev   # http://localhost:5173
```

확인:
```bash
curl -s http://localhost:8000/healthz   # {"status":"ok"}
curl -s http://localhost:8000/readyz    # {"status":"ready",...}
docker ps --format "table {{.Names}}\t{{.Status}}" | grep dp_   # 모든 dp_* healthy
```

---

## 1. API 수집 → outbox publisher → Streams 흐름 검증

```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login_id":"admin","password":"admin"}' | jq -r .access_token)

# 1-1. source 등록
curl -s -X POST http://localhost:8000/v1/sources \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"source_code":"PHASE2_E2E_API","source_name":"Phase 2 E2E","source_type":"API","is_active":true,"config_json":{}}' | jq .

# 1-2. ingest 1건
curl -s -X POST http://localhost:8000/v1/ingest/api/PHASE2_E2E_API \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: phase2-e2e-001' \
  -d '{"items":[{"sku":"E-001","name":"후지 사과 5kg","price":24900,"unit":"box","retailer_code":"E-MART","seller_name":"이마트 용산점"}]}' | jq .
```

DB 검증 — outbox PENDING 적재 후 publisher 가 stream 으로 이송하는지:

```sql
-- make dev-psql
SELECT count(*) FROM run.event_outbox WHERE status='PENDING';   -- 1
SELECT count(*) FROM run.event_outbox WHERE status='PUBLISHED'; -- 0 (publisher 호출 전)
```

publisher 강제 호출 (Phase 2.2.x 의 자동 트리거 도입 전):
```bash
make worker-logs   # 다른 터미널 로그 따라가기
docker exec dp_worker_outbox python -c \
  "from app.workers.outbox_publisher import publish_outbox_batch; print(publish_outbox_batch())"
```

기대 출력: `{"selected": 1, "published": 1, "failed": 0}`

```sql
SELECT count(*) FROM run.event_outbox WHERE status='PUBLISHED'; -- 1
```

Redis Streams 검증:
```bash
docker exec dp_redis redis-cli XLEN dp:events:raw_object   # 1
```

---

## 2. Transform 워커가 standard_record + price_observation 적재

`worker-transform` actor 는 `staging.ready` 이벤트를 listen 하지만, 1단계 chassis
에서는 outbox publisher 가 `dp:events:raw_object` 로만 발행한다. Phase 2.2.7 후속
consumer loop 가 도입되기 전엔 아래처럼 직접 enqueue:

```bash
docker exec dp_worker_transform python -c "
from app.workers.transform_worker import process_transform_event
print(process_transform_event(event_id='e2e-tx-001', raw_object_id=1, partition_date_iso='2026-04-25'))
"
```

기대: `{"status": "processed", "record_count": 1, "matched_count": 1, "crowd_task_count": 0}`

DB 검증:
```sql
SELECT product_name_raw, std_code, std_confidence
  FROM stg.price_observation
 ORDER BY obs_id DESC LIMIT 5;
-- 후지 사과 5kg | FRT-FUJI-APPLE | 70~99
```

`std_code` 가 채워졌으면 trigram 매칭 성공. NULL 이면:
- 표준코드 시드 재확인 (0번 단계 SQL)
- 또는 임계값 낮춤(`APP_STD_TRIGRAM_THRESHOLD=0.5` 후 worker 재기동)

---

## 3. price_fact 워커 → mart 반영 (latency 측정)

```bash
# staging.ready 이벤트가 outbox 에 있을 것 — 같은 publish_outbox_batch 트리거.
docker exec dp_worker_outbox python -c \
  "from app.workers.outbox_publisher import publish_outbox_batch; print(publish_outbox_batch())"

docker exec dp_worker_price_fact python -c "
from app.workers.price_fact_worker import process_price_fact_event
print(process_price_fact_event(event_id='e2e-pf-001', raw_object_id=1, partition_date_iso='2026-04-25'))
"
```

기대: `{"status": "processed", "inserted": 1, "sampled": 0, "held": 0, "skipped": 0}`

DB 검증:
```sql
SELECT pm.canonical_name, pf.price_krw, pf.observed_at
  FROM mart.price_fact pf
  JOIN mart.product_master pm ON pm.product_id = pf.product_id
 ORDER BY pf.created_at DESC LIMIT 1;
-- 후지 사과 5kg | 24900.00 | (1초 이내)
```

수집 → mart latency 측정:
```promql
# Grafana → Explore → Prometheus
histogram_quantile(0.95, sum by (le)(rate(price_fact_observed_to_inserted_seconds_bucket[5m])))
```

목표: **p95 < 60s** (SLA — Phase 2 비기능 기준 2.4).

---

## 4. OCR 영수증 시나리오 (CLOVA 키 있을 때만)

```bash
curl -s -X POST http://localhost:8000/v1/ingest/receipt \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Idempotency-Key: phase2-e2e-receipt-001' \
  -F "file=@tests/fixtures/receipt-sample.jpg" \
  -F "source_code=PHASE2_E2E_API" | jq .

# raw_object_id 확보 후
docker exec dp_worker_ocr python -c "
from app.workers.ocr_worker import process_ocr_event
print(process_ocr_event(event_id='e2e-ocr-001', raw_object_id=<위 raw_object_id>, partition_date_iso='2026-04-25'))
"
```

기대 outcome — confidence ≥ 0.85 이면 `ocr.completed` outbox + `raw.ocr_result` 적재.
미달이면 `crowd_task("ocr_low_confidence")` 추가 적재. 둘 다 정상 흐름.

---

## 5. Crowd 검수 큐 운영자 화면

브라우저 http://localhost:5173 → 좌측 Sidebar **검수 큐** 진입 (admin 또는 reviewer 권한).

확인:
- status 탭 PENDING/REVIEWING/APPROVED/REJECTED 이동 시 표 갱신
- reason 필터 (ocr/std/price_fact_low/sample) 클릭 시 표 좁혀짐
- 행 클릭 → 우측 패널에 raw_object payload + ocr_result 텍스트 표시
- "검수 시작" → status PENDING → REVIEWING 전이 + reviewed_at 기록
- "승인 (placeholder)" 클릭 → toast "Phase 4 정식 검수에서 활성화" — 정상 동작.
  실제 비즈니스 효과(mart 재반영, alias 추가) 는 Phase 4 — ADR-0006 참조.

REST 검증:
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/v1/crowd-tasks?status=PENDING&limit=10' | jq 'length'
```

---

## 6. Dead Letter replay 시연

의도적 실패 시드:

```bash
docker exec dp_redis redis-cli FLUSHDB   # (선택) 깨끗한 시작
make dev-psql <<SQL
INSERT INTO run.dead_letter (origin, payload_json, error_message, stack_trace)
VALUES ('publish_outbox_batch',
        '{"args":[],"kwargs":{},"message_id":"e2e-dl-001"}'::jsonb,
        'simulated failure for e2e',
        'Traceback (most recent call last):\n  File "fake.py"');
SQL
```

브라우저 좌측 Sidebar **Dead Letter** (admin only) → 표에 1건 → "재발송" 버튼.

기대:
- toast "재발송 완료 — publish_outbox_batch / message_id: ..."
- DB: `replayed_at` / `replayed_by` 채워짐
- `worker-outbox` 컨테이너 로그에 actor 호출 기록

REST:
```bash
curl -s -X POST http://localhost:8000/v1/dead-letters/<dl_id>/replay \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

## 7. Runtime 모니터 (Grafana iframe)

브라우저 좌측 Sidebar **Runtime 모니터** → Grafana iframe 으로 `pipeline-hub-runtime`
대시보드 표시. 확인:
- Workers throughput 4 패널 — 위에서 한 ingest/transform/price_fact 호출이 5분 rate
  로 보이는지
- 단계별 latency p95 — observed → price_fact 가 60s 미만
- Outbox PENDING / Dead Letter / Streams 길이 stat — 위 6번 시드 후 변화 확인
- Worker 로그 패널 (Loki) — 마지막 100줄에 `event=outbox.published`,
  `event=transform.completed` 등이 보여야 함

---

## 8. 백로그 게이지 + 알람 임계 확인

```promql
outbox_pending_total                           # 0~1
dead_letter_pending_total                      # 0
dramatiq_queue_lag_seconds{topic="raw_object"} # 1~수십
sum by (provider, status)(rate(ocr_requests_total[5m]))
sum by (outcome)(rate(price_fact_inserts_total[5m]))
```

운영 알람 임계 (Phase 2.2.x 후속 Alertmanager 도입 시):
- `outbox_pending_total > 1000` 5분 지속 → publisher 정지 의심
- `dead_letter_pending_total > 0` 즉시 → 운영자 호출
- `histogram_quantile(0.95, price_fact_observed_to_inserted_seconds_bucket) > 60` →
  파이프라인 lag 알람

---

## 9. Loki 로그 LogQL 검증

Grafana → Explore → Loki:
```logql
{service="dp_worker_outbox"} | json | event="outbox.published"
{service=~"dp_worker.*"} | json | level=~"error|warning"
{service="dp_backend"} | json | request_id="<요청 id>"   # 1번 시나리오의 X-Request-ID
```

기대:
- `dp_worker_*` 컨테이너 stdout 이 모두 Loki 에 수집되고 있음
- structlog JSON 의 `level/event/source_code/request_id` 가 추출되어 라벨 / 필터링
  가능
- 같은 request_id 로 backend → worker 흐름 연결 추적 가능

---

## 10. Sentry 오류 보고 (DSN 설정 시만)

`.env` 의 `APP_SENTRY_DSN` 채운 상태에서:

```bash
# 의도적 500 — 존재하지 않는 source 에 ingest 시도
curl -s -X POST http://localhost:8000/v1/ingest/api/__nonexistent__ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"items":[]}'
```

Sentry 프로젝트 화면 → Issues 에 새 항목 등장. 확인:
- `request.headers.Authorization` 이 `[Filtered]` (PII 스크럽)
- `request.url`, `transaction` (FastAPI route) 정상 노출
- stack trace 와 release / environment 라벨 부착

---

## 11. DB-to-DB 증분 + 크롤러 (선택)

```bash
# DB-to-DB 동일 PG 의 schema 시뮬 (자세한 스크립트는 backend/tests/integration/test_db_incremental.py 참조)

# Crawler 은 stub 모드 또는 외부 사이트 1회 호출
docker exec dp_worker_crawler python -c "
from app.workers.crawler_worker import process_crawl_event
print(process_crawl_event(source_code='PHASE2_E2E_CRAWL', url='https://example.com'))
"
```

`raw.raw_web_page` + Object Storage `crawl/...` key + outbox `crawler.page.fetched`
적재 확인.

---

## 통과 기준 (Definition of Done)

| 단계 | 검증 | 결과 |
|---|---|---|
| 0 | dev-up + airflow-up + worker-up + db-migrate 무에러 | □ |
| 1 | ingest API → outbox PENDING 1 + publisher 호출 후 PUBLISHED 1 + Streams XLEN 1 | □ |
| 2 | transform actor → standard_record + price_observation + std_code 매핑 | □ |
| 3 | price_fact actor → mart.product_master + price_fact + p95 < 60s | □ |
| 4 | (선택) OCR — confidence ≥ 0.85 면 ocr_result, 미만이면 crowd_task | □ |
| 5 | Crowd 검수 큐 화면 동작 + REVIEWING 전이 + 승인 placeholder toast | □ |
| 6 | Dead Letter 시드 + Replay 버튼 → replayed_at 마킹 + actor 재호출 | □ |
| 7 | Runtime 모니터 iframe + 9 패널 모두 데이터 보임 | □ |
| 8 | 백로그 게이지 (outbox_pending / dead_letter / queue_lag) Prometheus 응답 정상 | □ |
| 9 | Loki LogQL 로 worker stdout + request_id 추적 | □ |
| 10 | (DSN 설정 시) Sentry 에 새 issue + Authorization 마스킹 | □ |
| 11 | (선택) DB-to-DB watermark 전진 + Crawler raw_web_page | □ |

8/11 이상 ✅ 면 Phase 2 의 Pipeline Runtime 이 살아 있는 것이다 (4·10·11 은 외부
키/사이트 의존 — 키 없으면 자동 skip).

---

## 자주 막히는 곳

| 증상 | 원인 | 해결 |
|---|---|---|
| outbox_publisher actor 가 message 를 만들지 않음 | API 가 commit 후 `.send()` 하지 않음 (현재는 수동 호출 패턴) | `docker exec dp_worker_outbox python -c "from app.workers.outbox_publisher import publish_outbox_batch; print(publish_outbox_batch())"` |
| transform 후 std_code = NULL | 표준코드 시드 누락 또는 trigram 임계 너무 높음 | 0번의 시드 SQL 재실행 / `APP_STD_TRIGRAM_THRESHOLD=0.5` |
| price_fact INSERT 안 됨 (held) | std_confidence < 80 | trigram/embedding 둘 다 매칭이 약한 상태 — 표준코드 사전 보강 |
| OCR `circuit breaker is OPEN` | CLOVA 키 잘못됨 또는 요청 5회 연속 실패 | 키 확인 / 30s 대기 후 재시도 (cooldown) |
| Dead Letter Replay 4xx | actor 가 broker 에 등록 안 됨 (origin 이름 불일치) | `app/workers/__init__.py` 의 등록 모듈 확인 |
| Loki 로그 비어 있음 | promtail 이 docker socket 권한 부족 (Linux) | `chmod 666 /var/run/docker.sock` 또는 promtail user=0 |
| Runtime iframe 빈 화면 | Grafana 가 다른 origin / 인증 필요 | `VITE_GRAFANA_URL` 또는 상단 입력란 조정. 운영(NKS) 은 SSO 필요 |

---

## 다음 단계

이 시나리오가 ✅ 된 다음, Phase 3 부터는 **사용자가 UI 에서 노드를 조립해 만든
파이프라인** 이 자체 DAG 실행기로 동작한다. 그 검증 시나리오는
`docs/dev/PHASE_3_E2E.md` (Phase 3.x 후속 작성 예정).
