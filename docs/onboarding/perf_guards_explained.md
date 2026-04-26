# 성능 가드레일 해설 (5축 + 10 SLO)

> Phase 5.2.8 STEP 11. 사용자 자유도와 운영 안정성의 trade-off 를 가드레일로 분리.

## 5축 가드레일

### 1. 수집 (`source_throttle`)
- 위치: `data_source.config_json` + ingest_worker.
- 변수: `poll_interval_sec` / `batch_size` / `rate_limit_per_min` / `max_concurrency`.
- **위반 시**: ingest_worker 가 자동 throttle (sleep + retry).

### 2. Worker / Queue (`worker_routing`)
- 위치: `app/workers/__init__.py` 의 queue routing.
- 변수: domain/source 별 dedicated queue, OCR/AI heavy job 분리.
- **위반 시**: backpressure — Redis lag 임계 초과 시 polling throttle.

### 3. DB / Schema (`db_advisor`)
- 위치: Mart Designer (`app/domain/mart_designer.py`) + Performance Coach.
- 변수: partition_key / JSONB 컬럼화 / 인덱스 / row size / retention.
- **위반 시**: Mart Designer 가 *DRAFT 단계에서 경고*.

### 4. DQ / SQL (`sql_coach`)
- 위치: `app/domain/perf_guards/sql_coach.py`.
- 변수: timeout_ms / sample_limit / max_scan_rows / incremental_only.
- **검사**: EXPLAIN(JSON) → seq_scan / cross_join / unbounded / missing_index 등.
- **위반 시**: verdict=BLOCK → 노드 실행 자체 차단.

### 5. Backfill (`backfill`)
- 위치: `app/domain/perf_guards/backfill.py` + `/v2/backfill`.
- 변수: chunk_unit / chunk_size / batch_size / max_parallel / sleep_between.
- **위반 시**: 잡 생성 단계에서 거부 (10_000 chunk 한도).

## 10 종 SLO + 임계값

| metric_code | unit | warn | block | 측정 주체 |
|---|---|---|---|---|
| `ingest_p95_ms` | ms | 5_000 | 30_000 | ingest_worker 가 직접 |
| `raw_insert_throughput_per_sec` | rows/s | <50 | <10 | ingest_worker (낮을수록 위험) |
| `redis_lag_ms` | ms | 5_000 | 60_000 | sse_router or worker |
| `sse_delay_ms` | ms | 3_000 | 15_000 | SSE middleware |
| `sql_preview_p95_ms` | ms | 2_000 | 10_000 | SQL Studio |
| `dq_custom_sql_p95_ms` | ms | 5_000 | 30_000 | DQ_CHECK 노드 |
| `backfill_chunk_duration_ms` | ms | 60_000 | 300_000 | backfill worker |
| `db_query_p95_ms` | ms | 1_000 | 5_000 | pg_stat_statements |
| `worker_job_duration_p95_ms` | ms | 30_000 | 120_000 | dramatiq 미들웨어 |
| `dlq_pending_count` | count | 100 | 1_000 | DB count |

**측정 방법**:
- 자동 측정: `POST /v2/perf/baseline/measure` (DLQ + DB query p95 — 즉시 측정).
- application 측정: 각 worker / middleware 가 `record_slo` 호출.
- prometheus → application 이 결과를 DB 적재 (audit.perf_slo).

**verdict 산출**:
```python
if metric == 'raw_insert_throughput_per_sec':  # 역방향
    if value <= block: 'BLOCK'
    elif value <= warn: 'WARN'
    else: 'OK'
else:
    if value >= block: 'BLOCK'
    elif value >= warn: 'WARN'
    else: 'OK'
```

## SQL Performance Coach (Q3 backend)

`/v2/perf/coach/analyze` 호출:

```bash
curl -X POST /v2/perf/coach/analyze -d '{
  "domain_code": "agri",
  "sql": "SELECT * FROM mart.price_fact WHERE ymd >= '2026-01-01'"
}'
# → {"verdict":"WARN","warnings":[
#       "missing_index_candidate: Seq Scan + Filter on price_fact (ymd >= ...)"],
#     "estimated_rows":120000,"estimated_cost":15300}
```

7 검사:
1. `seq_scan_on_large_table` — `pg_class.reltuples ≥ 100_000`.
2. `estimated_rows_exceeded` — `Plan Rows > 5_000_000`.
3. `estimated_cost_exceeded` — `Total Cost > 1_000_000`.
4. `cross_join_detected` — Nested Loop + Join Filter 없음.
5. `unbounded_query` — WHERE/LIMIT 둘 다 없음.
6. `missing_index_candidate` — Seq Scan + Filter 가 있는 노드.
7. `timeout_risk` — `Total Cost > 500_000`.

verdict = BLOCK 인 sql 은 노드 실행 거부 (DQ_CHECK / SQL_INLINE 등).

## Kafka 도입 트리거 (ADR-0020)

현재 미도입. 4 트리거:
1. `redis_lag_ms` ≥ 30_000 가 30분+ 지속.
2. 1주+ replay/retention 필요.
3. 외부 partner 의 Kafka topic 직접 publish 요구.
4. CDC 기반 multi-DB 동기화.

위 중 하나라도 충족 → ADR-0020 의 7주 도입 플랜.
