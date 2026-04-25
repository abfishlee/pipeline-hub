# 전체 기능 Walkthrough — 데모 시나리오 8종

**목적**: 사용자/검토자가 http://127.0.0.1:5173 에 접속해 8개 시나리오를 순서대로 직접
시연하면서 Phase 1~3 의 모든 핵심 기능을 30분 안에 체험.

각 시나리오마다:
- **What** — 무엇을 시연하는지
- **Where** — 어느 메뉴
- **How** — 클릭/입력 순서
- **Expected** — 기대 결과
- **확인 포인트** — 사용자가 질문할 만한 부분

---

## 사전 준비

1. http://127.0.0.1:5173 접속
2. `admin` / `admin` 로그인
3. 좌측 사이드바 13개 메뉴 확인 (ADMIN 역할이라 모두 보임)
4. 시드 완료 확인:
   - 데이터 → 워크플로 3개 (online_crawl/receipt_ocr/retail_api_price)
   - SQL Studio → 좌측 12개 SQL 자산

---

## 시나리오 1 — Visual ETL Designer 신규 워크플로 생성 (5분)

### What
빈 화면에서 시작해 노드 5개의 워크플로를 그려 저장 + PUBLISH.

### How
1. **Visual ETL Designer** 진입 (좌측 사이드바)
2. 좌측 팔레트에서 캔버스로 drag:
   - SOURCE_API → 위치 (0, 0)
   - DQ_CHECK → 위치 (200, 0)
   - SQL_TRANSFORM → 위치 (400, 0)
   - LOAD_MASTER → 위치 (600, 0)
   - NOTIFY → 위치 (800, 0)
3. 각 노드의 핸들을 drag 해서 순서대로 연결 (4개 엣지)
4. 우측 패널에서 각 노드의 `config_json` 입력:
   - SOURCE_API: `{"source_code": "EMART_API", "limit": 100}`
   - DQ_CHECK: `{"input_table": "stg.daily_prices", "assertions": [{"kind": "row_count_min", "min": 1}]}`
   - SQL_TRANSFORM: `{"sql": "SELECT * FROM stg.daily_prices WHERE captured_at >= now() - interval '1 day'"}`
   - LOAD_MASTER: `{"source_table": "stg.daily_prices", "target_table": "mart.product_price", "key_columns": ["sku", "captured_at"]}`
   - NOTIFY: `{"channel": "slack", "target": "#test", "body": "test"}`
5. 상단 좌측 input 에 이름 입력 (예: `demo_workflow_1`)
6. 우측 상단 **저장** 클릭 → 토스트 `생성 완료 (workflow_id=N)`
7. **PUBLISH** 클릭 → 토스트 `v2 배포 완료 (release #N)` + 새 워크플로로 자동 이동

### Expected
- 캔버스의 노드 5개 + 엣지 4개 정상 표시
- 저장 후 URL 이 `/pipelines/designer/{새 ID}` 로 변경
- PUBLISH 후 status badge 가 `DRAFT` → `PUBLISHED` 로 변경
- 좌측 사이드바 **배포 이력** 진입 → release #N row 보임

### 확인 포인트
- "PUBLISH 했는데 왜 워크플로 ID 가 바뀌어요?" → ADR-0009 참고: PUBLISHED 는 새 row,
  원본 DRAFT 는 그대로 유지 (사용자가 다음 버전 계속 편집 가능)
- "config_json 이 비어 있어도 되나요?" → 노드 type 별 필수 필드는 노드 실행 시점에 검증

---

## 시나리오 2 — 배포 이력 + 변경 요약 (3분)

### What
같은 워크플로를 두 번 publish 하면서 diff 계산 확인.

### How
1. 시나리오 1 의 워크플로 (이름: `demo_workflow_1`) 가 PUBLISHED 상태
2. **Visual ETL Designer** 의 좌측 사이드바에서 같은 name 의 DRAFT 진입 (또는 그냥 신규 → 같은 이름 으로 저장)

   *팁*: PUBLISH 직후 자동 redirect 된 화면은 PUBLISHED 라 readonly. 같은 이름의 DRAFT 가 있어야 편집 가능.
3. DEDUP 노드 1개 추가 → 저장 → PUBLISH
4. **배포 이력** 메뉴 진입 → workflow_name 필터 = `demo_workflow_1`
5. 표에 release 2개 보임 (v2, v3)
6. v3 row 의 **상세** 클릭

### Expected
- v3 의 변경 요약: `+1 -0 ~0` (DEDUP 노드 추가)
- 상세 패널에 색상 블록:
  - 추가 (1): `dedup_<...>` (emerald)
  - 제거 (0): 없음
  - 변경 (0): 없음
  - 엣지 +/- 표시

### 확인 포인트
- "diff 가 어떻게 계산되나요?" → node_key 기준 (같은 key 가 양쪽 → changed, 한쪽만 → added/removed). config_json 은 정렬된 JSON 으로 비교

---

## 시나리오 3 — SQL Studio sandbox + EXPLAIN (4분)

### What
SQL Studio 에서 안전하게 SELECT 검증 + 결과 미리보기 + EXPLAIN.

### How
1. **SQL Studio** 진입
2. 좌측에서 `stg_dedup_row_count` 클릭
3. 본문이 자동 로드됨 (CTE 가 있는 SQL)
4. 상단 **Validate** → 통과 배너 + 참조 테이블: `stg.price_observation`
5. **Preview** → 결과 0 row (mart 비어 있음 — 정상)
6. **EXPLAIN** → JSON plan 표시
7. 본문 끝에 ` LIMIT 5` 추가 → 다시 **Preview** → 차이 비교
8. 본문을 `DROP TABLE stg.price_observation` 으로 바꾸고 **Validate** → 422 + 차단 사유

### Expected
- Validate 통과 시 emerald 배너 + 참조 테이블 1개
- DROP 시도 시 rose 배너 + `only SELECT statements are allowed (got DROP)`
- EXPLAIN 의 JSON plan 이 보기 좋게 펼쳐짐

### 확인 포인트
- "DROP/DELETE/COPY 도 막히나요?" → sqlglot 정책 12개 모두 차단 (ADR-0008)
- "결과 1000 row 가 넘으면?" → LIMIT 1000 자동 부착 + truncated=true 표시
- "방금 실행한 SQL 이 audit 에 남나요?" → `audit.sql_execution_log` 에 VALIDATE/PREVIEW/EXPLAIN 별 1행씩

---

## 시나리오 4 — SQL 자산 라이프사이클 (DRAFT → PENDING → APPROVED) (3분)

### What
새 SQL 자산을 만들어 제출 + 승인.

### How
1. **SQL Studio** 좌측 → **신규** 버튼
2. 이름: `demo_sql_1`, 본문: `SELECT product_id FROM mart.price_fact LIMIT 10`
3. **생성 (DRAFT v1)** → 좌측 트리에 추가됨, status = DRAFT
4. **제출** → status = PENDING
5. **승인** 시도 → 422 (`self-approval is not allowed` — admin 본인이 submit 했기 때문)

   *팁*: 별도 APPROVER 사용자 만들어 시연하면 정상 흐름 끝까지 가능
6. **반려** 클릭 → 코멘트 입력 → status = REJECTED
7. 새 DRAFT 만들어 재제출 가능

### Expected
- status badge 가 단계마다 색상 변경
- self-approval 차단 메시지 노출

### 확인 포인트
- "왜 본인 SQL 을 본인이 승인 못 해요?" → 이중 검토 강제 보안 정책 (ADR 0008)
- "REJECTED 되면 어떻게 되나요?" → 새 DRAFT version 만들어 재제출 (version_no +1)

---

## 시나리오 5 — 스케줄 + Backfill 시연 (3분)

### What
PUBLISHED 워크플로에 cron 등록 + 과거 일자 backfill.

### How
1. **파이프라인 실행** 메뉴 → 워크플로 표 → `retail_api_price__emart` 의 **편집/보기** 클릭
2. PUBLISHED 가 아니면 PUBLISH 먼저
3. PUBLISHED 상태에서 툴바의 cron 영역 표시됨
4. cron 입력: `0 5 * * *` → "활성" 체크 → **스케줄 저장**
5. **Backfill** 버튼 클릭 → 시작 `2026-04-01`, 종료 `2026-04-03` 입력 → **실행**
6. 토스트 `Backfill 적재됨 — run 3개`
7. **파이프라인 실행** 메뉴 → 같은 workflow 필터 → 3개의 PENDING run 보임 (run_date 가 2026-04-01/02/03)

### Expected
- cron 저장 후 워크플로 detail 에 `0 5 * * * · ON` 표시
- Backfill 후 같은 (workflow, date) 멱등 (다시 실행해도 같은 ID 반환)

### 확인 포인트
- "366일 넘으면?" → 한도 초과 422
- "PENDING 인 채로 실행 안 되는데?" → Worker (Phase 4 의 Airflow) 가 가동되어야 함 — 본 데모에선 PENDING 까지만

---

## 시나리오 6 — 재실행 (전체 / 특정 노드부터) (3분)

### What
실패한 run 또는 일부만 재실행.

### How
1. **파이프라인 실행** 메뉴 → 아무 run 의 **상세** 클릭
2. 헤더 우측 **처음부터 재실행** 버튼 클릭 → 토스트 `재실행 시작 — new run #N`
3. 새 run detail 로 자동 이동
4. 노드별 row 의 **이 노드부터** 버튼 (FAILED/SUCCESS 노드만) 클릭
5. 토스트 `'<node_key>' 부터 재실행 — new run #N`

### Expected
- 새 run 생성 + 새 run detail 로 redirect
- 특정 노드부터 재실행 시 그 노드의 ancestors 는 SUCCESS 시드 + 노드 자체는 READY + 후손은 PENDING

### 확인 포인트
- "왜 새 run 을 만드나요? 같은 run 다시 안 돌리나요?" → run_id 가 시간 기록의 unit. 재실행 = 새 인스턴스
- "ancestors 의 output_json 이 필요한 노드는?" → Phase 3 한정 — SUCCESS 만 시드 + Phase 5 lineage 결합 시 보강 예정

---

## 시나리오 7 — 데이터 흐름 한눈에 (5분)

### What
4계층 모델 (raw → stg → mart) 의 흐름을 화면 + DB 로 동시에 확인.

### How
1. **데이터 소스** 메뉴 진입 → ctl.data_source 행 보기
2. **원천 데이터** 메뉴 → 비어 있음 (raw_object 적재된 데이터 없음)
3. PowerShell 또는 별도 터미널에서:
   ```bash
   docker exec dp_postgres psql -U app -d datapipeline -c \
     "SELECT n.nspname, c.relname FROM pg_class c \
      JOIN pg_namespace n ON n.oid=c.relnamespace \
      WHERE c.relkind='r' AND n.nspname IN ('ctl','raw','stg','mart','wf','run','audit','dq') \
      ORDER BY 1,2 LIMIT 30;"
   ```
4. 30+ 테이블 출력 — schema 8개 모두 존재
5. **SQL Studio** → `stg_standardization_validate` 템플릿 → Validate → 참조 테이블 = `stg.price_observation`
6. 같은 SQL 을 Preview → 0 row (stg 비어 있음)
7. ERD HTML 열기: `file://e:/dev/datapipeline/docs/deliverables/03_erd.html`

### Expected
- 8 schema (ctl/raw/stg/mart/wf/run/audit/dq) 모두 존재
- 마이그레이션 0001~0020 적용 확인
- ERD 한 장으로 전체 관계 시각화

### 확인 포인트
- "데이터가 비어 있는데 어떻게 시연하나요?" → 시드 admin + 워크플로 + SQL 자산만 있음. 실제 데이터 흐름은 외부 시스템이 raw 로 push 해야 시작 → Phase 4 의 Airflow + 외부 source 연결 후 자동 흐름
- "왜 mart 가 비어 있나요?" → raw → stg → mart 흐름이 완성되려면 OCR/크롤러 worker 가동 필요 → Phase 2 인프라 (Phase 3 한정 시연에선 메타만)

---

## 시나리오 8 — 산출물 PDF 변환 (2분)

### What
HTML 산출물 3개를 Chrome 으로 PDF 추출.

### How
1. Chrome 에서 다음 URL 열기:
   - `file:///e:/dev/datapipeline/docs/deliverables/01_system_overview.html`
   - `file:///e:/dev/datapipeline/docs/deliverables/02_user_manual.html`
   - `file:///e:/dev/datapipeline/docs/deliverables/03_erd.html`
2. 각 파일에서 `Ctrl + P`
3. **인쇄 대상**: PDF로 저장
4. 03 (ERD) 만 **용지**: A3 → **방향**: 가로
5. **추가 설정** → **배경 그래픽**: ✅ (SVG 색상 보존)
6. 저장

### Expected
- 01: ~14페이지 (시스템 개요, A4 세로)
- 02: ~16페이지 (사용자 매뉴얼, A4 세로)
- 03: ~6페이지 (ERD, A3 가로)

### 확인 포인트
- "왜 PDF 직접 안 만들고 HTML?" → weasyprint/wkhtmltopdf 가 환경에 따라 깨질 수 있음. Chrome 인쇄 → PDF 가 가장 정확하고 SVG 색상 보존
- "이미지/스크린샷 추가는?" → 02 의 점선 박스 자리에 운영자가 직접 캡처해 `<img>` 로 교체

---

## 부록 — Q&A 빠른 참조

| 질문 | 답변 위치 |
|---|---|
| 시스템 목표 / 4계층 모델 | 01_system_overview.html §2~§3 |
| 핵심 기능 10개 + 기술 스택 | 01_system_overview.html §4 |
| 10단계 파이프라인 / 채널 7종 | 01_system_overview.html §5~§6 |
| 표준화 3단계 매칭 | 01_system_overview.html §7 |
| Phase 진행 / 누적 산출물 / ADR 9건 | 01_system_overview.html §8~§9 |
| 채널별 (POS API / DB / Crawl / OCR) 작업 절차 | 02_user_manual.html §3~§6 |
| 스케줄 / Backfill / 재실행 절차 | 02_user_manual.html §7 |
| SQL Studio 라이프사이클 | 02_user_manual.html §8 |
| 트러블슈팅 6분류 | 02_user_manual.html §9 |
| ERD + 47 FK + 정책 | 03_erd.html (전체) |
| Phase 4 13단계 진행 절차 | docs/phases/PHASE_4_PROMPTS.md |
| Phase 5 (v2 generic) 마이그 | docs/phases/PHASE_5_GENERIC_PLATFORM.md |
| Ubuntu 회사 서버 배포 | docs/ops/UBUNTU_STAGING_DEPLOYMENT.md |
