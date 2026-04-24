# Phase 4 — Enterprise & External Service

**기간 목표:** 10~12주
**성공 기준 (DoD):**
1. 영수증 OCR 검수 등 Crowd 워크플로우가 정식 운영 가능.
2. 데이터 품질 실패가 Mart 반영을 자동 차단한다 (승인 시 해제).
3. 외부 소비자가 API Key로 가격 조회 API를 호출할 수 있다.
4. 다중 소스 상품 매칭이 자동으로 머지되어 마스터가 정합한다.
5. **NKS 이관 완료** — 운영팀 6~7명이 Argo CD/Grafana/kubectl 로 독립 배포/관제 가능.

---

## 4.1 Phase 4 범위

**포함:**
- ✅ Crowd 검수 워크플로우 정식 운영
  - OCR_REVIEW / PRODUCT_MATCHING / RECEIPT_VALIDATION / ANOMALY_CHECK
  - 이중 검수 + 충돌 해결
  - 작업자별 품질 점수
- ✅ 데이터 품질 "게이트" (severity=ERROR면 pipeline_run ON_HOLD)
- ✅ 승인자 해제 플로우
- ✅ CDC 통합 (소스 DB 하나에 대해 PoC)
- ✅ RLS (Row Level Security) + 컬럼 마스킹 (내부 민감 필드 대비)
- ✅ 외부 서비스용 Public API
  - API Key 발급/관리
  - Rate Limit + Quota
  - `/public/v1/prices/*`, `/public/v1/products/*`, `/public/v1/standard-codes/*`
- ✅ API Gateway 역할 (FastAPI 경로 분리 + NCP API Gateway 검토)
- ✅ partition archive 자동화
  - raw 13개월+ → Object Storage archive 등급 이동
  - 운영 DB에서 DETACH
- ✅ Multi-source 상품 매칭 머지 (동일 상품이 여러 유통사에서 관찰될 때 canonical 통합)
- ✅ 대시보드: 외부 API 사용량, 비용, SLA
- ✅ 장애 복구 (RPO 1시간 / RTO 4시간) 테스트
- ✅ **NKS(Naver Kubernetes Service) 이관**: Terraform + Helm + Argo CD + 운영팀 온보딩

**제외 (추후):**
- ❌ 개인화 추천
- ❌ 모바일 SDK
- ❌ 다국어

---

## 4.2 작업 단위 체크리스트

### 4.2.1 Crowd 검수 워크플로우 [W1~W3]

- [ ] 작업함 UI (`/crowd/tasks`)
  - 필터: task_kind, priority, assigned_to_me
  - 상세: OCR_REVIEW는 원본 이미지 + 추출 라인 편집
  - PRODUCT_MATCHING은 후보 top-5 중 선택 + 신규 등록
- [ ] 이중 검수 정책:
  - priority >= 8 : 2인 이상 검수 필수, 결과 다르면 CONFLICT → 관리자 검토
  - 그 외 : 1인 검수로 충분
- [ ] 작업자 성과 테이블 `ctl.reviewer_stats`:
  - 건수, 평균 처리 시간, 충돌률, 이후 회귀 오류율
- [ ] 검수 완료 → pipeline_run HUMAN_REVIEW 노드 재개 이벤트 발행
- [ ] 재처리 흐름: REJECTED 결과는 `stg` 로 되돌리고 재표준화

### 4.2.2 DQ 게이트 [W3~W4]

- [ ] `app/domain/quality.py`:
  - rule 실행 엔진 (rule_sql 실행 + 실패 row 수집)
  - severity=ERROR 실패 시 `pipeline_run.status = ON_HOLD`
  - `dq.quality_result.status='FAIL'` + sample_json 저장
- [ ] 승인 UI:
  - ON_HOLD pipeline_run 목록
  - 실패 규칙 + 실패 row 샘플 확인
  - 승인(강제 진행) 또는 거부(롤백)
  - 승인자 = APPROVER role 필수
- [ ] 승인 이력: `run.hold_decision` 테이블 (signer, reason, decision, occurred_at)
- [ ] 자동 알림 (Slack/이메일): ON_HOLD 발생 시

### 4.2.3 CDC PoC [W4~W5]

**두 가지 경로 중 하나 선택, 선택 시 ADR 기록:**

**경로 A — 경량 (기본, 소스 1~2개)**
- [ ] `wal2json` + logical replication slot 직접 구독
- [ ] Python consumer → `raw.db_cdc_event` insert → Dramatiq `transform` 큐
- [ ] Kafka/Debezium 없이 운영, 복잡도 최소
- [ ] Airflow DAG: CDC lag 모니터링, snapshot+CDC 머지, slot 관리

**경로 B — Kafka + Debezium (소스 3개 이상으로 확장 시)**
- [ ] **Kafka 정식 도입 트리거 여기서 발생.** 도입 전 ADR + 사용자 승인.
- [ ] NCP에 Kafka 직접 배포 (Strimzi 또는 bitnami/kafka Docker) — KRaft 모드로 Zookeeper 제거
- [ ] Debezium Connect 배포 (PG/MySQL/MSSQL connector)
- [ ] topic 네이밍: `cdc.<source>.<schema>.<table>`
- [ ] Python consumer group: `transform-cdc-consumer`
- [ ] Airflow DAG: Kafka consumer lag 감시, DLQ 재처리 trigger
- [ ] Redis Streams는 "애플리케이션 이벤트", Kafka는 "DB CDC 이벤트"로 **역할 분리**

**공통:**
- [ ] `raw.db_cdc_event` 테이블에 변경 로그 저장
- [ ] CDC lag 모니터링 메트릭 + 알람
- [ ] Snapshot + CDC 결합 시 business_key 기준 머지

### 4.2.4 RLS + 컬럼 마스킹 [W5]

- [ ] 사용자 역할에 따라 `mart.retailer_master`, `mart.seller_master` 의 일부 컬럼 마스킹
  - 예: 사업자번호는 ADMIN 외 `***-**-****`
  - 내부 주소는 APPROVER/OPERATOR만 raw 접근
- [ ] RLS 정책: `mart.seller_master` 에 retailer_allowlist 기반 제한 (외부 API 키별)
- [ ] 운영 DB 유저 분리:
  - `app_rw` — 일반 API
  - `app_mart_write` — Mart upsert 전용
  - `app_readonly` — SQL sandbox
  - `app_public` — 외부 API 조회 전용 (RLS 적용)

### 4.2.5 Public API (외부 서비스) [W5~W8]

- [ ] API Key 관리 (이미 3.2에 테이블 생성됨)
  - 발급: 최초 1회만 full key 평문 노출, 이후 prefix + hash 저장
  - 스코프: `prices.read`, `products.read`, `aggregates.read`
- [ ] Rate Limit: slowapi + Redis, key별 `rate_limit_per_min`
- [ ] Public 엔드포인트:
  - `GET /public/v1/standard-codes` — 표준코드 목록/검색
  - `GET /public/v1/products` — 마스터 상품 검색 (std_code, 이름)
  - `GET /public/v1/prices/latest?std_code=&retailer_id=&region=` — 최신 가격
  - `GET /public/v1/prices/daily?std_code=&from=&to=&retailer_id=&region=` — 일별 집계
  - `GET /public/v1/prices/series?product_id=&from=&to=` — 시계열
- [ ] OpenAPI 별도 문서 (`/public/docs`)
- [ ] 응답 캐시 (Redis, 60~300초) — std_code/daily 같은 조회에 적용
- [ ] 사용량 로깅: `audit.public_api_usage` (일별 집계)

### 4.2.6 Gateway / 보안 [W7]

- [ ] 옵션 1: NCP API Gateway에 docs + 인증 위임
- [ ] 옵션 2: nginx 단에서 /public/ 만 별도 도메인 (`api.datapipeline.co.kr`)
- [ ] HTTPS + HSTS
- [ ] 1개 키당 동시 연결 제한
- [ ] 악용 탐지: 동일 IP 여러 키 사용 시 알람

### 4.2.7 Partition Archive 자동화 [W8]

- [ ] 매월 1일 04:00 배치:
  - `raw.raw_object_YYYY_MM` 중 13개월 이상 경과 파티션 detect
  - 내용 Object Storage archive 등급으로 복제 (`archive/{YYYY}/{MM}/`)
  - 검증 (row count, checksum) → DETACH → DROP 또는 보존
  - 작업 이력 `ctl.partition_archive_log`
- [ ] 복원 스크립트: archive key → 임시 테이블로 복원

### 4.2.8 Multi-source 머지 [W8~W9]

- [ ] 동일 상품이 여러 유통사에서 관찰될 때 `mart.product_master` 에 하나로 수렴.
- [ ] 머지 규칙:
  - canonical_name 은 가장 빈도 높은 표현
  - weight_g/grade/package_type 다수결
  - 분쟁 시 crowd_task(PRODUCT_MATCHING) 자동 생성
- [ ] 머지 이력: `mart.master_entity_history`

### 4.2.8b NKS 이관 (운영팀 6~7명 합류 대비) [W1~W8, Phase 4 전반에 걸쳐 병행]

상세 가이드: `docs/ops/NKS_DEPLOYMENT.md`

- [ ] **Terraform 베이스라인** (`infra/terraform/ncp/`)
  - VPC/Subnet/ACG
  - NKS 클러스터 (Worker node pool: `s2-g3` 3대 시작)
  - Cloud DB PG (prod + staging), Cloud DB Redis
  - Object Storage 버킷
  - Container Registry
- [ ] **staging 네임스페이스 먼저 구축**: NKS `datapipeline-staging`
- [ ] **Helm Chart 작성** (`infra/k8s/helm/datapipeline/`):
  - `backend-api`, `worker-transform`, `worker-ocr`, `worker-crawler`, `frontend`, `scheduler`
  - `airflow-webserver`, `airflow-scheduler`, `airflow-worker`(Celery)
  - Kustomize overlays: `base/`, `overlays/staging/`, `overlays/prod/`
- [ ] **Argo CD 설치 + Application 등록**: Git repo `infra/k8s/` 와 sync
- [ ] **External Secrets Operator** 설치 + NCP Secret Manager 연동
- [ ] **ingress-nginx + cert-manager** (Let's Encrypt)
- [ ] **HPA 정책** 등록:
  - backend-api: CPU 70%
  - worker-ocr: 커스텀 메트릭 `dramatiq_queue_lag{queue="ocr"}`
  - worker-transform: 동일
- [ ] **NetworkPolicy**:
  - `backend-api` → DB, Redis, Object Storage 엔드포인트만
  - `worker-*` → Redis, DB만
  - `frontend` → `backend-api` 만
- [ ] **PodDisruptionBudget**:
  - `backend-api` minAvailable: 2
  - 기타 Deployment도 최소 1 유지
- [ ] **Observability 네임스페이스**:
  - kube-prometheus-stack
  - Loki + Promtail
  - 기존 Grafana 대시보드 JSON 이관
- [ ] **Velero 백업** (클러스터 리소스 + PV, Object Storage 대상)
- [ ] **DB Migration Job 패턴**: Alembic은 pre-install/pre-upgrade Helm hook으로
- [ ] **병행 운영 2주** — 기존 VM 환경과 NKS 동시 가동, 트래픽 점진 이전
- [ ] **폐기 절차** — VM docker compose 환경 종료, 모니터링 확인 1주
- [ ] **운영 런북 작성** (`docs/runbooks/`):
  - 배포 / 롤백 / 장애 대응 / 백업-복구 / 스케일링
- [ ] **운영팀 온보딩 자료** 3종:
  - Kubernetes 기본 개념 (1시간)
  - 이 프로젝트 NKS 구조 투어 (2시간)
  - 장애 대응 시뮬레이션 (실습 1회)

### 4.2.9 장애 복구/HA [W9~W10]

- [ ] NCP Cloud DB PG 백업 정책: 일 단위 자동 + WAL 기반 PITR
- [ ] Object Storage cross-region replication 검토
- [ ] 애플리케이션 VM 2대 + Load Balancer (읽기 scale-out)
- [ ] Worker VM 2대로 분리 (ocr 전용 / transform+crawler)
- [ ] RTO/RPO 테스트 리허설 (실제 재해 가정 시나리오 실행)

### 4.2.10 관제/비용 대시보드 [W10~W12]

- [ ] Grafana "Enterprise" 대시보드:
  - 외부 API qps, 에러율, top 키
  - CLOVA OCR 사용량/비용 (월 예산 기준 bar)
  - pgvector 인덱스 크기/쿼리 성능
  - DLQ/ON_HOLD 누적 추세
- [ ] 월간 비용 리포트 스크립트 (NCP 빌링 API 연동 검토)

---

## 4.3 샘플 시나리오

**시나리오 A — 영수증 대량 유입 및 검수**
1. 소비자 100명이 동시에 영수증 업로드 → 100개 raw_object.
2. OCR worker 5개가 병렬 처리 → 80건 자동 반영, 20건 crowd_task.
3. 내부 검수자 3명이 작업함에서 병렬 처리.
4. 2인 검수 결과 일치한 18건 자동 승인 → mart 반영.
5. 2건 충돌 → 관리자 검토 후 결론.
6. 전체 시간: 5분 이내.

**시나리오 B — DQ 게이트로 잘못된 배치 차단**
1. 크롤러 파서 버그로 가격 단위가 100배 부풀려진 데이터 수집.
2. DQ rule "가격 범위 체크" (severity=ERROR) 실패.
3. pipeline_run 자동 ON_HOLD.
4. 승인자 UI에서 샘플 확인 후 REJECT → 관련 stg row rollback.
5. 파서 수정 후 재실행.

**시나리오 C — 외부 API 사용**
1. 외부 소비자 "FoodTech Inc"에 API Key 발급 (scope=prices.read, 60 req/min).
2. curl `GET /public/v1/prices/daily?std_code=FRT-CHAMOE&from=2026-04-01&to=2026-04-25` → 200 OK.
3. rate limit 초과 시 429.
4. 운영자가 월별 사용량/비용 대시보드 확인.

---

## 4.4 보안 점검 (Phase 4 종료 전 필수)

- [ ] 외부 API endpoint에는 내부 소스 정보(raw_object_id, source_code 등) 노출 금지
- [ ] Public API 응답은 RLS 통과 후 결과만
- [ ] API Key 리크 감지 (로그 패턴) 자동 알람
- [ ] 침입 탐지 (비정상 쿼리 패턴, 초당 수집량 급증 등)
- [ ] 개인정보 비식별 검증 (영수증 원본은 암호화 저장, 외부 API 응답에 절대 포함 안 됨)

---

## 4.5 오픈 이슈 (Phase 5 이상에서 검토)

- 한국 공공데이터 표준 변화 시 표준코드 정기 sync
- pgvector 성능 한계 시 외부 벡터 DB (Qdrant/Milvus) 도입
- Kafka 도입 시점 (실측 500K/일 초과 시)
- NKS(Kubernetes) 전환 시점 (VM 5대 이상 운영 필요 시)
- 다국어 상품명 지원 (수입 농산물 확대 시)
