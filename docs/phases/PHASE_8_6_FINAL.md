# Phase 8.6 — 공용 데이터 수집 플랫폼 사용성 정착

**날짜:** 2026-04-27
**선행:** Phase 8.5 (Real Operation, 96~98%)
**목적:** Phase 9 실증 진입 전, **공용 (도메인 무관) 플랫폼** 정체성 회복 + 사용자 친화도 + Mock API 자체 검증 도구 + 풀체인 작동 증명

---

## 0. 시스템 정체성 (재정의)

> **이 시스템은 "공용 데이터 수집 파이프라인 플랫폼"이다.**
> 농축산물 / 부동산 / IT 통계 / 정부 공공데이터 등 **어떤 도메인이든** Canvas 로
> 직관적으로 설계 → Job 으로 등록 → 주기 실행 → 표준 마트 적재까지 코드 0줄로
> 가능하게 만드는 글로벌 스탠다드 솔루션.
>
> 현재 "농축산물 가격" 은 **첫 실증 프로젝트일 뿐**이며, 시스템 자체에는
> 농축산물 / KAMIS / 가격 같은 도메인 특정 표현이 절대 박혀있으면 안 됨.

---

## 1. SQL Studio 정책 — 재정의

### 이전 인식 (잘못됨)
SQL Studio = ad-hoc SQL 자유 작성 + 일회성 실행 도구.

### 정정된 정책 (Phase 8.6)
> **모든 등록 SQL 은 *반드시 Canvas 에서 활용되어야* 데이터 추적 가능.**
> SQL Studio 의 ad-hoc 실행도 audit log 에 기록되며, *영구 자산이 되려면 Transform
> Designer 의 sql_asset 으로 승급* 해야 한다.

### 적용 변경
1. SQL Studio = "**SQL 자산 작성 + 탐색 워크벤치**" 로 재정의
2. SELECT 만 ad-hoc 허용 (현재도 sql_guard 로 DML/DDL 차단됨)
3. SQL 저장 시 **2 모드 강제 선택**:
   - **(A) sql_asset 으로 승급** — Transform Designer 로 이관, DRAFT/REVIEW/APPROVED/PUBLISHED 라이프사이클 → Canvas 의 SQL_ASSET_TRANSFORM 노드에서 사용
   - **(B) 임시 query (예외)** — 30일 후 자동 만료, *sql_asset 으로 승급 권장* 배너 노출
4. 모든 ad-hoc SELECT 실행은 `audit.sql_execution_log` 기록 (이미 존재)

---

## 2. 14 sub-step 작업 매트릭스

| # | sub-step | 산출물 | 그룹 |
|---|---|---|---|
| 8.6.1 | 도메인 특정 표현 제거 | CLAUDE.md, docs/, frontend 16 파일 | A |
| 8.6.5 | Mock API 페이지 | backend `/v1/mock-api/*` + frontend 관리 화면 | B |
| 8.6.2 | 응답 포맷 7종 + parser | json/xml/csv/tsv/text/excel/binary | B |
| 8.6.3 | Cron Picker (6 모드) | 즉시/N분/N시간/매일/요일+시각/고급 | C |
| 8.6.4 | Airflow 기동 + 실증 | scheduled_pipelines DAG 검증 + ops 문서 | C |
| 8.6.6 | EmptyState + HelpDrawer + QuickStart | 도메인 무관 표현 | D |
| 8.6.7 | Canvas 권장 패턴 박스 | "SOURCE → MAP → STD → MART" 가이드 | D |
| 8.6.12 | 평탄화 stg 시각화 | wf/stg/<domain>_mart 3 단계 도식 | D |
| 8.6.9 | Field Mapping 마법사 | 5 단계 마법사 + sample JSON 자동 평탄화 | E |
| 8.6.10 | Quality 카탈로그 통합 | target_table dropdown + column 자동완성 | E |
| 8.6.11 | SQL Studio 정책 재정의 | 테이블 트리 + sql_asset 승급 버튼 | E |
| 8.6.13 | 9 노드 풀체인 e2e | Mock API → MAP → FUNCTION → STANDARDIZE → SQL_ASSET → DEDUP → DQ → LOAD 통합 테스트 | F |
| **8.6.14** | **데이터 wipe + 시나리오 검증** | **truncate 후 Mock API 로 처음부터 끝까지 자동 시나리오 + 시나리오 markdown** | **F** |

### 그룹별 commit 전략

| 그룹 | commit 주제 |
|---|---|
| **A** | `feat(phase8.6): 공용 플랫폼 정체성 회복 — 도메인 표현 제거` |
| **B** | `feat(phase8.6): Mock API 자체 검증 도구 + 응답 포맷 7종 파서` |
| **C** | `feat(phase8.6): Cron Picker + Airflow 기동 검증` |
| **D** | `feat(phase8.6): UX 진입경험 + Canvas 권장 패턴 도식` |
| **E** | `feat(phase8.6): 디자이너 카탈로그 통합 + SQL Studio 정책 정정` |
| **F** | `feat(phase8.6): 9노드 풀체인 e2e + 시나리오 자동 검증` |

---

## 3. 시나리오 — Phase 8.6 종료 시점 자동 검증

`docs/manual/PHASE_8_6_VALIDATION_SCENARIO.md` 에 7 단계 시나리오 작성. 각 단계는
운영자가 *웹 화면에서* 직접 검증 가능.

| 단계 | 화면 | 행동 | 기대 결과 |
|---|---|---|---|
| 1 | Mock API 관리 페이지 | "sample_iot_sensors" mock 등록 (JSON 응답) | mock endpoint URL 노출 |
| 2 | Source / API Connector | mock URL 로 connector 등록 + dry-run | dry-run 통과 |
| 3 | Mart Workbench | `iot_mart.sensor_reading` 마트 + load_policy 정의 | PUBLISHED |
| 4 | Field Mapping Designer | mock JSON path → mart 컬럼 매핑 (마법사) | PUBLISHED |
| 5 | Quality Workbench | `null_pct_max` + `range` 룰 정의 (카탈로그 dropdown) | PUBLISHED |
| 6 | ETL Canvas | SOURCE → MAP → DQ → LOAD 4 노드 chain + Cron Picker 1분마다 + PUBLISHED | PUBLISHED |
| 7 | Pipeline Runs / Operations Dashboard | 1분 안에 자동 trigger → SUCCESS run 1건 + iot_mart 에 row 적재 | row count > 0 |

---

## 4. 완성도 목표

| 단계 | 완성도 | 의미 |
|---|---|---|
| Phase 8.5 종료 | 96~98% | Real Operation 인프라 |
| **Phase 8.6 종료** | **98~99%** | **공용 플랫폼 정체성 + 사용성 + 자체 검증** |
| Phase 9 진입 | 99% | 실증 도메인 사용자 결정 → 첫 데이터 흐름 |
