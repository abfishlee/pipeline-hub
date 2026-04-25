# 현재 진행 중인 Phase & 전체 타임라인

## 📅 주요 마감선
- **2026-09-01** — 운영팀 6~7명 합류 예정. 이 시점까지 **Phase 1~3 완료** 목표.
- **Phase 4 (NKS 이관 + Public API + Crowd 정식 + CDC)** 는 운영팀과 함께 수행 (9월 이후).

## ✅ 지금 진행 중
**Phase 3 — Visual ETL Designer + SQL Studio (핵심만)**
- 시작: 2026-07-13 (예정 — Phase 2 가 같은 날(2026-04-25) 2.2.1 → 2.2.10 + 2.6 마무리까지 종료)
- 목표 완료: 2026-08-29 (**7주**)
- 참조: [PHASE_3_VISUAL_ETL.md](./PHASE_3_VISUAL_ETL.md)

> Phase 1·2 모두 같은 날(2026-04-25) 끝나, 일정 13주(5+6+2주 여유) 가 Phase 3 운영 안정화/문서화에 흡수됨. 2026-09-01 운영팀 합류 데드라인까지 4개월 이상 마진.

### Phase 3 진입 조건 (모두 충족 — 2026-04-25)
- ✅ Phase 2 DoD 7종 모두 충족 (Worker 5종 / OCR + Upstage / 표준화 + pgvector / price_fact 4단계 게이트 / DB-to-DB + Crawler / Loki + Sentry / 운영자 화면)
- ✅ outbox publisher + Streams consumer + idempotent_consume 흐름 검증 — Phase 3 Pipeline Runtime 노드들도 이 위에 얹는다
- ✅ `run.event_outbox` 토픽 6종(raw_object/ocr_result/crowd_task/staging/price_fact/crawler_page) — Phase 3 의 새 토픽(`pipeline.run.*`, `pipeline.node.state.changed`)도 같은 prefix 로 추가
- ✅ ADR 0001~0006 기록 (드라이버 듀얼 / Object Storage / Outbox+content_hash / Outbox 트리거 전략 / 표준화 3단계 / Crowd placeholder)

### Phase 3 대상 모듈 (신규 생성)
| 위치 | 책임 |
|---|---|
| `migrations/versions/0015_workflow_definition.py` | `wf.workflow_definition`, `wf.node_definition`, `wf.edge_definition` (Visual ETL DAG 메타) |
| `migrations/versions/0016_pipeline_run.py` | `run.pipeline_run`, `run.node_run` (실행 이력 — partitioned by run_date) |
| `migrations/versions/0017_sql_studio.py` | `wf.sql_query`, `wf.sql_query_version`, `wf.sql_run` (SQL Studio 승인 플로우) |
| `backend/app/models/wf.py` | workflow / pipeline / node ORM |
| `backend/app/domain/pipeline_runtime.py` | 자체 DAG 실행기 (위상 정렬 + 노드별 actor 디스패치 + node_run 상태 갱신) |
| `backend/app/domain/nodes/` | 노드 6종 구현 — `source_api.py`, `sql_transform.py`, `dq_check.py`, `dedup.py`, `load_master.py`, `notify.py` |
| `backend/app/api/v1/pipelines.py` | `/v1/pipelines` CRUD + 실행/취소/상태 조회 + SSE 노드 상태 stream |
| `backend/app/api/v1/sql_studio.py` | `/v1/sql-studio/queries` (sqlglot 검증 + sandbox 실행 + 승인 후 mart 반영) |
| `backend/app/integrations/sqlglot_validator.py` | SQL AST 분석 (참조 테이블 / 위험 패턴 / 함수 화이트리스트) |
| `frontend/src/pages/PipelineDesigner.tsx` | React Flow 캔버스 (노드 조립 → 검증 → 저장) |
| `frontend/src/pages/SqlStudio.tsx` | 에디터 + 검증 결과 + 승인 플로우 |
| `frontend/src/pages/PipelineRunDetail.tsx` | 노드 상태 SSE 실시간 갱신 (Phase 1.2.9 와 동일 SSE 채널) |
| `infra/airflow/dags/pipeline_runtime_bridge.py` | Pipeline 의 SCHEDULED 트리거를 Airflow DAG 으로 동기화 (Phase 2.2.3 chassis 위) |

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

### Phase 1 (5주) DoD — ✅ 2026-04-25 완료
- [x] FastAPI 수집 API 3종 동작 (`/v1/ingest/api`, `/file`, `/receipt`) — Phase 1.2.7
- [x] PG 스키마 (ctl, raw, run, audit, stg 뼈대, mart 뼈대) — Phase 1.2.3
- [x] Object Storage 연동 (MinIO 로컬, NCP 호환) — Phase 1.2.6
- [x] 기본 Web Portal (로그인 + 소스 관리 + 원천 조회 + 수집 잡) — Phase 1.2.9
- [x] Prometheus `/metrics` + Grafana 대시보드 — Phase 1.2.10
- [x] audit.access_log 미들웨어 — Phase 1.2.10
- [x] CI (lint+test+typecheck) — Phase 1.2.1
- [x] **NKS Ready 8계명** 이미지 준수 — Phase 1.2.2 Dockerfile

### Phase 2 (6주) DoD — ✅ 2026-04-25 완료
- [x] Dramatiq worker 5종 (outbox / ocr / transform / price_fact / db_incremental + crawler) — Phase 2.2.1, 2.2.4~2.2.8
- [x] **Apache Airflow 2.10 LocalExecutor** chassis (init / webserver / scheduler) — Phase 2.2.3 (시스템 DAG 5종은 후속)
- [x] CLOVA OCR + Upstage 폴백 + confidence 게이트 (≥0.85 자동, 미만 crowd_task placeholder) — Phase 2.2.4
- [x] 상품 표준화 3단계 (pg_trgm 0.7 → HyperCLOVA 임베딩 0.85 → crowd) + pgvector(1536) IVFFLAT — Phase 2.2.5
- [x] `stg.price_observation` → `mart.price_fact` 자동 반영 + confidence 4단계 게이트(insert/sampled/held/skipped) — Phase 2.2.6
- [x] DB-to-DB 증분 수집 (PostgreSQL/MySQL + watermark JSONB) — Phase 2.2.7
- [x] httpx 정적 HTML 크롤러 + robots.txt + content_hash dedup — Phase 2.2.8
- [x] 관제 고도화 — Loki + Promtail (structlog JSON 라벨링) + Sentry (PII 스크럽) + Runtime 대시보드 + 백로그 Gauge — Phase 2.2.9
- [x] 운영자 화면 — Crowd 검수 큐 + Dead Letter replay + Runtime 모니터 — Phase 2.2.10
- [x] event_outbox publisher 가 Redis Streams 로 이송 + Consumer Group fan-out + idempotent consume — Phase 2.2.1, 2.2.2

운영팀 9월 합류 시 즉시 시연 가능: `docs/dev/PHASE_2_E2E.md`.

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
