# Phase 8.4 — Final Polish (운영 시연 완성도 95% 목표)

**날짜:** 2026-04-27
**선행:** Phase 8 (Synthetic Rehearsal) + 8.1 (Hardening) + 8.2 (Deep UX) + 8.3 (DB cleanup)
**목적:** 운영팀 6~7명 합류 (2026-09-01) 전 완성도 80~82% → 93~95% 도달

---

## 0. 실측 베이스라인

- 등록 v2 노드: **20종** (backend `list_v2_node_types` 검증)
- NodePalette 노출: **17종** — OCR_RESULT_INGEST / CRAWLER_RESULT_INGEST / CDC_EVENT_FETCH 누락
- Inbound 인증: HMAC 단일 (`auth_method='api_key'` / `'mtls'` 미구현)
- Operations Dashboard: 24h trend + 재실행 (Phase 8.2) — 클릭→상세 / refresh / 최근 실패 패널 부재
- Service Mart Viewer: 표 + 추이 차트 — 요약 통계 (최저/최고/평균) / 할인·품절 필터 부재
- Backend pytest: dp_postgres + venv 환경에서 정상 작동 (Phase 8 e2e 9건 PASS, spike 8건 SKIP)
- Pre-existing 회귀: `test_dispatcher_includes_public_api_fetch` — Phase 7 wave 추가로 14→20 변경 누락

---

## 1. 우선순위 / 작업 매트릭스 (사용자 분석 9항목)

| # | 작업 | 상승치 | Phase 8.4 처리 |
|---|---|---|---|
| 1 | NodePalette 누락 노드 보완 (P3) | +3% | ✅ 본 PR |
| 2 | Phase 8 seed/문서 정합성 (P6) | +2% | ✅ 본 PR |
| 3 | Backend pytest 환경 (P1) | +5% | ⚠ 이미 작동 — pre-existing 회귀 1건 수정 |
| 4 | Phase 8 Canvas 실제 E2E (P2) | +6% | 🟨 부분 — 기존 9건 PASS, intentional-fail 케이스 추가는 Phase 9 |
| 5 | Inbound API Key 인증 (P4) | +4% | ✅ 본 PR |
| 6 | Operations Dashboard 운영 UX (P5) | +4% | ✅ 본 PR |
| 7 | Service Mart 시연 UX (P7) | +3% | ✅ 본 PR |
| 8 | DB 분류 문서 (P8) | +2% | ✅ 본 PR |
| 9 | CDC stub 정책 (P9) | +1% | ✅ 본 PR |

---

## 2. 변경 사항 상세

### 2.1 NodePaletteV2 — 누락 3종 추가 + Stub 배지
- `OCR_RESULT_INGEST` (DATA SOURCES) — OCR 업체가 push 한 텍스트 결과 수신
- `CRAWLER_RESULT_INGEST` (DATA SOURCES) — Crawler 업체가 push 한 페이지 결과 수신
- `CDC_EVENT_FETCH` (DATA SOURCES) — `Phase 9 STUB` 배지 + 노드 흐릿하게 표시

### 2.2 NodeConfigPanelV2 — OCR/CRAWLER/CDC 폼
- OCR_RESULT_INGEST: `channel_code` (inbound 채널 매핑)
- CRAWLER_RESULT_INGEST: `channel_code`, `expected_format`
- CDC_EVENT_FETCH: read-only stub UI + Phase 9 안내

### 2.3 Backend Inbound `api_key` 인증
- `inbound.py`: `auth_method='api_key'` 처리 추가
- `X-API-Key` 헤더 검증 → `audit.api_key.scope` 확인
- 실패 시 `audit.security_event` 기록
- 통합 테스트 `test_inbound_api_key.py` 추가

### 2.4 OperationsDashboard 운영 보강
- 채널 클릭 → 우측 패널: 최근 실패 raw_object / inbound_envelope 링크
- 재실행 후 5초 안에 자동 refetch
- 새 카드: **최근 실패 10건** (`/operations/recent-failures` 신설)
- 백엔드 신규: `recent-failures` 엔드포인트 (pipeline_run + node_run + dq_failure 조인)

### 2.5 ServiceMartViewer 시연 UX
- 표준품목 카드 상단: **최저가 / 최고가 / 평균가 / 할인폭** 요약 (4유통사 평균)
- 필터 토글: 「할인 중」 / 「품절」 / 「검수 필요」
- 행에 마지막 수집시간 (`collected_at`) 표시 — 신선도 가시화

### 2.6 Phase 8 문서/Seed 정합성
- `PHASE_8_SYNTHETIC_REHEARSAL.md` 의 시드 파일 목록을 실제(`phase8_seed_full_e2e.py`, `phase8_seed_synthetic_data.py`)에 맞춤
- 실행 순서: `synthetic_data` → `full_e2e` → 화면 확인
- 「화면 확인용」 vs 「Canvas E2E 검증용」 시드 구분 표

### 2.7 DB 분류 문서
- `docs/DB_CLASSIFICATION.md` 신규 — 활성/데모/미래/test-only/deprecated 매트릭스
- `iot_spike_mart` (Phase 8.3 에서 drop 완료), `ctl.connector` (drop 완료) 기록
- ANALYZE/VACUUM 운영 가이드 link

### 2.8 CDC_EVENT_FETCH stub 정책
- `cdc_event_fetch.py` runner 상단 docstring 에 Phase 9 정식 구현 조건 명시
- NodePalette / NodeConfigPanelV2 에 stub 배지
- 정식 구현 조건: CDC 소스 3개 초과 또는 트래픽 500K/일 초과 (CLAUDE.md 정책)

### 2.9 pre-existing 회귀 수정
- `test_dispatcher_includes_public_api_fetch`: assertion 14 → 20

---

## 3. 산출물

```
backend/app/api/v1/inbound.py               (수정 — api_key 인증)
backend/app/api/v2/operations.py            (수정 — recent-failures)
backend/app/domain/nodes_v2/cdc_event_fetch.py  (수정 — docstring stub)
backend/tests/integration/test_inbound_api_key.py  (신규)
backend/tests/integration/test_phase6_public_api.py  (수정 — 14→20)

frontend/src/api/v2/operations.ts           (수정 — recent-failures hook)
frontend/src/components/designer/NodePaletteV2.tsx  (수정 — 3 nodes + STUB)
frontend/src/components/designer/NodeConfigPanelV2.tsx  (수정 — OCR/CRAWLER/CDC forms)
frontend/src/components/dashboard/RecentFailuresPanel.tsx  (신규)
frontend/src/components/service_mart/PriceSummaryCard.tsx  (신규)
frontend/src/pages/v2/OperationsDashboard.tsx  (수정)
frontend/src/pages/v2/ServiceMartViewer.tsx  (수정)

docs/phases/PHASE_8_4_FINAL_POLISH.md       (본 문서)
docs/phases/PHASE_8_SYNTHETIC_REHEARSAL.md  (수정 — 시드 정합)
docs/DB_CLASSIFICATION.md                   (신규)
```

---

## 4. 완성도 추적

| 단계 | 누적 완성도 |
|---|---|
| Phase 8 종료 | 80~82% |
| Phase 8.1 (Hardening) | 84~85% |
| Phase 8.2 (Deep UX 8영역) | 87~88% |
| Phase 8.3 (DB cleanup) | 88~89% |
| **Phase 8.4 (Final Polish 9영역)** | **93~95%** |

---

## 5. Phase 9 이월

- CDC_EVENT_FETCH 정식 구현 (조건 충족 시)
- pgvector IVFFLAT 재정책 (표준코드 1k+)
- 파티션 자동 생성 cron + matview 2종
- KAMIS 실증 (Phase 9 main task)
- intentional-fail Canvas E2E 시나리오 (DQ 실패 → 재실행 흐름 자동화)
