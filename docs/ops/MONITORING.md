# 관제 (Monitoring) — Phase 1.2.10

**대상:** 운영팀이 9월 합류하기 전 기본 가시성 확보. Loki 로그 집계는 Phase 2.

---

## 1. 메트릭 수집 (Prometheus)

### 1.1 노출 위치
- 백엔드: `GET /metrics` — 인증 없음, `/v1` 외부 (내부 scrape 전용)
- 운영(NKS): NetworkPolicy 로 `prometheus` namespace 만 접근 허용

### 1.2 핵심 메트릭

| 이름 | 타입 | 라벨 | 설명 |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `path`, `status` | 모든 HTTP 요청 수 |
| `http_request_duration_seconds` | Histogram | `method`, `path`, `status` | 요청 지연 (5ms~5s 버킷) |
| `db_pool_in_use` | Gauge | — | SQLAlchemy pool 사용 중 커넥션 |
| `ingest_requests_total` | Counter | `source_code`, `kind`, `status` | 수집 호출 (kind=api/file/receipt, status=created/dedup) |
| `ingest_dedup_total` | Counter | `source_code`, `kind` | dedup 히트 횟수 |
| `ingest_bytes_total` | Counter | `source_code`, `kind` | 신규 적재 누적 바이트 |

### 1.3 Cardinality 정책
- `path` 라벨은 **라우트 템플릿** 사용 (`/v1/users/{user_id}` ✅, `/v1/users/123` ❌)
- `source_code` 는 ASCII 64자 제한 (Phase 1.2.5 regex)
- 동적 라벨(예: user_id, request_id)은 라벨로 쓰지 않는다

---

## 2. 대시보드 (Grafana)

### 2.1 자동 프로비저닝
- `infra/grafana/provisioning/datasources/prometheus.yml` — Prometheus 자동 등록
- `infra/grafana/provisioning/dashboards/dashboards.yml` — 대시보드 자동 로드
- `infra/grafana/dashboards/core.json` — Phase 1 핵심 대시보드

### 2.2 패널 구성 (Pipeline Hub — Core)

| 패널 | PromQL | 의도 |
|---|---|---|
| 수집 QPS (1m) | `sum(rate(ingest_requests_total[1m]))` | 트래픽 |
| Dedup 비율 | `sum(rate(ingest_dedup_total[1m])) / sum(rate(ingest_requests_total[1m]))` | 중복 비중 (>30% 시 클라이언트 재전송 의심) |
| 24시간 누적 적재 | `sum(increase(ingest_requests_total{status="created"}[24h]))` | 일간 처리량 |
| 24시간 누적 바이트 | `sum(increase(ingest_bytes_total[24h]))` | Object Storage 비용 추적 |
| HTTP p95 by path | `histogram_quantile(0.95, sum by (path,le)(rate(http_request_duration_seconds_bucket[5m])))` | 느린 엔드포인트 발굴 |
| HTTP 5xx rate | `sum by (path)(rate(http_requests_total{status=~"5.."}[5m]))` | 장애 알람 신호 |
| 수집 source × kind | `sum by (source_code,kind,status)(rate(ingest_requests_total[5m]))` | 채널별 분포 |
| Outbox PENDING (placeholder) | `outbox_pending_total or vector(0)` | Phase 2 outbox publisher 도입 시 채워짐 |
| DB pool 사용 | `db_pool_in_use` | 커넥션 고갈 모니터링 |

### 2.3 Phase 2~4 추가 예정

| Phase | 메트릭 | 비고 |
|---|---|---|
| 2 | `outbox_pending_total`, `outbox_published_total`, `dramatiq_queue_lag` | Worker 도입 |
| 2 | `ocr_requests_total`, `ocr_duration_seconds` | CLOVA OCR 도입 |
| 2 | `standardization_confidence_bucket` | AI 표준화 |
| 4 | `public_api_requests_total`, API Key별 사용량 | 외부 서비스 |
| 4 | `dq_check_failures_total` | DQ 게이트 |

---

## 3. 감사 로그 (audit.access_log)

### 3.1 미들웨어 (`app/core/access_log.py`)
- 모든 `/v1/*` 응답 후 `audit.access_log` 비동기 INSERT
- Best-effort: INSERT 실패는 `warning` 로그만, 요청은 정상 완료
- 별도 DB 세션을 `asyncio.create_task` 로 fire-and-forget
- 제외 경로: `/metrics`, `/healthz`, `/readyz`, `/`, `/docs`, `/redoc`, `/openapi.json`

### 3.2 수집 필드
| 컬럼 | 출처 |
|---|---|
| `user_id` | JWT `sub` (unverified 디코드 — middleware 는 검증 비용 회피) |
| `api_key_id` | Phase 4 (Public API 시) |
| `method`, `path`, `status_code`, `ip`, `user_agent`, `duration_ms` | 자동 |
| `request_id` | RequestIdMiddleware 가 발급한 X-Request-ID |
| `occurred_at` | DB now() |

### 3.3 파티션
- 월별 RANGE 파티션. 2026-04 파티션 존재 (Phase 1.2.5 시점에 생성).
- 매월 1일 03:00 Airflow DAG 가 다음 달 파티션 자동 생성 (Phase 2 `monthly_partition_create.py`).
- 13개월 이상 파티션은 Object Storage archive 후 DETACH (Phase 4).

### 3.4 수동 조회 예시
```sql
-- 최근 1시간 5xx
SELECT method, path, status_code, request_id, duration_ms, occurred_at
FROM audit.access_log
WHERE occurred_at >= now() - interval '1 hour'
  AND status_code >= 500
ORDER BY occurred_at DESC LIMIT 50;

-- 특정 사용자 요청 흐름 (request_id 추적)
SELECT method, path, status_code, occurred_at
FROM audit.access_log
WHERE user_id = $1
  AND occurred_at >= CURRENT_DATE
ORDER BY occurred_at DESC LIMIT 100;
```

---

## 4. 로컬 기동 (`make dev-up`)

```bash
cp .env.example .env
make dev-up
```

| 서비스 | URL | 인증 |
|---|---|---|
| Prometheus | http://localhost:9090 | 없음 |
| Grafana | http://localhost:3000 | admin / admin (`.env` 의 `GRAFANA_ADMIN_PASSWORD` 변경 권장) |
| 백엔드 `/metrics` | http://localhost:8000/metrics | 없음 |

Prometheus 가 백엔드를 scrape 하려면 백엔드가 `host.docker.internal:8000` 에서 동작해야 함 (Windows/macOS Docker Desktop 자동 지원, Linux 는 `extra_hosts: host-gateway` 로 설정됨).

---

## 5. 알람 (Phase 1 미적용)

Phase 1.2.10 은 메트릭 수집만. Alertmanager 룰은 Phase 2에서 추가:
- `5xx_rate > 1%` 5분 rolling
- `outbox_pending > 1000` 5분 rolling
- `ocr_budget_alert` (월 예산 80%)
- `db_connection_pool_exhaustion`

---

## 6. NKS 이관 (Phase 4)

- `kube-prometheus-stack` (Prometheus Operator) 도입
- ServiceMonitor 로 `/metrics` 자동 발견
- Grafana 는 동일 대시보드 JSON 재사용
- AlertManager 알람 → Slack 채널
- Loki + Promtail 로 stdout JSON 로그 집계

자세한 NKS 마이그레이션은 `docs/ops/NKS_DEPLOYMENT.md` 4.2.4 참조.

---

## 7. 변경 이력

- 2026-04-25: Phase 1.2.10 — Prometheus + Grafana + audit.access_log 미들웨어 도입.
