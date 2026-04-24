# Claude와 효과적으로 일하는 법 (명령 가이드)

**대상:** 이 프로젝트에서 Claude에게 개발 작업을 시키는 사용자.
**목표:** 사용자가 적은 노력으로 정확한 결과를 얻도록, **어떤 형식으로 명령하면 Claude가 쉽게 작업하는지**를 알려준다.

---

## 1. 좋은 명령의 5가지 요소

Claude에게 일을 시킬 때 다음 5가지를 **하나의 메시지**에 담으면 품질이 급상승한다.

| # | 요소 | 예시 |
|---|---|---|
| 1 | **무엇을 (What)** | "수집 API `/v1/ingest/api/{source_code}` 를 구현해줘" |
| 2 | **왜 (Why)** | "Phase 1의 1.2.7 항목이고, 10만/일 수집의 입구야" |
| 3 | **어디에 (Where)** | "`backend/app/api/v1/ingest.py` 에 라우터, 도메인 로직은 `backend/app/domain/ingest.py`" |
| 4 | **어떻게 확인할지 (Verify)** | "테스트는 `tests/integration/test_ingest.py` 에, happy + idempotency 재시도 + 비활성 소스" |
| 5 | **제약/선호 (Constraints)** | "raw 저장 + outbox insert 는 같은 트랜잭션. 이미 작성된 `03_DATA_MODEL.md` 스키마와 일치" |

**복사용 템플릿:**

```
[작업] ...
[목적] ...  (관련 문서: docs/phases/PHASE_X.md 의 X.X.X)
[파일] ...
[완료 기준] ...
[제약] ...
```

## 2. 이 프로젝트 전용 — 문서 기반 명령

이 레포는 `docs/` 가 작업의 진실 원천이다. Claude에게 문서 경로와 섹션 번호만 줘도 맥락을 완전히 파악한다.

### 2.1 가장 좋은 시작 명령

```
docs/phases/PHASE_1_CORE.md 의 1.2.7 "수집 API" 부분을 구현해줘. 
docs/03_DATA_MODEL.md 의 raw 스키마와 정합하게. 
작업 전에 현재 레포 상태를 훑고 무엇부터 만들지 보고한 뒤 진행해.
```

### 2.2 단일 체크박스 단위로 명령

```
PHASE_1_CORE.md 의 [1.2.3 DB & Migration] 체크박스 중 
'0001_init_schemas.py' 와 '0002_ctl_tables.py' 두 개만 먼저 작성해줘.
로컬에서 alembic upgrade head 가 통과하는지 docker-compose 띄워서 확인해.
```

### 2.3 Phase 단위로 명령 (범위가 크면 쪼개게 유도)

```
Phase 1 전체를 한꺼번에 하지 말고, 
1.2.1 → 1.2.2 → 1.2.3 순서로 체크박스 하나씩 끝낼 때마다 커밋하고 나한테 보고해.
```

---

## 3. 작업 크기 고르는 법

Claude는 큰 작업도 처리하지만, **너무 크면 중간에 방향이 틀어졌을 때 되돌리기 비싸다.** 아래 기준을 추천:

| 작업 크기 | 명령 예시 | 언제 쓰나 |
|---|---|---|
| **마이크로 (5~30분)** | "이 함수의 error handling만 고쳐줘" | 버그 수정, 리팩토링 |
| **스몰 (1~3시간)** | "`raw_object` CRUD endpoint 와 테스트 작성" | 체크박스 1~3개 |
| **미디엄 (반나절)** | "Phase 1의 1.2.7 수집 API 전체" | 하위 섹션 1개 |
| **라지 (1일+)** | "Phase 1 전체" | 신중히 — 중간 체크포인트 필수 |

**라지 명령 쓸 때 안전장치:**
```
큰 작업이니까:
1) 먼저 구현 순서 5~7단계로 나눠서 제안해줘
2) 내가 승인하면 그 순서대로 진행
3) 각 단계 완료 후 1~2줄로 보고
4) 예기치 못한 결정이 필요하면 진행 멈추고 물어봐
```

---

## 4. 상황별 명령 템플릿

### 4.1 새 기능 구현

```
[작업] 영수증 업로드 API 추가
[목적] Phase 1의 1.2.7, 모바일에서 영수증 이미지 보낼 endpoint
[파일]
  - backend/app/api/v1/ingest.py  (POST /v1/ingest/receipt 추가)
  - backend/app/domain/ingest.py  (save_receipt 함수)
  - tests/integration/test_ingest_receipt.py
[완료 기준]
  - 10MB 이미지 정상 업로드
  - 같은 Idempotency-Key 재전송 시 dedup=true
  - 비활성 source면 403
[제약]
  - content_hash는 이미 있는 core/hashing.py 사용
  - Object Storage 업로드는 integrations/object_storage.py 사용
  - raw_object + content_hash_index + ingest_job + event_outbox 같은 트랜잭션
```

### 4.2 버그 수정

```
[버그] /v1/jobs 조회 시 source 필터 적용 안 됨
[재현] curl 예시 + 기대 결과 + 실제 결과
[파일 의심] backend/app/api/v1/jobs.py, repositories/jobs.py
[요청] 원인 파악 후 최소 수정 + 회귀 테스트 추가
```

### 4.3 리팩토링

```
[대상] backend/app/domain/standardization.py
[이유] 함수 하나가 200줄 넘어서 테스트 어려움
[범위] 기능 변경 없음. 함수 분리 + 타입 힌트 보강만
[확인] 기존 테스트 그대로 통과해야 함
```

### 4.4 리뷰 요청

```
방금 작성한 backend/app/domain/ingest.py 를 리뷰해줘.
[관점]
  - 트랜잭션 경계 맞는지
  - N+1 쿼리 가능성
  - 에러 처리 누락
[형식] 지적 3~5개, 각자 파일:line 과 수정 제안.
```

### 4.5 학습 요청

```
Airflow의 Sensor 개념을 docs/airflow/LEARNING_GUIDE.md 의 Step 4를 기준으로
우리 프로젝트의 'outbox에 staging.ready 도착 감시' 시나리오로 풀어서 설명해줘.
예제 코드 1개 + 실제 DAG 파일에 넣을 완성본.
```

### 4.6 설계 의견 요청

```
[상황] 표준화 confidence 임계치 0.7~0.95 구간을 어떻게 할지 고민
[옵션] A) 자동반영 + 사후 샘플링  B) 전부 crowd task 생성  C) 신뢰도별 차등
[결정 기준] Crowd 검수 capacity 하루 200건, 전체 수집 10만/일
[요청] 옵션별 장단점 + 추천 + 근거. 2분 안에 읽을 분량.
```

### 4.7 의사결정 로그 (ADR) 요청

```
방금 Airflow LocalExecutor → CeleryExecutor 전환하기로 했어.
docs/adr/0003-airflow-celery-executor.md 로 ADR 파일 만들어줘.
템플릿: 배경 / 결정 / 대안 / 결과 / 영향.
```

### 4.8 막혔을 때 (디버깅)

```
[증상] Docker compose up 시 backend 컨테이너가 healthcheck 실패
[로그] (여기 붙여넣기)
[이미 시도한 것] 1) 포트 충돌 확인 OK  2) .env 확인 OK
[요청] 원인 후보 3가지 + 각 확인 명령어 + 내가 실행할 순서
```

---

## 5. Claude에게 확인받는 습관 (중요)

### 5.1 "먼저 계획 보여줘"

```
이 작업을 하기 전에 3~5줄로 계획만 먼저 보여줘. 
내가 승인하면 그 때 코드 작성 시작해.
```

→ 큰 작업 전 항상 쓰는 걸 추천.

### 5.2 "전에 뭘 알고 있는지 요약해줘"

```
지금 우리 레포 상태를 파악했어? 주요 파일 / 현재 Phase / 최근 작업 내용을 
5줄 이하로 정리해줘. 빠진 맥락 있으면 알려줘.
```

→ 대화 초반이나 세션 재개 시 유용.

### 5.3 "가정을 명시해줘"

```
이 작업에서 네가 한 가정을 모두 나열해줘. 
내가 동의하지 않는 부분만 수정하면 되도록.
```

→ 애매한 요구사항을 구체화할 때.

---

## 6. 피해야 할 명령 (안티패턴)

| 나쁜 명령 | 왜 나쁜가 | 고친 버전 |
|---|---|---|
| "수집 시스템 만들어줘" | 너무 광범위 | "PHASE_1_CORE.md 1.2.7 체크박스 순서대로" |
| "알아서 잘 해줘" | Claude가 가정 남발 | "작업 전 계획을 보여주고 내가 승인하면 진행" |
| "전체 리팩토링해줘" | 범위 무한 | "domain/standardization.py 만, 기능 변경 없이" |
| "테스트도 다 쳐줘" | 커버리지 과다 | "happy path + 1 edge case 만" |
| "에러 나는데 어떡해?" | 정보 부족 | "증상 + 로그 + 시도한 것 + 요청" |
| "DB 스키마 전부 바꿔서 최적화" | 리스크 큼 | "한 테이블씩 마이그레이션 파일로, ADR 작성 후" |

---

## 7. 이 프로젝트의 관습 (Claude가 이해하는 패턴)

다음은 `CLAUDE.md` + `docs/05_CONVENTIONS.md` 에 이미 담겨 있어 **명령에 반복 설명할 필요 없다**:

- Phase 1~3 배포는 Docker Compose, Phase 4에 NKS 이관
- **Phase 1~3에 K8s manifest 만들지 말기** (Phase 4 이관 시 작성)
- 단, 이미지는 "NKS Ready" 규칙 (stateless, healthz/readyz, SIGTERM graceful, env 기반 설정, stdout JSON 로그) 준수
- Kafka는 Phase 4 조건부
- Airflow = 시스템 배치, Visual ETL = 사용자 정의, Dramatiq = 실시간
- DB 스키마 변경은 Alembic migration 파일로만
- 외부 API 호출은 `integrations/` 에서만
- 커밋 메시지는 Conventional Commits
- Mart 쓰기는 APPROVER role만
- raw 보존 필수, content_hash + idempotency_key 2중 방어

**따라서:** 명령에 "Kubernetes 쓰지 마"라고 매번 쓸 필요 없음. Claude가 CLAUDE.md 읽고 알아서 회피한다.

---

## 8. 실전 명령 예시 10개 (복사해서 쓸 수 있음)

```
1) "docs/phases/CURRENT.md 읽고, 지금 우선순위 top-3 알려줘"

2) "PHASE_1_CORE.md 의 1.2.1 'Repo & 환경' 전체를 구현해. 
    docker-compose가 로컬에서 에러 없이 올라가는지까지 확인하고 보고해."

3) "방금 만든 migration 0003_raw_tables.py 를 리뷰해줘. 
    파티션 선언, content_hash_index, GIN 인덱스 3가지만."

4) "Airflow를 처음 써봐. docs/airflow/LEARNING_GUIDE.md Step 2 예제를 
    우리 DB에 붙게 수정해서 hello_dag.py 파일 하나 만들어줘. 
    docker-compose로 띄운 뒤 UI에서 실행까지 확인."

5) "영수증 OCR 결과 confidence < 0.85 면 crowd_task 생성하는 로직, 
    어디에 넣는 게 맞을지 파일 위치 2~3개 후보를 먼저 제안해줘. 
    결정은 내가 할게."

6) "PHASE_2_RUNTIME.md 의 2.2.4 OCR 파이프라인을 계획만 먼저 5단계로 
    쪼개서 보여줘. 구현은 내 승인 후."

7) "pg_partman 말고 직접 파티션 생성 스크립트 쓰는 이유 ADR 만들어줘. 
    docs/adr/0004-manual-partitioning.md 로."

8) "docker compose up 시 worker-ocr 컨테이너가 재시작 루프 돈다. 
    로그 (붙여넣기). 원인 후보 3개 + 각 확인 명령어."

9) "docs/03_DATA_MODEL.md 의 price_fact 테이블에 unit_price_per_kg 컬럼을 
    generated column으로 바꾸는 게 나을지 판단해줘. 
    지금 설계의 장단점 + 변경 시 영향 요약."

10) "지금까지 Phase 1 진척을 체크박스 단위로 요약해줘. 
     완료 / 진행 중 / 미착수 분류로."
```

---

## 9. Claude가 잘 못하는 것 (알고 있으면 좋음)

| 약한 영역 | 대처 |
|---|---|
| **실시간 상태 확인** (사용자 브라우저 화면, UI 애니메이션 등) | 스크린샷 붙여넣기 or 로그 공유 |
| **모호한 디자인 선호** (색상, 레이아웃 미감) | Figma 링크 or 구체적 레퍼런스 |
| **외부 시스템 실시간 검증** (NCP 콘솔, 대시보드 등) | Claude는 제안만, 확인은 사용자 |
| **장기 맥락 유지** (수십 session 이전 작업) | `docs/` 문서 / 메모리 시스템 활용 |
| **대량 데이터 처리 체감 판단** | 실측 수치 전달 + 프로파일링 결과 공유 |

---

## 10. 한 줄 요약

> **"무엇을 / 왜 / 어디에 / 어떻게 확인할지 / 제약" 5가지를 한 메시지에 담되, 이 프로젝트에서는 `docs/` 경로와 체크박스 번호만 짚어줘도 충분하다.**

---

## 11. 세션 시작 시 첫 명령 예시 (붙여넣기 가능)

**새 세션을 시작할 때 다음을 맨 먼저 보내면 Claude가 맥락을 빠르게 잡는다:**

```
프로젝트 맥락:
- 루트: e:\dev\datapipeline
- CLAUDE.md + docs/ 읽고, docs/phases/CURRENT.md 확인해서 
  지금 어느 Phase 에 있는지 파악해줘
- 오늘 할 일은 [여기 목표].
- 작업 전 5줄 이하 계획을 보여주고 내가 승인하면 진행해.
```

---

## 12. 문제 발생 시 에스컬레이션 순서

1. Claude에게 **가정 + 옵션** 질문으로 먼저 던진다.
2. 그래도 애매하면 **비교표** 요청 ("A/B 장단점 5개씩 표로").
3. 그래도 고민되면 **ADR 초안** 요청 ("두 옵션 ADR로 써줘, 결정은 내가").
4. 그래도 결정 안 서면 일단 **프로토타입** 요청 ("최소 구현체로 A와 B 모두 만들어 비교").

---

모르는 명령/상황이 생기면 이 문서를 다시 열어 템플릿 하나 골라 그대로 붙여넣으면 된다. 시간이 가면서 자기만의 명령 스타일이 생길 것이고, 그때 이 문서도 같이 업데이트하면 된다.
