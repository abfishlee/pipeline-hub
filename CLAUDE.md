# CLAUDE.md — Unified Data Pipeline Platform (공용 데이터 수집 플랫폼)

**이 프로젝트는 "공용 데이터 수집 파이프라인 플랫폼"이다.**
도메인 (농축산물 / 부동산 / IT 통계 / 정부 공공데이터 등) 에 종속되지 않고,
어떤 외부 데이터든 사용자가 Canvas 로 직관적으로 설계 → Job 으로 등록 → 주기 실행 →
표준 마트 적재까지 코드 0줄로 가능하게 만든 글로벌 스탠다드 솔루션이다.

**현재 첫 실증 도메인 = 농축산물 가격 수집** (Phase 8 시드 / Phase 9 실증).
이후 부동산, IT 통계 등 어떤 도메인이든 같은 플랫폼으로 동일하게 수집 가능.

Claude는 이 파일을 먼저 읽은 뒤, 작업 전 반드시 해당하는 `docs/` 문서를 읽고 시작한다.

---

## 1. 이 프로젝트가 무엇인지

- **목적:** 어떤 외부 채널 (Public API / Inbound Push / DB CDC / OCR / Crawler / 파일 업로드) 의 데이터든 수집 → 평탄화 → 표준화 → 마트 적재 → 외부 서비스의 *전체 흐름을 화면에서 코드 0줄로 설계 가능* 하게 만드는 데이터 파이프라인 *플랫폼*. 특정 도메인 (가격/상품/주소/거래 등) 의 솔루션이 *아니라* 그 위에 어떤 도메인이든 얹을 수 있는 *기반*.
- **첫 실증 도메인:** Phase 8 ~ Phase 9 에서 *농축산물 가격 데이터 수집·표준화·서비스* 를 시범 적용. 이는 *플랫폼의 첫 사용 사례일 뿐* 이며, 시스템 코드/화면에는 농축산물·KAMIS·가격 같은 도메인 특정 표현이 박혀있으면 안 됨 (도메인 무관).
- **팀:** Phase 1~3 개발 = 사용자(Product Owner 1명) + Claude(개발자). Phase 4 운영 이관 시 **운영팀 6~7명 합류** 예정. 개발 중엔 단순함 최우선, 이관 대비해서 **stateless·헬스체크·12-factor** 규칙은 처음부터 지킨다.
- **규모 (첫 실증 기준):** 평시 10만 rows/일, 피크 30만 rows/일. OCR 1,000페이지/일. *플랫폼 자체는 도메인/규모 가변*.
- **SLA:** Mart 반영까지 **실시간**(수집 후 1분 이내).
- **배포:** 로컬 개발 → Naver Cloud Platform(NCP) 운영.
- **상태:** Greenfield (코드 0줄에서 시작).

## 2. 작업 시작 전 반드시 읽을 문서

| 상황 | 읽을 문서 |
|---|---|
| 프로젝트 전체 맥락을 모를 때 | `docs/00_PROJECT_CONTEXT.md` |
| 새 라이브러리/서비스 선택 시 | `docs/01_TECH_STACK.md` (여기 없는 스택은 도입 전 사용자 확인) |
| 새 파일/폴더 만들 때 | `docs/02_ARCHITECTURE.md` |
| DB 스키마 변경 시 | `docs/03_DATA_MODEL.md` |
| 첫 실증 도메인 (농축산물 가격) 의 모델 작성 시 | `docs/04_DOMAIN_MODEL.md` (도메인 sample, 다른 도메인은 별도 정의) |
| 코딩 중 | `docs/05_CONVENTIONS.md` |
| 데이터 흐름 10단계 이해 | `docs/06_DATA_FLOW.md` |
| K8s/Airflow/Kafka 개념 이해 | `docs/07_CORE_TECHNOLOGIES.md` |
| 환경 분리 (dev/staging/prod) | `docs/ENVIRONMENTS.md` |
| 단계별 구현 할 일 | `docs/phases/PHASE_*.md` |
| 현재 Phase / 타임라인 | `docs/phases/CURRENT.md` |
| NCP 배포 관련 (Phase 1~3, Docker Compose) | `docs/ops/NCP_DEPLOYMENT.md` |
| NKS 이관 (Phase 4) | `docs/ops/NKS_DEPLOYMENT.md` |
| Airflow 학습/설계 | `docs/airflow/LEARNING_GUIDE.md`, `docs/airflow/INTEGRATION.md` |
| Claude에게 효과적으로 지시하는 법 | `docs/HOW_TO_WORK_WITH_CLAUDE.md` |

## 3. Claude 작업 원칙 (이 프로젝트 전용)

1. **Phase 순서 엄수.** Phase 1 미완료 상태에서 Phase 2/3/4 기능을 먼저 만들지 않는다. 현재 Phase는 `docs/phases/CURRENT.md`에 기록한다(없으면 Phase 1).
2. **배포 방식 2-stage.** Phase 1~3(개발) = **Docker Compose** (단일 VM, 사용자+Claude 2인 개발 속도 우선). Phase 4(운영 이관, 운영팀 6~7명 합류) = **NKS(Naver Kubernetes Service)** (산업 표준 운영 체계, GitOps, Auto-scale). **Phase 1~3에는 K8s manifest 만들지 마라.** Phase 4 이관 가이드는 `docs/ops/NKS_DEPLOYMENT.md`.

3. **Airflow는 Phase 2부터 정식 도입. Kafka는 Phase 4 조건부.** Airflow는 "시스템 정기 파이프라인" 전담, Visual ETL은 "사용자 정의 파이프라인" 전담으로 역할 분리. Kafka는 CDC 소스 3개 초과 또는 트래픽 500K/일 초과 시 재평가. 자세한 내용은 `docs/01_TECH_STACK.md`, `docs/airflow/INTEGRATION.md`.
4. **NCP-friendly 선택.** S3 대신 NCP Object Storage, AWS RDS 대신 NCP Cloud DB for PostgreSQL, Managed Redis 대신 NCP Cloud DB for Redis.
5. **한국어 도메인 + 영어 코드.** DB 컬럼/함수/변수는 영어, 주석/문서/UI는 한국어. 표준코드 매핑 라벨은 한국어 원본 보존.
6. **모든 수집 경로는 raw 보존 + idempotency_key 필수.** raw 누락 또는 중복 삽입 시 마스터 재처리 불가.
7. **DB 스키마 변경은 반드시 Alembic migration 파일로.** 직접 ALTER 금지.
8. **외부 API 호출은 `integrations/` 폴더에만 격리.** 비즈니스 로직에 직접 `requests.get` 금지.
9. **테스트 없는 코드는 merge 금지.** 최소 happy-path + 1 edge case.
10. **비밀키 git 금지.** `.env.example` 만 commit, 실제 값은 NCP Secret Manager / 로컬 `.env`.
11. **화면 있는 변경은 브라우저로 직접 확인 후 완료 보고.** 타입체크/유닛테스트만으로 "완료" 처리 금지.
12. **컨테이너 이미지는 NKS 이관 대비 규칙.** Phase 1부터 이미지에 상태 저장 금지 (stateless), 설정은 env/ConfigMap 주입 가능한 구조, 헬스체크 엔드포인트 필수(`/healthz`, `/readyz`), shutdown 신호(SIGTERM) 처리. 이 규칙만 지키면 Phase 4 NKS 이관이 쉬워진다.

## 4. 현재 위치

- **Phase 1 — Core Foundation (5주, ~2026-05-30)** 진행 예정. 상세 `docs/phases/PHASE_1_CORE.md`.
- **데드라인:** 2026-09-01 운영팀 6~7명 합류 → Phase 1~3까지 완료 목표. 세부 일정 `docs/phases/CURRENT.md`.
- 아직 코드 없음. 문서만 존재.

## 5. 질문/결정이 필요할 때

애매한 것은 **가정을 달고 진행**하되, 되돌리기 어려운 결정은 사용자에게 짧게 확인:
- DB 스키마 구조적 변경 (기존 테이블 drop/컬럼 제거)
- 외부 유료 서비스 도입 (CLOVA OCR, Upstage 등 — 비용 발생)
- NCP 인프라 프로비저닝
- 운영 배포 실행

## 6. 프로젝트 최상위 구조 (앞으로 생길 것)

```
datapipeline/
├── CLAUDE.md                # 이 파일
├── docs/                    # 설계 문서 (현재 존재)
├── backend/                 # FastAPI (Phase 1부터)
├── frontend/                # React + Vite (Phase 1부터)
├── worker/                  # Dramatiq Worker (Phase 2부터)
├── migrations/              # Alembic (Phase 1부터)
├── infra/                   # docker-compose, NCP Terraform (Phase 1부터)
├── scripts/                 # 운영 스크립트
└── tests/                   # 통합 테스트
```

## 7. 핵심 한 문장

> **"데이터를 많이 넣는 시스템이 아니라, *어떤 외부 데이터가 언제 어디서 들어와 어떤 규칙으로 표준화되어 어떤 마트에 반영되었는지* 끝까지 추적 가능한 *공용* 플랫폼. 도메인은 사용자가 결정한다."**
