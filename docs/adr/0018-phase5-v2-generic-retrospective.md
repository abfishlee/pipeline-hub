# ADR-0018 — Phase 5 v2 generic 회고 + 추상화 KPI

- **Status**: ACCEPTED
- **Date**: 2026-04-27
- **Phase**: 5.2.9 STEP 12
- **Author**: Claude / 사용자

---

## 결정 (한 줄)

> **Phase 5 의 v2 generic 추상화는 ✅ 통과** — POS 도메인을 *코드 수정 0* 으로 1일
> 미만에 추가 (ADR-0019). 다만 8 개의 *일반화 부족* 항목이 발견됨 → Phase 6 backlog.

---

## 컨텍스트

Phase 5 는 v1 (단일 도메인 = 농축산물 가격) 을 *공용 데이터 수집 운영체제* 로 일반화.
12 STEP 으로 진행:

| STEP | 내용 | commit |
|---|---|---|
| 0 | 사전 준비 체크 | — |
| 1 | Spike (Hybrid ORM) | `94ef1f1` |
| 2 | 가드레일 7종 | `f4f360a` |
| 3 | domain.* schema | `f2ccb0b` |
| 4 | Provider Registry | `297d695` |
| 5 | nodes_v2 13+ | `1c53b73` |
| 6 | (5.2.3 — std generic, STEP 9 와 통합) | `6a2b248` |
| 7 | ETL UX MVP backend | `736ffe6` |
| 8 | v1→v2 shadow + cutover | `9a1eef1` |
| 9 | POS 도메인 ★ | `6a2b248` |
| 10 | multi-domain public API | `df76286` |
| 11 | perf SLO + Coach + Backfill | `b560c36` |
| 12 | onboarding + 본 ADR | (이 commit) |

---

## 추상화 KPI 결과 (Q2 ① — KPI 결과)

### POS 도메인 추가 (STEP 9)

| 지표 | 값 |
|---|---|
| Calendar 일수 | < 1일 (mock 데이터 한정) |
| Engineering 시간 | ~30분 |
| `app/` 코드 수정 라인 | 0 (alias_lookup 은 *신규* 모듈) |
| 신규 yaml 라인 | 47 (`domains/pos.yaml`) |
| 신규 migration | 1 (`0043_pos_mart.py`, ~400 lines) |
| 신규 도메인 모듈 | `app/domain/std_alias.py` (~150 lines) |
| 신규 테스트 | 10 cases |

**평가**: ✅ *1~2주 적정 범위* 통과. **4주 초과 X** → STEP 10 진입 OK.

### Spike 결과 적중률 (Q2 ④)

ADR-0017 의 Hybrid ORM (옵션 C) 결정:
- **예측**: v1 ORM 유지 + v2 generic = SQLAlchemy Core + reflected Table.
- **실제**: 100% 적중. v2 generic 노드 (MAP_FIELDS, LOAD_TARGET, SQL_INLINE) 모두
  Core + `text(...)` + `_validate_ident` 패턴으로 구현. 동적 ORM 클래스 (옵션 A)
  없이 충분.

**Spike 정확도 KPI**: 5 점 만점에 5점.

### v1 → v2 shadow run 결과 (Q2 ⑤, ⑥)

Phase 5 종료 시점에 **agri 의 shadow run 은 아직 실 운영 환경에서 가동 안 됨**
(코드 인프라만 완성). 검증 결과:

| 항목 | 결과 |
|---|---|
| `audit.shadow_diff` 적재 동작 | ✅ unit test 11건 통과 |
| diff_kind 분류 정확도 | ✅ value/row_count/schema/v1_only/v2_only |
| cutover_block 임계 (1%) | ✅ 통과 (10% 시뮬레이션) |
| cutover warning (0.01~1%) | ✅ acknowledge_warning 강제 |
| **false positive 비율** | **TBD** — 실 staging 1주 후 측정 (Phase 5.x 후속) |

**cutover 사고 / near-miss**: 없음 (실 운영 시작 전).

**STEP 8 의 후속 액션**: Phase 6 시작 시 staging 에서 1주 shadow run 실측.

### 성능 SLO 변화 (Q2 ⑦)

Phase 5.2.8 STEP 11 에서 10종 SLO baseline 측정 인프라 신설.
**baseline 값 vs Phase 4 종료 시점 비교는 미수행** — Phase 4 종료 시 SLO 측정이
없었음 (자체적으로 baseline 잡아야 함, ADR-0020 의 reasoning).

→ Phase 6 시작 후 1주일 baseline 수집 → 본 ADR 갱신.

### 운영팀 피드백 (Q2 ⑨)

Phase 5 종료 시점 운영팀 *합류 전*. 본 ADR 작성 시점 = 2026-04-27,
운영팀 6~7명 합류 = 2026-09-01 예정.

피드백 채널 (Phase 6 부터 활성):
- Weekly 운영팀 회의 (`docs/onboarding/04_operations_runbook.md`).
- ADR 별 review comment.
- `audit.access_log` 의 admin 사용 빈도 분석 (대시보드).

---

## 코드 수정 없이 해결된 범위 (Q2 ②)

POS 도메인 추가에서 *기존 코드를 단 한 줄도 수정하지 않고* 동작한 부분:

1. **registry 메타** — `domain.*` 7 테이블이 새 도메인 자동 수용.
2. **sql_guard** — `SqlNodeContext.domain_code` 가 `<domain>_mart` schema 자동
   허용.
3. **provider registry** — `generic_http` provider 가 도메인 무관 재사용 가능.
4. **load_policy** — `append_only` / `upsert` mode 가 도메인 무관 동작.
5. **cutover_flag** — `v2-only` baseline 이 새 도메인 즉시 적용.
6. **public_v2 router** — `/public/v2/{domain}/*` 가 *경로 변수* 만으로 작동.
7. **Mini Publish Checklist** — entity_type='dq_rule' / 'load_policy' 가 도메인 무관.
8. **dry-run** — MAP_FIELDS / LOAD_TARGET / FUNCTION_TRANSFORM 모두 도메인 무관.

---

## 코드 수정이 필요했던 범위 (Q2 ③)

POS 도메인 추가 시점에 *신규 모듈* 형태로 추가된 것 (수정 X, 추가만):

| 영역 | 신규 모듈 | 이유 |
|---|---|---|
| 표준화 alias-only | `app/domain/std_alias.py` | 기존 임베딩 + 3단계 폴백 (`standardization.py`) 와 별개 경로 (Q3 답변) |
| 도메인 yaml | `domains/pos.yaml` | 정적 카탈로그 |
| 도메인 schema | `migrations/versions/0043_pos_mart.py` | DDL 은 alembic 으로 |

→ **0 코드 수정 가설은 통과**. 단, 새로운 표준화 패턴 (alias-only) 이
*Phase 6 의 yaml schema 확장* 으로 정형화되면 더 적합.

---

## 발견된 일반화 부족 → Phase 6 backlog (Q2 ⑩)

ADR-0019 의 *발견된 일반화 부족* 3건 + Phase 5.2.x 전체에서 추가 발견:

1. **resource_definition.fact_table 단독 사용** — POS 는 fact 만, agri 는 fact +
   canonical 둘 다. LOAD_TARGET 의 자동 선택 정책 명시 필요.
2. **std_code alias 등록 인터페이스 부재** — pos.yaml 에 alias 직접 못 적음.
   yaml schema 확장 backlog.
3. **mock 데이터 시드 helper 부재** — 매 도메인 migration 안에 직접
   `INSERT ... generate_series` — 별도 `scripts/seed_<domain>.py` 자동 생성.
4. **shadow run 실측 부재** — staging 1주 가동 후 false positive 측정.
5. **SLO baseline 비교 부재** — Phase 4 종료 시점 측정 없음.
6. **운영팀 피드백 부재** — 합류 후 첫 회고 turn 필요.
7. **Performance Coach UI** — backend 만 STEP 11. UI 는 Phase 6.
8. **8개 ETL UX 후순위** — Lineage / Backfill Wizard / Source Wizard /
   Template Gallery / Error Sample Viewer / Node Preview / Publish Checklist 고도화.

→ `docs/phases/PHASE_6_FIELD_VALIDATION.md` 의 Phase 6 backlog 갱신 (별도 commit).

---

## 회수 액션 (Q2 ⑪)

본 ADR 의 평가 결과 **회수 액션 불필요**. STEP 9 가 4주 내 통과, STEP 10~11 도
정상 완료. Phase 6 진입 가능.

만약 Phase 6 시작 후 다음 신호가 발생하면 회수 turn:

| 신호 | 회수 액션 |
|---|---|
| 새 도메인 추가에 4주+ | STEP 5~7 의 추상화 보강 |
| shadow_diff false positive ≥ 5% | shadow_run 알고리즘 재검토 |
| API key multi-domain 권한 사고 | RLS / scope 가드 강화 |
| Performance Coach 의 BLOCK 비율 ≥ 30% | 임계값 재조정 |
| Kafka 트리거 충족 (ADR-0020) | Kafka 도입 turn |

---

## Phase 6 Field Validation 진입 조건

다음이 모두 충족되어야 Phase 6 시작:

- [x] Phase 5 의 12 STEP 모두 commit + push
- [x] ADR-0017 / 0018 / 0019 / 0020 작성 완료
- [x] onboarding 5종 문서 갱신 (이 commit)
- [ ] 운영팀 6~7명 합류 (2026-09-01 예정)
- [ ] staging 1주 shadow run + 운영팀 첫 회고
- [ ] Phase 6 backlog (PHASE_6_FIELD_VALIDATION.md) 우선순위 합의

진입 후 첫 작업: **사업측이 요청한 새 도메인 1개** 본격 추가 + 실 외부 API 연동.

---

## 결론

Phase 5 의 핵심 가설 ("새 도메인은 yaml + migration + seed 만으로 추가") 이
*POS mock 데이터 한정으로* 검증됨. 실 외부 API + 운영팀 피드백은 Phase 6 에서
완성. 본 ADR 은 *현 시점의 정확한 그림* 이며, Phase 6 종료 시 갱신 ADR-00XX
신설 예정.
