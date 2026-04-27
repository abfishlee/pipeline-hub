# DB 테이블 분류 매트릭스 — 운영 이관 전 가이드

**최종 갱신:** 2026-04-27 (Phase 8.4)
**대상 DB:** `datapipeline` (PostgreSQL 16 + pgvector)
**검증 출처:** dp_postgres 컨테이너 실측 + Phase 8.3 cleanup migration 0052

---

## 0. 분류 기준

| 분류 | 의미 | 운영 정책 |
|---|---|---|
| 🟢 **active** | 본 사업 (4 유통사 + KAMIS) 운영에 직접 사용 | 모니터링 + 백업 + autovacuum 적극 |
| 🟡 **demo** | 시연/리허설 데이터 (Phase 8 synthetic) | seed 재실행 가능, 백업 제외 가능 |
| 🔵 **future** | 공통 플랫폼 미래 기능 (사업 진입 전 0 rows) | 스키마 유지, 활성화 시점 도래 시 사용 |
| 🟣 **test-only** | 통합 테스트 fixture / 검증용 | 운영 DB 진입 시 truncate or drop |
| ⚫ **deprecated** | v1 흔적, 제거 완료 또는 예정 | Phase 8.3 에서 일부 제거 |

---

## 1. 스키마별 분류

### 🟢 active — 본 사업 운영 핵심

| 스키마.테이블 | 용도 |
|---|---|
| `domain.domain_definition` / `domain.resource_definition` / `domain.public_api_connector` / `domain.field_mapping` / `domain.sql_asset` / `domain.load_policy` / `domain.dq_rule` / `domain.inbound_channel` / `domain.source_provider_binding` / `domain.provider_definition` / `domain.source_contract` / `domain.mart_design_draft` | v2 generic 플랫폼 자산 (4 유통사 + 향후 도메인 공용) |
| `wf.workflow_definition` / `wf.node_definition` / `wf.edge_definition` / `wf.pipeline_release` / `wf.pipeline_template` / `wf.workflow_dag_lock` | Canvas workflow 정의 |
| `run.pipeline_run` (파티션 12개) / `run.node_run` / `run.ingest_job` / `run.event_outbox` / `run.hold_decision` | 실행 이력 |
| `raw.raw_object` / `raw.raw_object_audit` | 원천 데이터 보존 |
| `audit.access_log` (파티션) / `audit.inbound_event` (파티션) / `audit.security_event` / `audit.public_api_usage` / `audit.sql_execution_log` / `audit.perf_slo` | 감사/모니터링 |
| `service_mart.product_price` / `service_mart.std_product` | 4 유통사 통합 마트 (배달 서비스용) |
| `mart.standard_code` / `mart.product_master` / `mart.retailer_master` / `mart.seller_master` / `mart.product_mapping` | 표준코드 + 마스터 |
| `ctl.app_user` / `ctl.role` / `ctl.user_role` / `ctl.api_key` / `ctl.user_domain_role` / `ctl.dry_run_record` / `ctl.partition_archive_log` | 사용자/권한/운영 |
| `dq.quality_result` | DQ 실행 결과 |
| `crowd.task` (view) / `crowd.crowd_task` | 검수 큐 |

### 🟡 demo — 시연 데이터 (4 유통사 가상)

| 스키마 | 용도 |
|---|---|
| `emart_mart.*` / `homeplus_mart.*` / `lottemart_mart.*` / `hanaro_mart.*` | Phase 8 synthetic — 각 유통사 mart |
| `emart_stg.*` / `homeplus_stg.*` / `lottemart_stg.*` / `hanaro_stg.*` / `agri_stg.*` / `stg.*` | staging |
| `pos_mart.*` | POS 시연 |

### 🔵 future — 공통 플랫폼 미래 기능 (현재 0 rows)

| 스키마.테이블 | 활성화 조건 |
|---|---|
| `raw.db_snapshot`, `raw.db_cdc_event` | CDC 활성 시 |
| `ctl.cdc_subscription` | CDC 활성 시 (CLAUDE.md § 3 — CDC 소스 3개 초과 또는 500K rows/일 초과) |
| `crowd.payout`, `crowd.skill_tag` | Crowd 정식 운영 시 |
| `mart.price_daily_agg` | 일별 집계 배치 도입 시 |
| `agri_mart.kamis_price` | Phase 9 KAMIS 실증 |
| `audit.provider_usage_*` (파티션) | Provider Registry 정식 운영 시 |
| `mart.standard_code.embedding` | 표준코드 1k+ rows 도달 시 (현재 18 rows — IVFFLAT 비효율) |

### ⚫ deprecated — 제거 완료 / 예정

| 항목 | 처리 |
|---|---|
| `iot_spike_mart.*` | ✅ Phase 8.3 (migration 0052) 에서 DROP SCHEMA CASCADE |
| `ctl.connector` | ✅ Phase 8.3 에서 DROP TABLE |
| `ctl.api_key.expired_at` | ✅ Phase 8.3 에서 DROP COLUMN (expires_at 단일화) |
| `ctl.data_source.schedule_cron` / `owner_team` / `retailer_id` (현재 100% null) | ⚠ Phase 4 운영 이관 전 검토 — domain 쪽으로 역할 이동 |

---

## 2. 운영 ANALYZE/VACUUM 가이드

### 2.1 즉시 (운영 시작 시)

```sql
-- 운영 핵심 테이블 통계 갱신
ANALYZE service_mart.product_price;
ANALYZE service_mart.std_product;
ANALYZE mart.standard_code;
ANALYZE mart.retailer_master;
ANALYZE domain.public_api_connector;
ANALYZE domain.field_mapping;
ANALYZE domain.sql_asset;
ANALYZE domain.dq_rule;
ANALYZE domain.inbound_channel;
ANALYZE wf.workflow_definition;
ANALYZE wf.node_definition;

-- 자산 변경이 잦은 테이블 dead tuple 정리
VACUUM ANALYZE domain.public_api_connector;
VACUUM ANALYZE domain.sql_asset;
VACUUM ANALYZE wf.pipeline_release;
VACUUM ANALYZE ctl.api_key;
VACUUM ANALYZE ctl.user_role;
VACUUM ANALYZE audit.security_event;
```

### 2.2 정기 (운영팀 합류 후)

| 테이블 | 권장 cron |
|---|---|
| `run.pipeline_run_*` 파티션 | 매월 새 파티션 생성 시 ANALYZE |
| `mart.price_fact_*` 파티션 | 매월 1일 ANALYZE |
| `audit.*` 파티션 | 매주 일요일 ANALYZE |
| `domain.*`, `wf.*` (자산 잦은 변경) | autovacuum threshold 0.1 (기본 0.2 보다 낮춤) |

### 2.3 별도 PR 권장 (Phase 4 이관 직전)

- 파티션 자동 생성 cron (`pipeline_run`, `price_fact`, `audit.access_log`, `audit.inbound_event` — 현재월+다음 1~2개월만 rolling)
- `audit.pipeline_run_daily_summary` materialized view (Operations Dashboard 부하 분산)
- `service_mart.current_price` materialized view (최저가/최신가 조회 최적화)
- `mart.standard_code` IVFFLAT 인덱스 재정책 (1k+ rows 시점)

---

## 3. 변경 이력

| 일자 | 변경 |
|---|---|
| 2026-04-27 | Phase 8.4 — 본 문서 신규 |
| 2026-04-27 | Phase 8.3 — `iot_spike_mart` / `ctl.connector` / `ctl.api_key.expired_at` 제거 (migration 0052) |
