# ADR-0019 — Phase 5 추상화 검증 결과 (POS 도메인 시험지)

- **Status**: ACCEPTED
- **Date**: 2026-04-27
- **Phase**: 5.2.6 STEP 9
- **Author**: Claude / 사용자

---

## 컨텍스트

Phase 5 는 v1 (단일 도메인 = 농축산물 가격) 을 *공용 데이터 수집 운영체제* 로
일반화. 그 추상화 적정성을 검증하기 위해 STEP 9 에서 **POS 거래 로그** 도메인을
*시험지* 로 추가.

검증 가설:
> 새 도메인 추가가 *yaml + migration + seed* 만으로 가능해야 한다 (코드 수정 ≈ 0).
> 4주 초과 시 5.2.5 까지의 generic 화 회귀 분석 + 보강 turn 필요.

---

## STEP 9 진입 결정 (사용자 답변)

| 항목 | 결정 |
|---|---|
| Q1. 새 도메인 | POS 거래 로그 (사업 요청 미정 → 기술 검증 우선 1순위) |
| Q2. 데이터 소스 | mock 데이터 — 실 외부 API 는 Phase 6 |
| Q3. std_code | `payment_method` 중심 7종 + alias 사전 |
| Q4. KPI 측정 | commit timestamp + 실 작업 시간 둘 다 기록 |
| Q5. 4주 초과 시 | STEP 10 진입 금지, generic 화 재검토 |

---

## 추상화 KPI (실측)

| 지표 | 값 |
|---|---|
| 시작 commit | `9a1eef1` (2026-04-26 13:46 KST) |
| 완료 commit | (이 ADR 의 commit) |
| Calendar 시간 | < 1일 (mock 데이터 한정) |
| Engineering 시간 | ~30분 (yaml + migration + alias_lookup + 테스트) |
| 신규 코드 라인 | ~400 (migration 0043) + ~150 (alias_lookup) + ~150 (tests) |
| 신규 yaml 라인 | 47 (`domains/pos.yaml`) |
| `app/` 코드 수정 | 0 (alias_lookup 은 *신규* 모듈) |
| `frontend/` 수정 | 0 |

**평가**: ✅ *1~2주 적정 범위* 통과. 추상화가 새 도메인 (거래 이벤트) 을
받는 데 충분.

---

## 검증 결과 요약

### ✅ 작동한 추상화
1. **`domain.*` registry** — `domain_definition` / `resource_definition` /
   `standard_code_namespace` 가 POS 의 3 자원 + 2 namespace 를 *코드 변경 없이*
   수용.
2. **provider registry** — POS 는 외부 API (Phase 6) 미사용이라 `generic_http`
   provider 를 그대로 사용 가능.
3. **load_policy + sql_guard** — `pos_mart.*` schema 가 sql_guard 의 도메인
   인지 ALLOWED_SCHEMAS 에 자동 추가됨 (sql_guard.SqlNodeContext.domain_code).
4. **cutover_flag** — 새 도메인은 v1 path 가 없으므로 `active_path='v2'` +
   `v1_write_disabled=TRUE` 로 baseline seed (shadow 미적용).
5. **payment_method alias 사전** — 임베딩 미사용. v1 의 3단계 폴백을 *덮어쓰지
   않고* alias-only 경로로 별도 모듈 (`standardization.alias_lookup`) 추가.

### ⚠ 발견된 일반화 부족 (Phase 6 backlog)
1. **resource_definition.fact_table 단독 사용** — POS 는 fact 만 있고 master 가
   별도. 현재 `LOAD_TARGET` 노드는 fact 또는 canonical 둘 중 하나만 자동 선택.
   *둘 다 있는* 경우의 정책 명시 필요 (Phase 6 STEP 11).
2. **std_code alias 등록 인터페이스 부재** — pos.yaml 에 alias 를 직접 적지
   못함. migration SQL 또는 admin UI 만 가능. yaml schema 확장 backlog.
3. **mock 데이터 시드** — migration 안에 `INSERT ... generate_series` 형태로
   직접 작성. 더 큰 도메인은 별도 seed 스크립트 필요 (`scripts/seed_<domain>.py`
   생성 helper).

### ❌ 회수 액션 필요 X
4주 초과 X. 추가 generic 화 turn 불필요.

---

## std_code 매핑 결과 (mock 50건 거래 기준)

`pos_mart.pos_transaction.payment_method_raw` 에 한국어/영어 혼합 5종 raw 값.
`alias_lookup.standardize_column_in_table` 1회 호출 결과:

| matched_via | 건수 |
|---|---|
| std_code (직접) | 0 |
| alias | 5 (신용카드/현금/카카오페이/쿠폰/OK캐쉬백 → 5 표준코드) |
| fallback (OTHER) | 0 |

**커버리지**: 100% (alias 사전이 mock 데이터의 모든 raw 값을 커버).

---

## Phase 6 후속 항목

1. POS 실제 외부 API 연동 (Field Validation phase).
2. yaml schema 확장 — alias 인라인 등록.
3. fact + canonical 동시 적재 정책 (LOAD_TARGET v2).
4. resource 단위 std_code coverage Grafana 대시보드.

---

## 결론

POS 도메인 추가가 *코드 수정 0* 으로 완료됨 — Phase 5.2.5 까지의 generic 화는
통과 판정. STEP 10 (외부 API 도메인 인지) 진입 가능.
