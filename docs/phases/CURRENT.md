# 현재 진행 중인 Phase & 전체 타임라인

## 📅 주요 마감선
- **2026-09-01** — 운영팀 6~7명 합류 예정. 이 시점까지 **Phase 1~3 완료** 목표.
- **Phase 4 (NKS 이관 + Public API + Crowd 정식 + CDC)** 는 운영팀과 함께 수행 (9월 이후).

## ✅ 지금 진행 중
**Phase 5 — v2 Generic Platform** ✅ 완료 (2026-04-27)
- 12 STEP 모두 commit + push (Spike → onboarding).
- ADR-0017 / 0018 / 0019 / 0020 작성.
- 누적 통합 테스트 100+ passing.
- 운영자 onboarding 5종 + 5종 보조 문서 갱신.

**다음**: Phase 6 — Field Validation (운영팀 6~7명 합류 후).
- 시작 예정: 2026-09-02
- 참조: [PHASE_6_FIELD_VALIDATION.md](./PHASE_6_FIELD_VALIDATION.md)
- 첫 작업: 사업측 요청 도메인 1개 + 실 외부 API 연동 + staging shadow 1주.

### 직전 Phase: Phase 5 — v2 Generic Platform ✅ 완료 (2026-04-27)

| STEP | 완료일 | 핵심 산출물 | commit |
|---|---|---|---|
| 1 (Spike Hybrid ORM) | 2026-04-26 | ADR-0017 + experimental/registry_spike.py | 94ef1f1 |
| 2 (가드레일 7종) | 2026-04-26 | sql_guard / state_machine / dry_run / publish_checklist | f4f360a |
| 3 (domain.* schema) | 2026-04-26 | 9 ORM + v2 API 스켈레톤 + agri.yaml | f2ccb0b |
| 4 (Provider Registry) | 2026-04-26 | 7 provider seed + 자체 circuit breaker + shadow runner | 297d695 |
| 5 (nodes_v2 generic) | 2026-04-26 | 6 generic nodes + FUNCTION allowlist 26 + sql_asset | 1c53b73 |
| 7 (ETL UX backend) | 2026-04-26 | user×domain 권한 + Mart Designer + DQ Builder + Mini Checklist | 736ffe6 |
| 8 (v1→v2 shadow) | 2026-04-26 | shadow_diff + T0 sha256 partition + cutover_flag | 9a1eef1 |
| 9 (POS 도메인 ★) | 2026-04-26 | pos.yaml + pos_mart + payment_method + ADR-0019 | 6a2b248 |
| 10 (multi-domain public) | 2026-04-26 | api_key JSONB scope + /public/v2/{domain}/* | df76286 |
| 11 (perf SLO + Coach) | 2026-04-27 | 10 SLO + EXPLAIN coach + 1년치 backfill + ADR-0020 | b560c36 |
| 12 (onboarding + 회고) | 2026-04-27 | 5종+5종 docs + ADR-0018 + Phase 6 backlog | (이 commit) |

### Phase 5 ADR
- **ADR-0017** Hybrid ORM 전략 (v1=ORM, v2=Core+reflected) — `docs/adr/0017-resource-registry-orm-strategy.md`
- **ADR-0018** v2 generic 회고 + 추상화 KPI 결과 ★ — `docs/adr/0018-phase5-v2-generic-retrospective.md`
- **ADR-0019** POS 도메인 추가 KPI 검증 (1일 미만 / 코드 수정 0) — `docs/adr/0019-phase5-abstraction-validation-pos.md`
- **ADR-0020** Kafka 도입 트리거 (현재 미도입) — `docs/adr/0020-kafka-introduction-triggers.md`

### Phase 5 핵심 결과 (ADR-0018 요약)
- ✅ 새 도메인 추가가 *yaml + migration + seed* 만으로 가능 (POS 검증).
- ✅ Strangler Pattern — v1 동결 / v2 옆에 추가.
- ⚠ Phase 6 backlog 8 종 ETL UX (Error Sample Viewer 1순위) + shadow 실측.

### Phase 4 진입 (NKS / Public API / CDC) — Phase 6 와 병행 예정
- 시작 예정: 2026-09-02 (운영팀 6~7명 합류 다음 날)
- 참조: [PHASE_4_ENTERPRISE.md](./PHASE_4_ENTERPRISE.md)
- 진입 게이트는 본 문서 "📌 Phase 4 진입 체크리스트" 참조.

### 직전 Phase: Phase 3 — Visual ETL + SQL Studio ✅ 완료 (2026-04-26)

- 1주차에 가속 완료 (Phase 1, 2 가 같은 날 끝나 누적 13주 여유 흡수). 2026-09-01 운영팀
  합류까지 4개월+ 마진.
- 누적 코드 — migration 20개 / backend 110 .py / frontend 43 .ts(x).
- 모든 sub-phase 완료:

| Sub-phase | 완료일 | 핵심 산출물 |
|---|---|---|
| 3.2.1 Pipeline Runtime | 2026-04-25 | 자체 DAG 실행기 + workflow 메타 + node_run 상태머신 |
| 3.2.2 노드 6종 | 2026-04-25 | NOOP/SOURCE_API/SQL_TRANSFORM/DEDUP/DQ_CHECK/LOAD_MASTER/NOTIFY |
| 3.2.3 SSE 실시간 | 2026-04-25 | Pub/Sub → SSE 30s heartbeat + fetch-event-source |
| 3.2.4 Visual Designer 프론트 | 2026-04-25 | React Flow 12 캔버스 + SQL Studio dry-run |
| 3.2.5 SQL Studio sandbox + 승인 | 2026-04-25 | read-only TX + EXPLAIN + DRAFT/PENDING/APPROVED 상태머신 |
| 3.2.6 파이프라인 버전/배포 | 2026-04-26 | wf.pipeline_release + 새 PUBLISHED row + diff |
| 3.2.7 배치 스케줄 관리 | 2026-04-26 | cron 메타 + Backfill + runs 검색 + 재실행 |
| 3.2.8 문서/템플릿 | 2026-04-26 | 3 YAML pipelines + 12 SQL 템플릿 + 2 seed 스크립트 |
| 3 wrap-up | 2026-04-26 | perf 측정 스크립트 + ADR 0007/0008/0009 + 진입 게이트 정리 |

### Phase 3 ADR
- **ADR-0007** Visual ETL Designer 캔버스 = React Flow 12 — `docs/adr/0007-visual-etl-designer-react-flow.md`
- **ADR-0008** SQL Studio sandbox = read-only TX (vs 임시 스키마) — `docs/adr/0008-sql-studio-sandbox-policy.md`
- **ADR-0009** Pipeline 버전 관리 = DRAFT 유지 + 새 PUBLISHED row — `docs/adr/0009-pipeline-versioning-draft-published.md`

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

### Phase 3 (7주) 압축 DoD — ✅ 2026-04-26 완료
- [x] Pipeline Runtime (자체 DAG 실행기) — 3.2.1
- [x] Visual Designer 캔버스 (React Flow 12) — 3.2.4
- [x] 노드 7종: NOOP/SOURCE_API/SQL_TRANSFORM/DQ_CHECK/DEDUP/LOAD_MASTER/NOTIFY — 3.2.2
- [x] SQL Studio (sqlglot 검증 + read-only sandbox + 승인 플로우) — 3.2.4 + 3.2.5
- [x] 노드 상태 SSE 실시간 반영 — 3.2.3
- [x] Pipeline 버전/배포 (DRAFT 유지 + 새 PUBLISHED + release 이력 + diff) — 3.2.6
- [x] 스케줄 메타 (cron) + Backfill + runs 검색 + 수동 재실행 — 3.2.7
- [x] 샘플 파이프라인 YAML 3종 + SQL 템플릿 12종 + seed 스크립트 — 3.2.8

**원래 Phase 4 로 미뤘다가 Phase 3 안에 끌어온 기능:**
- ✅ Pipeline 버전 diff 뷰 (3.2.6)
- ✅ Backfill UI (3.2.7)
- ✅ 템플릿 라이브러리 (3.2.8)

**여전히 Phase 4 로 미뤄진 기능:**
- `SOURCE_DB`, `OCR`, `CRAWLER`, `HUMAN_REVIEW` 노드
- SQL lineage 자동 추출 (OpenLineage RunEvent)
- 실제 cron 트리거 (Airflow DAG 통합)

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

## 📌 Phase 4 진입 체크리스트 (2026-09-01 운영팀 합류 직전 검증)

### 코드 측면
- [x] Phase 1~3 DoD 모두 충족 (2026-04-26 완료)
- [x] ADR 0001~0009 기록 (드라이버 듀얼 / Object Storage / Outbox / 표준화 / Crowd
  placeholder / Visual Designer / SQL sandbox / 버전 관리)
- [x] migration 0001~0020 적용 + downgrade 스크립트 동봉
- [x] backend ruff/mypy strict 모두 clean (110 source files)
- [x] frontend tsc strict noEmit clean

### 인프라 / 운영 측면 (실 NCP 환경 가동 후)
- [ ] **성능 회귀 baseline 측정** — `PERF=1` 환경에서 backend perf tests + Playwright
  designer render 1회 측정 → PHASE_3_VISUAL_ETL.md 3.4 표에 baseline 기록.
- [ ] `docs/ops/NKS_DEPLOYMENT.md` 마이그레이션 가이드 점검 (Phase 1 ~ 3 모든 컨테이너
  이미지 NKS 호환성 확인).
- [ ] 컨테이너 이미지가 NKS Ready 8계명 준수 — Phase 1.2.2 Dockerfile 기준 + Phase 2/3
  추가된 worker 이미지도 동일 정책.
- [ ] Terraform 베이스라인 skeleton 준비 (실제 apply 는 운영팀과 — `infra/`).
- [ ] NCP managed PostgreSQL replica 스킨 검토 (ADR-0008 의 sandbox replica 마이그
  트리거 — Phase 4.x 에서 결정).
- [ ] Airflow 통합 PoC — `wf.workflow_definition.schedule_enabled=TRUE` PUBLISHED 워크플로
  를 Airflow DAG 에서 polling 해 trigger_run 하는 흐름 (Phase 3.2.7 의 `schedule_cron`
  필드는 이미 시드됨, 트리거만 미연결).

### 운영팀 합류 자료 (5종)
- [ ] **1. 시스템 아키텍처 투어** (30분 슬라이드) — Phase 1~3 의 핵심 모듈 8개 (수집 /
  outbox / OCR / 표준화 / price_fact / Designer / SQL Studio / 스케줄) + ADR 인덱스.
- [ ] **2. 도메인 모델 소개** — `docs/04_DOMAIN_MODEL.md` + 채널 7종 (POS API / DB-to-DB
  / 크롤링 / OCR / 영수증 / KAMIS / 축산 API) 표준화 흐름.
- [ ] **3. Phase 1~3 기능 데모** (녹화) — Designer 신규 + PUBLISH + 실행 + Backfill +
  SQL Studio 승인 + 재실행 시나리오.
- [ ] **4. 알려진 기술부채 리스트** — sandbox replica 미적용 / cron 트리거 미연결 /
  OCR/CRAWLER 정식 노드 미구현 / lineage 자동 추출 미연결 / Monaco editor 미도입 /
  100 노드 perf baseline 미측정.
- [ ] **5. Phase 4 우선순위 제안서** — Crowd 정식 / NKS 이관 / Public API / CDC PoC
  순서 + 각 sub-phase ETA.

### 첫 주 onboarding 실습 (운영팀 6~7명)
| 일차 | 실습 내용 | 산출물 |
|---|---|---|
| Day 1 | 로컬 docker-compose 기동 + admin 로그인 + Designer 첫 워크플로 생성 | 7명 모두 자기 워크플로 1개 |
| Day 2 | SQL Studio 에서 템플릿 실행 + 새 SQL 자산 create→submit→approve | DRAFT/PENDING/APPROVED 상태머신 체험 |
| Day 3 | Backfill 일배치 7일치 + 재실행 (특정 노드부터) | runs 검색 화면 익숙 |
| Day 4 | 운영자 화면 (Crowd 큐 / Dead Letter / Runtime 모니터) 익히기 | Phase 2.2.10 화면 |
| Day 5 | NKS 환경 1주 후 이관 시나리오 검토 + 본인 owner 후보 영역 선정 | Phase 4 task 분배 초안 |

### Owner 후보 영역
- **Airflow DAG 통합** — 시스템 cron 트리거 + 시스템 정기 파이프라인 (운영자 1명)
- **NKS 이관** — manifest / Argo CD / Grafana (운영자 2명)
- **Crowd 정식** — `crowd.*` schema + 이중 검수 + SLA + 보상 (운영자 1~2명)
- **Public API** — API Key + Rate Limit + 외부 가격 조회 (운영자 1명)
- **CDC** — Phase 4 조건부 (CDC 소스 3+ 또는 트래픽 500K/일+)
