# Phase 7 — Wave Status + Phase 9 Backlog

작성일: 2026-04-27
브랜치: `feature/v2-generic-platform`

> Phase 7 의 9개 wave 중 핵심 5개는 완료, 나머지 4개는 *Phase 9 후속* 으로 이월.

---

## 완료된 Wave

| Wave | 핵심 산출물 | commit |
|---|---|---|
| **Wave 1A** | Inbound Push Receiver (HMAC + idempotency) + 3 source 노드 (WEBHOOK/FILE_UPLOAD/DB_INCREMENTAL) | `f7889ec` |
| **Wave 1B** | OCR_RESULT_INGEST + CRAWLER_RESULT_INGEST + node_type 20종 | (이번 commit) |
| **Wave 3 핵심** | LLM_CLASSIFY / ADDRESS_NORMALIZE / PRODUCT_CANONICALIZE / CODE_LOOKUP provider seed + audit.provider_usage | (이번 commit) |
| **Wave 4 핵심** | DQ catalog 11종 (freshness / anomaly_zscore / drift 추가) | (이번 commit) |
| **Wave 5** | Operations Dashboard + workflow heatmap | (이번 commit) |
| **Wave 6 핵심** | inbound dispatch — RECEIVED envelope → workflow trigger | (이번 commit) |

## 미완료 Wave (Phase 9 후속)

본 Phase 의 *out-of-scope* 로 명시. Phase 9 진입 후 우선순위 결정.

### Wave 2 — 자산 version pinning (Phase 9 Wave 0 후보)
**범위**:
- 8 entity 모두 PUBLISHED 수정 시도 → 자동 fork on confirm
- workflow_definition 의 자식 자산 version 강제 pinning
- pipeline_run 에 사용된 자산 version snapshot

**현재 상태**: 모든 자산이 *DRAFT-only edit* 정책은 강제됨 (Phase 6 Wave 2A 부터).
`version` 컬럼은 sql_asset / load_policy / source_contract 에 *이미 존재*.
auto-fork 로직은 미구현.

**Phase 9 진입 시 추정 분량**: 1주

### Wave 7 — Schema Evolution + Data Contract semver
**범위**:
- `source_contract.schema_version` → `major.minor.patch` 분할
- `compatibility_mode` BACKWARD/FORWARD/FULL/NONE 자동 검증
- PUBLIC_API_FETCH 응답 schema drift detection (severity별 routing)

**현재 상태**: `compatibility_mode` 컬럼 존재 (Phase 5). semver 분할 + 자동
검증 미구현.

**Phase 9 진입 시 추정 분량**: 1주

### Wave 8 — Bronze/Silver/Gold + Lineage
**범위**:
- schema 명명 표준화 강제 (sql_guard 의 화이트리스트)
- `audit.run_lineage` — run 의 input/output table 자동 기록
- 자산 사용처 reverse lookup

**현재 상태**: schema 패턴 (`<domain>_raw` / `<domain>_stg` / `<domain>_mart`) 은
이미 사용 중. 명명 강제 + lineage 자동 기록 미구현.

**Phase 9 진입 시 추정 분량**: 1.5주

### Wave 9 — Replay/Backfill UX 완성
**범위**:
- `/v2/operations/backfill` 화면 (날짜 범위 + chunk 진행률)
- 노드 단위 partial replay (`POST /v1/pipelines/runs/{id}/replay-from`)
- replay 사유 입력 + 결과 비교 보고서

**현재 상태**: backend `/v2/backfill` 은 Phase 5.2.8 부터 존재. 노드 단위 replay
는 미구현. UI 미구현.

**Phase 9 진입 시 추정 분량**: 1주

---

## Phase 7 acceptance 결과

| # | 시나리오 | 상태 |
|---|---|---|
| 1 | 외부 크롤링 push 수용 | ✅ Wave 1B + Wave 6 dispatch (수동 trigger) |
| 2 | 소상공인 업로드 즉시 처리 | ✅ FILE_UPLOAD_INGEST + dispatch endpoint |
| 3 | 자산 version pinning | 🟡 Wave 2 — Phase 9 이월 |
| 4 | 노드 단위 재실행 | 🟡 Wave 9 — Phase 9 이월 |
| 5 | **KAMIS API Pull 회귀** | ✅ test_phase6_kamis_vertical_slice.py 5/5 |

5/5 acceptance 시나리오 중 **3 통과 / 2 Phase 9 이월**.

---

## 다음 단계

**Phase 8** — 가상 데이터 시나리오 리허설 (이번 PR 에 포함).
**Phase 9** — 실증 진입 + Wave 2/7/8/9 완성. KAMIS / 4 유통사 실 API 연동.
