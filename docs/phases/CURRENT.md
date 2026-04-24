# 현재 진행 중인 Phase & 전체 타임라인

## 📅 주요 마감선
- **2026-09-01** — 운영팀 6~7명 합류 예정. 이 시점까지 **Phase 1~3 완료** 목표.
- **Phase 4 (NKS 이관 + Public API + Crowd 정식 + CDC)** 는 운영팀과 함께 수행 (9월 이후).

## ✅ 지금 진행 중
**Phase 1 — Core Foundation**
- 시작: 2026-04-25
- 목표 완료: 2026-05-30 (**5주, 원래 6~8주에서 압축**)
- 참조: [PHASE_1_CORE.md](./PHASE_1_CORE.md)

---

## 🗓 전체 일정 (2026-04-25 기준, 18주)

| Phase | 기간 | 시작 | 완료 목표 | 누적 주차 |
|---|---|---|---|---|
| Phase 1 — Core | 5주 | 2026-04-25 | **2026-05-30** | W5 |
| Phase 2 — Runtime (Airflow 포함) | 6주 | 2026-06-01 | **2026-07-11** | W11 |
| Phase 3 — Visual ETL (핵심만) | 7주 | 2026-07-13 | **2026-08-29** | W18 |
| **운영팀 합류** | — | **2026-09-01** | — | — |
| Phase 4 — Enterprise + NKS | 10~12주+ | 2026-09-02 | 2026-11~ | — |

---

## 📦 Phase별 완료 기준 (9/1 전에 갖춰야 할 것)

### Phase 1 (5주) DoD
- FastAPI 수집 API 3종 동작 (`/v1/ingest/api`, `/file`, `/receipt`)
- PG 스키마 (ctl, raw, run, audit, stg 뼈대, mart 뼈대)
- Object Storage 연동 (MinIO 로컬)
- 기본 Web Portal (로그인 + 소스 관리 + 원천 조회 + 수집 잡)
- Prometheus `/metrics` 노출
- CI (lint+test+build)
- **NKS Ready 8계명** 이미지 준수

### Phase 2 (6주) DoD
- Dramatiq worker 3종 (OCR / transform / crawler)
- **Apache Airflow 2.9+ 정식 도입** (LocalExecutor)
- 시스템 DAG 5종 (`daily_agg`, `monthly_partition`, `hourly_outbox`, `daily_archive`, `ingest_db_incremental`)
- CLOVA OCR 연동 + confidence 게이트 (≥0.85 자동, 미만 crowd_task)
- 상품 표준화 (pg_trgm + pgvector + HyperCLOVA 임베딩)
- `stg.price_observation` → `mart.price_fact` 실시간 반영 < 60초
- 관제 고도화 (Loki + Sentry)

### Phase 3 (7주) 압축 DoD — **핵심만**
- Pipeline Runtime (자체 DAG 실행기)
- Visual Designer 기본 캔버스 (React Flow, 저장/검증/실행)
- 노드 타입 6종: `SOURCE_API`, `SQL_TRANSFORM`, `DQ_CHECK`, `DEDUP`, `LOAD_MASTER`, `NOTIFY`
- SQL Studio 기본 (sqlglot 검증 + sandbox + 승인 플로우)
- 노드 상태 SSE 실시간 반영
- Pipeline 예약 (Airflow DAG 자동 생성)

**Phase 3에서 운영팀 합류 후로 미루는 기능:**
- `SOURCE_DB`, `OCR`, `CRAWLER`, `HUMAN_REVIEW` 노드
- SQL lineage 자동 추출 (OpenLineage)
- Pipeline 버전 diff 뷰
- Backfill UI
- 템플릿 라이브러리 고도화

---

## 🚦 매주 체크

매주 월요일, 다음 질문 3개로 자체 점검:
1. 지난주 완료한 체크박스는? (Phase 문서의 해당 항목에 ✅)
2. 이번주 타겟 체크박스는? (3~5개 선정)
3. 일정 대비 지연? (지연이면 원인 + 대응: 스코프 축소 or 기간 연장)

지연이 2주 이상 누적되면:
- Phase 3 스코프를 추가 삭제 (Visual ETL 미구현 → Phase 4로)
- 또는 Phase 2의 크롤링 기능을 Phase 4로 이동

---

## 🧭 완료 시 업데이트 절차

Phase N 완료 시 이 파일을 다음처럼 갱신:
1. `## ✅ 지금 진행 중` 값을 다음 Phase로 교체
2. 해당 Phase DoD 체크박스 모두 ✅
3. ADR 작성 (주요 결정 사항)
4. 루트 README에 진척 badge 업데이트 (선택)

---

## 📌 운영팀 합류 전 체크 (2026-08-29까지)

- [ ] Phase 1~3 DoD 모두 충족
- [ ] `docs/ops/NKS_DEPLOYMENT.md` 마이그레이션 가이드 점검
- [ ] 컨테이너 이미지가 NKS Ready 8계명 준수
- [ ] Terraform 베이스라인 skeleton 준비 (실제 apply는 운영팀과)
- [ ] 운영팀 온보딩 자료 5종 초안:
  1. 시스템 아키텍처 투어 (30분 슬라이드)
  2. 도메인 모델 소개 (농축산물 가격)
  3. Phase 1~3에서 만든 기능 데모 (녹화)
  4. 알려진 기술부채 리스트
  5. Phase 4 우선순위 제안서

이 5개가 있으면 9/1 합류 첫 주에 온보딩이 끝남.
