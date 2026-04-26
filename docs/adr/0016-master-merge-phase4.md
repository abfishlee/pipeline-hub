# ADR-0016 — Multi-source product 머지 (Phase 4.2.8)

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.2.8 (도입), 4.2.1 (Crowd) 와 결합

## 1. 컨텍스트

여러 유통사 (마트/SSM/로컬푸드) 가 같은 *상품* 을 각자의 product_code 로 등록 →
mart.product_master 에 동일 std_code + 유사 weight_g/grade 인 row 가 *N개* 생성.
같은 상품인데 row 가 분산되면:

1. 가격 비교 시 *같은 상품의 평균* 을 못 보여줌 (n+1 row 별로 보임).
2. Public API `/public/v1/products` 응답이 중복으로 가득 차서 사용자가 어떤 row 를
   택해야 할지 모호.
3. mart.product_mapping 의 정합성 — 같은 retailer_product_code 가 서로 다른
   product_id 에 묶여 추적 어려움.

요구:
- *자동 수렴* — 명백히 동일한 상품은 자동 머지 (운영자 개입 0).
- *분쟁 시 사람 검수* — 다수결이 분명하지 않으면 Crowd 작업 (PRODUCT_MATCHING).
- *un-merge 가능* — ADMIN 이 잘못된 머지 되돌리기.

## 2. 결정

### 핵심 결정 1 — 클러스터링 + 다수결 + 임계 기반 분쟁 분기

```
같은 std_code 안에서:
  cluster = (grade, package_type, sale_unit_norm) 동일 + weight_g ±5%
  cluster 의 row >= 2 → 머지 후보
  
머지 결정:
  - target = mapping count 가 가장 많은 product (tie 시 product_id 큰 쪽)
  - canonical_name = 다수결 (count 기반, tie 시 target 의 이름)
  - grade/package_type/sale_unit_norm/weight_g = 다수결
  - confidence_score = max
  
분쟁:
  - cluster row >= 5 (운영자가 개별 판단 필요한 규모)
  - 또는 grade 다수결 비율 < 50% (명확한 다수가 없음)
  → run.crowd_task (reason='PRODUCT_MATCHING') 자동 발급
```

### 핵심 결정 2 — `mart.master_merge_op` 신설 (별도 테이블)

- 기존 `mart.master_entity_history` 는 *행 단위 SCD2* — 한 entity 의 시간축 변경 이력.
- 머지 작업 1건은 *N→1 변환* 으로 SCD2 와 패턴이 다름.
- 별도 테이블에 `source_product_ids JSONB` + target_product_id + un-merge 메타 (is_unmerged,
  unmerged_at, unmerged_by) 보관.

### 핵심 결정 3 — product_mapping 의 product_id 만 UPDATE, retailer_product_code 보존

- 머지 시 `UPDATE mart.product_mapping SET product_id = target WHERE product_id = ANY(sources)`.
- retailer_product_code 는 그대로 — 어떤 retailer 가 어떤 코드로 등록했었는지 이력 유지.
- source product_master row 만 DELETE.

### 핵심 결정 4 — Un-merge 는 *새 product_id* 부여 (원본 id 미복원)

- merge 시 source product 의 product_id 는 DELETE 됨 → 다시 INSERT 해도 *동일 id 보장
  불가* (sequence 가 이미 진행).
- Un-merge 는 *원본 id 보존이 아닌 새 id 로 재등록* + master_merge_op.is_unmerged=true.
- Un-merge 후 product_mapping 재배치는 운영자가 수동으로 (Phase 4.2.8 PoC). 자동
  재배치는 머지 시점에 *어떤 mapping 이 어떤 source 였는지* 의 snapshot 컬럼이 필요
  — 후속 ADR.

### 핵심 결정 5 — Airflow DAG 는 stub, 운영자가 직접 실행

- `master_merge_daily.py` 는 후보 std_code 개수만 계산 + Slack 알람.
- 실제 자동 머지는 운영자가 `/v1/admin/master-merge/run` 호출 (또는 frontend 버튼).
- 자동 cron 실행 트리거를 도입하려면 *분쟁 임계 보수적 설정 + dry-run 1주 후 자동화*.

## 3. 대안

### 대안 A — 임베딩 cosine 유사도 단독

- **장점**: HyperCLOVA Studio Embedding (Phase 2.2.5) 재사용. 의미 기반 유사 → 표기
  차이 (예: "사과 1.5kg" vs "사과 1.5kg(특)") 흡수 가능.
- **기각 사유 (PoC)**: cosine 임계는 *상품 카테고리별로 다름* — 단일 임계로는 false
  positive/negative 폭증. 본 ADR 의 *카테고리 + 다수결 + ±5% weight* 가 더 명확한
  결정 기준.
- **재평가 트리거**: 본 결정의 자동 머지율이 60% 미만이면 임베딩 단계 추가.

### 대안 B — Probabilistic record linkage (Fellegi-Sunter)

- **장점**: 이론적 기반 강. 각 매칭 차원 (이름/무게/등급) 의 weight 를 EM 추정.
- **기각 사유**: 운영자가 모델 재학습 부담. PoC 단계는 *deterministic 규칙* 이 디버깅
  용이.

### 대안 C — Crowd 만 사용 (자동 머지 없음)

- **장점**: 사람이 100% 결정 → 사고 0.
- **기각 사유**: 운영팀 6~7명에 std_code 5,000+ 매트릭스는 처리 불가. 자동 머지로
  *명확한 케이스* 를 걸러내고, *분쟁만 사람* 이 최적.

## 4. 결과

**긍정적**:
- mart.product_master 의 row 수 감소 → Public API 응답 중복 제거.
- 분쟁만 Crowd 로 보내 운영팀 부담 최소.
- master_merge_op 가 *변경의 단위* 로 보존 → un-merge 가능.

**부정적**:
- weight_g ±5% 는 *과일/채소* 같이 변동 큰 카테고리에선 false positive 위험.
  카테고리별 tolerance 맵으로 후속 개선 (ADR § 6).
- Un-merge 시 product_mapping 재배치가 자동이 아님 — 운영자가 frontend 에서 수동
  처리. snapshot 컬럼 도입 필요.
- 머지된 product 의 mart.master_entity_history 가 *target 만* 갱신 → source 의 history
  는 끊김. master_entity_history 에 merge_op_id 컬럼 추가 검토 (후속).

**중립**:
- Crowd 작업은 같은 std_code 의 미해결 작업이 있으면 중복 발급 X — 운영자가 한 번에
  처리.

## 5. 검증

- [x] migration `0029_master_merge.py` — `mart.master_merge_op` 신설.
- [x] `app/domain/master_merge.py` — find_merge_candidates / attempt_auto_merge /
  run_daily_auto_merge / unmerge_op + 분쟁 임계 (5+ row 또는 grade 다수결 < 50%).
- [x] `app/api/v1/master_merge.py` — ADMIN/APPROVER 의 candidates / run / ops /
  unmerge.
- [x] `infra/airflow/dags/master_merge_daily.py` — 매일 03:00 KST 후보 알람 (실행은
  수동).
- [x] frontend `MasterMergePage.tsx` + `api/master_merge.ts` — 후보 + 머지 이력 +
  un-merge.
- [x] `tests/integration/test_master_merge.py` 5 케이스: 동일 std_code 3 product
  자동 머지 / 5+ row 분쟁 → crowd / grade 다수결 < 50% 분쟁 → crowd /
  product_mapping 의 retailer_product_code 보존 / un-merge 새 product_id 발급.

**Acceptance 충족 확인**:
- 같은 std_code 의 product 3개 (호환되는 grade/weight) → 자동 머지 → 1개 ✅
- product_mapping.retailer_product_code 모두 보존 + product_id 가 target 으로
  통합 ✅
- ADMIN 의 unmerge 버튼 → 새 product_id 발급 + master_merge_op.is_unmerged=true ✅

## 6. 회수 조건

다음 *어떤 것* 이라도 발생하면 후속 ADR + 모델 변경:

1. **자동 머지율 < 60%** — 분쟁율이 너무 높아 Crowd 부담 → 임베딩 cosine 추가
   (대안 A 재평가).
2. **카테고리별 tolerance 차이 큼** — weight_g ±5% 가 과일에 부적합 → category × ±%
   매트릭스 도입.
3. **Un-merge 빈도 높음** — 머지 결정이 잘못되는 경우가 많으면 자동 머지 임계를
   더 보수적으로 (10+ row 만 분쟁 외에는 명확).
4. **product_mapping snapshot 요구** — un-merge 후 mapping 자동 재배치 필요 →
   master_merge_op 에 mapping_snapshot JSONB 컬럼 추가.

## 7. 참고

- `migrations/versions/0029_master_merge.py` — 스키마.
- `backend/app/domain/master_merge.py` — 도메인 로직.
- `backend/app/api/v1/master_merge.py` — ADMIN/APPROVER 라우트.
- `backend/app/models/mart.py` — `MasterMergeOp` ORM.
- `infra/airflow/dags/master_merge_daily.py` — 매일 03:00 KST 알람 DAG.
- `frontend/src/pages/MasterMergePage.tsx` — 후보 / 이력 / un-merge UI.
- `tests/integration/test_master_merge.py` — 5 케이스 회귀.
- ADR-0006 (HyperCLOVA Embedding) — 대안 A 재평가 시 재사용.
- Phase 4.2.1 ADR (Crowd 정식) — PRODUCT_MATCHING reason 의 표준화 주체.
