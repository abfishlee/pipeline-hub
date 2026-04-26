# Backfill 운영법

> Phase 5.2.8 STEP 11 (Q4) — chunk_unit=day, chunk_size=1, max_parallel_runs=2,
> batch_size=5000, statement_timeout=60s, lock_timeout=3s, sleep_between=1s,
> resume_checkpoint required.

## 1년치 backfill 시나리오

```bash
# 1. 잡 생성 (365 chunks).
curl -X POST /v2/backfill -d '{
  "domain_code": "agri",
  "resource_code": "PRICE_FACT",
  "target_table": "mart.price_fact",
  "start_at": "2025-01-01T00:00:00+00:00",
  "end_at":   "2026-01-01T00:00:00+00:00",
  "chunk_unit": "day",
  "chunk_size": 1,
  "max_parallel_runs": 2
}'
# → job_id=88, total_chunks=365, status=PENDING.

# 2. 실행 시작.
curl -X POST /v2/backfill/88/start
# → status=RUNNING, started_at=now.

# 3. 진행률 모니터링.
watch -n 30 'curl -s /v2/backfill/88 | jq ".completed_chunks,.failed_chunks,.total_chunks"'
```

## chunk 진행 흐름 (worker 입장)

```
1. SELECT * FROM ctl.backfill_chunk
    WHERE job_id = 88 AND status = 'PENDING'
    ORDER BY chunk_index LIMIT max_parallel_runs;
2. for each chunk:
     UPDATE chunk SET status='RUNNING' WHERE chunk_id = X;
     SET LOCAL statement_timeout = 60000;
     SET LOCAL lock_timeout = 3000;
     INSERT INTO mart.price_fact ... WHERE ymd = chunk.ymd ...;
     mark_chunk_done(chunk_id, success=True, rows_processed=N, checkpoint={...});
3. sleep 1s (sleep_between_chunks_ms);
4. 다음 batch.
```

## 실패 + Resume

```bash
# chunk 30 이 timeout 으로 실패.
# error_message + checkpoint_json 보존됨.
curl /v2/backfill/88/chunks?status=FAILED
# → [{"chunk_id": 130, "chunk_index": 30, "attempts": 3, ...}]

# 옵션 A: 같은 chunk 재실행 (검증 후).
curl -X POST /v2/backfill/chunk/done \
  -d '{"chunk_id": 130, "success": true, "rows_processed": 4500, "checkpoint": {...}}'

# 옵션 B: 부분 backfill 새 잡 생성.
curl -X POST /v2/backfill -d '{
  ...,
  "start_at": "2025-01-30T00:00:00+00:00",
  "end_at":   "2025-01-31T00:00:00+00:00"
}'
```

## 권장 default 별 시나리오

| 데이터 규모 | chunk_unit | chunk_size | max_parallel | batch_size |
|---|---|---|---|---|
| < 1만 rows/일 | day | 1 | 2 | 5_000 |
| 1만~10만 rows/일 (현재) | day | 1 | 2 | 10_000 |
| 10만~30만 rows/일 (Phase 5 목표) | day | 1 | 2 | 10_000 |
| 30만+ rows/일 | hour | 6 | 2 | 5_000 |
| 단발 backfill 5년치 | week | 1 | 1 | 20_000 |

## 시간대별 throttle 가이드

```
00:00 ~ 06:00 (낮은 부하):  max_parallel_runs = 3~4
07:00 ~ 22:00 (일반 운영):  max_parallel_runs = 1~2
22:00 ~ 24:00 (저녁 폐쇄):  max_parallel_runs = 3
DB CPU > 70%:               throttle to 1
Redis lag > 5s:             pause until recover
```

→ 본 throttle 은 *수동 조정* (Phase 5 MVP). Phase 6 에서 자동 throttle.

## 실패 패턴 + 대응

| 에러 | 원인 | 조치 |
|---|---|---|
| `statement_timeout` | chunk_size 너무 큼 | chunk_unit=hour 로 분할 |
| `lock_timeout` | 동시 INSERT 충돌 | max_parallel 감소 |
| `unique violation` | 멱등성 깨짐 | `ON CONFLICT DO NOTHING` 또는 mart upsert mode |
| OOM | batch_size 너무 큼 | 5_000 으로 줄임 |
| `Redis lag` 동시 폭증 | parallel 너무 높음 | sleep_between_chunks_ms 증가 |

## DB 부하 측정

```bash
# backfill 진행 중 SLO 측정.
curl /v2/perf/slo/summary?metric_code=backfill_chunk_duration_ms
# → last/avg/max + verdict.

# Grafana 대시보드: pg_stat_activity 활성 연결 수, Lock wait, WAL 생성률.
```
