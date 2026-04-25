# ADR-0006 — Crowd Task Placeholder (Phase 2) vs 정식 검수 (Phase 4)

- **Status:** Accepted
- **Date:** 2026-04-25
- **Deciders:** abfishlee + Claude
- **Phase:** 2.2.4 (도입) / 2.2.10 (운영자 화면) — 결정·검증

## 1. 컨텍스트

OCR / 표준화 / price_fact 단계에서 confidence 가 임계 미만이면 사람이 직접 검토해야
한다. 이 검토 흐름은 다음 세 가지 요구를 동시에 만족해야 한다.

1. **빠른 도입** — Phase 2 에서 자동 파이프라인이 confidence 미달 row 를 만나면
   *어딘가에 안전하게 보관* 해야 한다. 그러지 않으면 mart.price_fact 에 잘못된
   매핑이 흘러 들어가거나 raw 데이터가 사라진다.
2. **정식 검수 UI 는 Phase 4** — 운영팀 6~7명 합류 후 정식 워크플로(이중 검수,
   업무 분배, 통계, SLA)를 갖춘 Crowd 모듈을 만든다.
3. **마이그레이션 부담 최소화** — Phase 4 에서 정식 모듈을 만들 때 Phase 2 에 쌓인
   row 들이 자연스럽게 이관되어야 한다.

이 세 요구를 동시에 만족하는 설계가 필요하다.

## 2. 결정

**Phase 2 = `run.crowd_task` placeholder 테이블** + **운영자 화면(2.2.10)** 으로
안전 격리만 보장. **Phase 4 = `crowd.*` 독자 schema 로 분리** 하면서 Phase 2 row 를
이관.

### Phase 2 설계 (placeholder)

```sql
CREATE TABLE run.crowd_task (
    crowd_task_id  BIGSERIAL PRIMARY KEY,
    raw_object_id  BIGINT NOT NULL,
    partition_date DATE NOT NULL,
    ocr_result_id  BIGINT,
    reason         TEXT NOT NULL,           -- 'ocr_low_confidence' / 'std_low_confidence' /
                                            -- 'price_fact_low_confidence' / 'price_fact_sample_review'
    status         TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING/REVIEWING/APPROVED/REJECTED
    payload_json   JSONB NOT NULL DEFAULT '{}',
    assigned_to    BIGINT REFERENCES ctl.app_user(user_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at    TIMESTAMPTZ,
    reviewed_by    BIGINT REFERENCES ctl.app_user(user_id)
);
```

기능 한정:
- 자동 파이프라인이 미달 row 를 만나면 placeholder INSERT.
- 운영자 화면(`/v1/crowd-tasks`, `frontend/CrowdTaskQueue`)에서 status 전이 마킹.
- **승인/반려는 placeholder** — Phase 4 에서 비즈니스 결과(mart 재반영, alias 추가) 로
  연결됨. Phase 2 의 toast 는 명시적으로 "Phase 4 정식 검수에서 활성화" 안내.

`run.*` 스키마에 둔 이유:
- 자동 파이프라인의 *runtime artifact* 라는 의미가 강함 (이벤트 outbox, dead_letter
  와 같은 위치).
- 별도 schema 신설 없이 기존 권한/migration 정책 재사용.

### Phase 4 정식 검수 (예정 — `docs/phases/PHASE_4_ENTERPRISE.md`)

```
crowd.task               -- 검수 단위 (run.crowd_task 와 1:1, schema 만 이동)
crowd.task_assignment    -- 다중 검수자 배정 + 할당 시각 + dueline
crowd.review             -- 검수자 1인의 결정 (이중 검수)
crowd.task_decision      -- 합의 결과 + 비즈니스 효과 (alias 추가, std_code 변경, ...)
crowd.payout             -- 검수 보상 (외주 사용 시)
crowd.skill_tag          -- 검수자 전문 분야 태깅 (식품/POS/IoT 등 v2 도메인 분기)
```

마이그레이션 경로:
1. `crowd.task` 신설 + `run.crowd_task` 의 모든 row 를 `INSERT INTO crowd.task SELECT ...`
2. 기존 `run.crowd_task` 는 `crowd.task` 로 view 재생성 (FK 호환).
3. 다음 메이저 release 에서 `run.crowd_task` view 폐지.
4. ADR-0010 (Phase 4) 에서 마이그레이션 정확한 SQL 기록.

## 3. 대안

### 대안 A — 정식 Crowd 모듈 처음부터
- **장점**: 추후 마이그레이션 0.
- **기각 사유**: 운영팀 합류 전이라 진짜 검수 흐름의 요구사항(이중 검수, SLA, 보상)
  이 정해지지 않은 상태. *일찍 한 추상화는 잘못된 추상화*. Phase 4 에서 운영팀이
  실제 검수해보고 나서 모델을 짜야 함.

### 대안 B — DLQ 에 통합
- **장점**: 기존 `run.dead_letter` 인프라 재사용.
- **기각 사유**: DLQ 는 *실패한 메시지* 이고 Crowd 는 *성공했지만 confidence 부족*
  이라 의미가 다름. Phase 4 에서 정식 분리할 때 한쪽으로 합쳐 놓은 row 를 떼어내는
  비용이 큼.

### 대안 C — 별도 `crowd.*` schema 를 Phase 2 에서 미리 신설
- **장점**: 마이그레이션 0.
- **기각 사유**: schema 만 만들고 비즈니스 로직은 비어 있는 상태가 6개월 가량
  지속됨. 다른 개발자(운영팀)가 들어오면 "왜 비어 있나" 의문 발생. Phase 가 스키마
  와 함께 진행되도록 명시적 placeholder 가 더 명확.

## 4. 결과

**긍정적:**
- Phase 2 자동 파이프라인이 confidence 미달 데이터를 안전하게 격리. mart 오염 0.
- 운영자 화면(2.2.10) 으로 *현재 큐가 얼마나 쌓였는지* 매일 확인 가능.
- Phase 4 마이그레이션 경로가 단순 (run.crowd_task → crowd.task 1:1 SQL).
- ADR-0003 의 outbox 패턴과 결합 — `crowd.task.created` outbox 도 같이 발행되므로
  Phase 4 가 stream 소비자만 추가하면 됨.

**부정적:**
- 운영자가 "승인/반려 버튼이 placeholder" 라는 점을 알아야 함 — toast 로 명시 + ADR
  링크. 학습 비용 ~5분.
- `run.crowd_task` 의 schema 위치가 Phase 4 에서 이동 → migration 시 view/synonym
  로 호환 한 release 유지 필요.

**중립:**
- 통계 (검수자별 처리량, reason 별 분포) 는 Phase 4 정식 모듈에서 추가. Phase 2 의
  단순 SELECT 로도 충분히 운영 가능.

## 5. 검증

- [x] Migration `0011_crowd_task` — `run.crowd_task` + 인덱스(PENDING partial /
  raw_object 추적 / BRIN created_at)
- [x] 4개 reason 모두 적재 가능 — Phase 2.2.4 (ocr_low_confidence), 2.2.5
  (std_low_confidence), 2.2.6 (price_fact_low_confidence / sample_review)
- [x] `tests/integration/test_crowd_api.py` (5건) — list filter / detail / 정상 전이
  / 잘못된 전이 4xx / VIEWER 차단
- [x] 운영자 화면 — `/crowd-tasks` (status 탭, reason 필터, 상세 패널, placeholder
  버튼) — Phase 2.2.10
- [ ] Phase 4 마이그레이션 SQL 작성 + 회귀 — Phase 4 진입 시점

## 6. 회수 조건

- 운영팀 합류 후 검수 큐가 수천 단위로 쌓이면서 placeholder 한계 노출 (할당/SLA/
  통계 부재) → ADR-0010 작성 후 정식 모듈 가속 도입
- 마이그레이션 비용이 예상 (1주) 보다 크면 — Phase 4 에서 schema 분리 대신 `run.
  crowd_task` 를 그대로 두고 컬럼만 추가하는 방향 재검토

## 7. 참고

- `migrations/versions/0011_crowd_task.py` — placeholder DDL
- `backend/app/api/v1/crowd.py` — list/detail/status 전이 API
- `frontend/src/pages/CrowdTaskQueue.tsx` — 운영자 화면
- `docs/phases/PHASE_4_ENTERPRISE.md` — 정식 Crowd 모듈 (Phase 4)
- ADR-0003 — Outbox + content_hash (검수 결과를 mart 에 반영하는 경로)
- ADR-0005 — 표준화 3단계 매칭 (이 ADR 의 폴백 동작이 본 ADR 의 placeholder 로 흐름)
