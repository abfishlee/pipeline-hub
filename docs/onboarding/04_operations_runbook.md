# 4. 운영 / 장애 대응 Runbook

## 일상 운영 (daily)

| 시간 | 작업 |
|---|---|
| 09:00 | DLQ pending 확인 (`audit.perf_slo` 의 `dlq_pending_count`) |
| 09:00 | shadow_diff mismatch_ratio (Phase 5.2.5 활성 도메인만) |
| 09:30 | overnight 배치 (Airflow Phase 2) 결과 + alert 채널 검토 |
| 13:00 | API key rate-limit 위반 (`audit.public_api_usage` 5xx 비율) |
| 17:00 | backfill 진행 (`/v2/backfill?status=RUNNING`) — chunk 진행률 |

## 알림 채널 + 임계값 (Phase 5.2.8)

| Metric | WARN | BLOCK | 채널 |
|---|---|---|---|
| `ingest_p95_ms` | 5_000 | 30_000 | Slack #ingest-alerts |
| `redis_lag_ms` | 5_000 | 60_000 | PagerDuty (60s 초과 시) |
| `dlq_pending_count` | 100 | 1_000 | Slack + Email |
| `sql_preview_p95_ms` | 2_000 | 10_000 | Slack #sql-studio |
| `dq_custom_sql_p95_ms` | 5_000 | 30_000 | Slack #data-quality |
| `worker_job_duration_p95_ms` | 30_000 | 120_000 | Slack #worker-alerts |
| `backfill_chunk_duration_ms` | 60_000 | 300_000 | dashboard 만 (운영자 직접 확인) |

## 장애 대응 절차

### 시나리오 A — Worker 가 처리 못 함 (DLQ 폭증)

1. **확인**: `SELECT origin, COUNT(*) FROM run.dead_letter WHERE replayed_at IS NULL GROUP BY origin;`
2. **원인 파악**: `payload_json`, `error_message`, `stack_trace`.
3. **임시 조치**: `dramatiq` worker process 수 증가 (`--processes 2 --threads 8`).
4. **replay**: `/v1/dead-letters/{id}/replay` (ADMIN). 1건 성공 후 일괄.
5. **재발 방지**: 원 코드 fix → PR → migration 필요 시 hotfix.

### 시나리오 B — Public API 5xx 폭증

1. `/public/v1/*` 또는 `/public/v2/*`?
2. `audit.public_api_usage WHERE status_code >= 500 ORDER BY occurred_at DESC LIMIT 50;`
3. Redis 캐시 폭주? → `_cache_get` log 확인.
4. RLS GUC 누락? → `set_session_role` 가 항상 호출되는지 확인.
5. 임시: 해당 api_key revoke (`POST /v1/api-keys/{id}/revoke`).

### 시나리오 C — Shadow diff 임계 초과 (Phase 5.2.5 활성)

1. `/v2/cutover/diff-report?domain_code=agri&resource_code=PRICE_FACT&window_hours=1`
2. `mismatch_ratio` 가 1% 이상이면 자동으로 cutover 차단됨.
3. 원인 분석:
   - `audit.shadow_diff WHERE diff_kind = 'value_mismatch' ORDER BY occurred_at DESC LIMIT 20;`
   - `v1_payload` vs `v2_payload` 비교.
4. 해결: v2 코드 fix 후 shadow 다시 1주일.

### 시나리오 D — backfill 중간 실패

1. `/v2/backfill/{job_id}/chunks?status=FAILED` — 실패 chunk 목록.
2. 각 chunk 의 `error_message` + `checkpoint_json` 확인.
3. `chunk_id` 별로 다시 SUCCESS 마킹할 정상화 필요한가?
4. 부분 재실행: 새 backfill_job 생성 (해당 시점만 좁게) — 기존 job 은 PARTIAL.

### 시나리오 E — DB 디스크 폭주

1. `du -sh /var/lib/postgresql/data/*` (NCP 의 경우 dashboard 에서).
2. 가장 큰 schema: `SELECT schemaname, pg_size_pretty(SUM(pg_relation_size(oid))) FROM pg_class JOIN pg_namespace ON ... GROUP BY schemaname;`
3. raw.raw_object 가 90%+ 차지면:
   - Phase 4.2.7 의 `partition_archive` 가 정상 동작 중인가?
   - `audit.partition_archive_log` 의 최근 row 확인.
4. 임시: 가장 오래된 partition 1개 archive 강제 트리거.

### 시나리오 F — RLS / 권한 사고

1. **잘못된 도메인 데이터 노출**: 즉시 해당 api_key revoke.
2. `audit.access_log WHERE api_key_id = X AND occurred_at > '...'` 로 영향 범위.
3. RLS policy 가 정확히 적용됐는지 `pg_policies` view 확인.
4. fix → 새 migration → review → ADMIN APPROVE → PUBLISHED.

## v2 generic 운영 도구 (Phase 5.2.4 STEP 7~)

| 도구 | URL | 누가 |
|---|---|---|
| Mart Designer dry-run | `POST /v2/dryrun/mart-designer` | DOMAIN_ADMIN |
| DQ Rule preview | `POST /v2/dq-rules/preview` | OPERATOR+ |
| Mini Publish Checklist | `POST /v2/checklist/run` | APPROVER+ |
| Cutover diff report | `GET /v2/cutover/diff-report` | ADMIN |
| Cutover apply | `POST /v2/cutover/apply` | ADMIN ★ |
| SQL Performance Coach | `POST /v2/perf/coach/analyze` | OPERATOR+ |
| Backfill 생성 | `POST /v2/backfill` | OPERATOR+ |
| domain user 권한 | `POST /v2/permissions/grant` | ADMIN |

## 쇼크 흡수 (capacity reserve)

현재 정책 — Redis Streams + Dramatiq + PG 단일 인스턴스 가정.
- *수직* 스케일 (NCP CPU/RAM 증액) 가 1순위.
- *수평* 은 worker process 수만 (state stateless 보장 — Phase 1 부터 정책).

Kafka 도입 트리거는 **ADR-0020** 에 명시. Redis lag 30s+ 가 30분 이상 지속 시 알림.

## 운영팀 6~7명 합류 후 분담 (Phase 4.0.2 매트릭스)

| Owner | 책임 영역 |
|---|---|
| DBA | migration 검토, partition 운영, RLS 정책 |
| SRE | NKS 배포, alert/Grafana, capacity |
| Data Engineer | DQ rule 작성, Mart Designer, 새 도메인 onboarding |
| Backend | API 변경, worker tuning, ADR 작성 |
| Frontend | Designer/SQL Studio 사용성, 신규 페이지 |
| Security | API Key, RLS, audit 로그 검토 |
| (옵션) Domain Owner | 도메인별 명세 + 사업측 소통 |

→ Phase 4 합류 시 위 6~7명이 자율 운영 가능하도록 본 문서 갱신.
