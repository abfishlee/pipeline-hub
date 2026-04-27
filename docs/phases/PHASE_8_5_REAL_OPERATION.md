# Phase 8.5 — Real Operation 보강 (완성도 95% → 98%)

**날짜:** 2026-04-27
**선행:** Phase 8 ~ 8.4
**목적:** "예쁜 화면" 단계에서 "**실제로 흐르고 끊김을 알 수 있는 운영 시스템**" 으로 전환

---

## 0. 진단 (Phase 8.4 종료 시점)

| 영역 | 현 상태 | 부족 |
|---|---|---|
| Canvas 자산 조립 | ✅ 화면 + 폼 + dry-run | ❌ 실제 worker 실행 e2e 검증 |
| 데이터 노출 | ✅ Service Mart Viewer / Operations Dashboard | ❌ 수집-적재 lag 측정 |
| Inbound 처리 | ✅ HMAC + API Key 인증 | ⚠ Auto dispatcher 5초 polling 작동 중 (검증 누락) |
| 모니터링 | ✅ 24h trend / failure category / recent failures | ❌ 채널 freshness / system alert |
| Provider | ⚠ audit.provider_usage 테이블만 존재 | ❌ 호출수/비용 가시성 |
| 장애 대응 | ✅ recent-failures 패널 + run 링크 | ❌ Run Detail 깊이 부족 |

**한 줄 요약:** *"조립 가능한 도구"는 갖췄지만 "흐름이 흐른다는 증명" 과 "흐름이 막혔을 때 알 수 있는 신호" 가 부족.*

---

## 1. 7 영역 작업

### ① Canvas 실제 실행 통합 테스트
- 시나리오: Phase 8 시드된 4 유통사 workflow 1개를 실제로 실행 → service_mart row 증가 확인
- 신규: `tests/integration/test_phase8_5_real_workflow_run.py`
- 핵심 단계:
  1. emart workflow 의 source_data → map_fields → load_target 노드 chain 을 worker 호출로 직접 실행
  2. `service_mart.product_price` row count before/after 비교
  3. node_run COMPLETED 상태 확인
  4. pipeline_run.status = COMPLETED 확인
- 측정: row 증가 ≥ 1, run.status='COMPLETED'

### ② Real-time SLA Lag 측정
- 백엔드: `/v2/operations/sla-lag` 신규
  - `inbound_event.received_at` → 최종 mart 적재 (`run.pipeline_run.finished_at`) 까지 24h p50/p95/p99
- 프런트: Operations Dashboard 상단 "SLA Lag" 카드 — p95 색상 (≤60s 녹색, ≤180s 황색, >180s 적색)
- CLAUDE.md SLA: "수집 후 1분 이내" 추적 가능

### ③ Auto Dispatcher 검증 + 헬스 노출
- 코드 검증: `app/workers/inbound_dispatcher.py` 가 main.py lifespan 에서 5초 polling 으로 이미 가동 중 — *기능 자체는 완료*
- 보강:
  - `/v2/operations/dispatcher-health` 엔드포인트: 마지막 dispatch 시각 / 누적 처리수
  - Operations Dashboard 에 "Auto Dispatcher" 카드 — RUNNING / STALE 상태 표시
  - dispatcher iteration 마다 `audit.dispatcher_heartbeat` 같은 lightweight log 1건 (또는 메모리 ring buffer)

### ④ Data Freshness 모니터링
- 백엔드: `/v2/operations/freshness` 신규
  - `domain.inbound_channel × MAX(audit.inbound_event.received_at)` 조회
  - threshold (default 60min) 초과 시 STALE 마킹
- 프런트: `StaleChannelsPanel` 신규 — Operations Dashboard 에 마운트
- 구현 우선 4 가상 유통사 + KAMIS 채널 (있으면) 모두 포함

### ⑤ System Alert 채널
- 신규: `app/alerting/dispatcher.py` — Slack webhook + 로그 fallback
- 트리거 조건 (rule-based, code 내 정의):
  - failure_rate_24h > 30% (workflow 단위)
  - sla_lag_p95 > 180s
  - channel stale > 60min
  - provider cost (있으면)
- 신규: `audit.alert_log` 테이블 (migration 0053) — alert 발사 이력
- env: `ALERT_SLACK_WEBHOOK_URL` (없으면 로그만)
- 백엔드 cron: 5분마다 평가 (lifespan task)

### ⑥ PipelineRunDetail 보강
- 현재 251줄 — 기본 구조는 있음
- 추가:
  - 노드별 실행 시간선 (gantt-style mini)
  - 실패 노드의 `error_message` + `payload_preview` (raw_object_id 있으면 raw 첫 200B)
  - "Retry from this node" 버튼 (단, 실제 재실행은 trigger-rerun 호출)
  - downstream 영향 (cascade 실패 노드 표시)

### ⑦ Provider Cost 가시성
- 백엔드: `/v2/operations/provider-usage` 신규
  - `audit.provider_usage` 24h 집계: 호출수 / 추정 비용 / provider별
  - 추정 비용은 `domain.provider_definition.cost_per_call_krw` 같은 컬럼 또는 hardcoded 단가
- 프런트: Operations Dashboard 에 "Provider Cost (24h)" 카드
- KAMIS / OCR / Crawler 등 사용 시 비용 가시성

---

## 2. 산출물 매트릭스

| 카테고리 | 파일 | 종류 |
|---|---|---|
| 백엔드 신규 | `app/api/v2/operations.py` | 5 신규 endpoint (sla-lag / freshness / dispatcher-health / provider-usage) |
| 백엔드 신규 | `app/alerting/dispatcher.py` | Slack webhook + rule evaluator |
| 백엔드 신규 | `app/alerting/rules.py` | rule definitions |
| 백엔드 신규 | `app/workers/alert_loop.py` | 5분 cron lifespan task |
| 백엔드 신규 | `migrations/versions/0053_alert_log_provider_cost.py` | audit.alert_log + provider cost 컬럼 |
| 백엔드 신규 | `tests/integration/test_phase8_5_real_workflow_run.py` | ① 실제 실행 e2e |
| 백엔드 신규 | `tests/integration/test_phase8_5_sla_freshness.py` | ②④ 검증 |
| 프런트 신규 | `components/dashboard/SlaLagCard.tsx` | ② |
| 프런트 신규 | `components/dashboard/StaleChannelsPanel.tsx` | ④ |
| 프런트 신규 | `components/dashboard/DispatcherHealthCard.tsx` | ③ |
| 프런트 신규 | `components/dashboard/ProviderCostCard.tsx` | ⑦ |
| 프런트 수정 | `pages/PipelineRunDetail.tsx` | ⑥ |
| 프런트 수정 | `pages/v2/OperationsDashboard.tsx` | 카드/패널 마운트 |

---

## 3. 완성도 추적

| 단계 | 누적 |
|---|---|
| Phase 8.4 종료 | 93~95% |
| Phase 8.5 ①+②+③+④ (필수) | 96~98% |
| Phase 8.5 ⑤+⑥+⑦ (선택) | 98~99% |
