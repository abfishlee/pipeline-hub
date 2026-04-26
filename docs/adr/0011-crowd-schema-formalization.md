# ADR-0011 — Crowd 검수 정식 (Phase 4.2.1) + run.crowd_task → view 호환

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 4.2.1 (도입). Phase 2.2.4 의 ADR-0006 (Crowd Placeholder) 후속.

## 1. 컨텍스트

ADR-0006 (Phase 2) 에서 `run.crowd_task` 를 *placeholder* 로 두고 Phase 4 에서 정식화
하기로 결정. Phase 4.2.1 진입 시점의 요구:

1. **이중 검수** — priority ≥ 8 (예: 가격이 평균의 5σ 벗어나는 이상치 / 영수증 PII 의심
   keyword) 인 task 는 2명 검수자의 review 가 모두 도착해야 합의.
2. **충돌 해결** — 두 검수자 결정이 다르면 관리자 (ADMIN/APPROVER) 가 결론.
3. **outbox 발행** — 합의된 task 는 mart 자동 반영 — Phase 4.2.2 의 worker 가 outbox
   소비.
4. **운영자 통계** — 건수 / 평균 처리 시간 / 충돌률 / 회귀 오류율.
5. **회귀 0** — Phase 2.2.10 의 운영자 화면이 마이그 후에도 동작 (6개월간 호환 보장).

## 2. 결정

### 2.1 새 schema `crowd.*` 신설 + 6 테이블

| 테이블 | 책임 |
|---|---|
| `crowd.task` | 검수 단위. status (PENDING/REVIEWING/CONFLICT/APPROVED/REJECTED/CANCELLED), task_kind (8종), priority (1~10), requires_double_review |
| `crowd.task_assignment` | 다중 검수자 배정. due_at + released_at |
| `crowd.review` | 검수자 1인의 결정. decision (APPROVE/REJECT/SKIP), comment, time_spent_ms |
| `crowd.task_decision` | 합의 결과. consensus_kind (SINGLE/DOUBLE_AGREED/CONFLICT_RESOLVED) + effect_payload |
| `crowd.payout` | 검수 보상 (외주 시) |
| `crowd.skill_tag` | 검수자 전문 분야 태깅 (식품/POS/IoT…) |

추가로 `ctl.reviewer_stats` (cache 테이블) — 일별 갱신.

### 2.2 마이그 정책 — `run.crowd_task` → VIEW 호환

```sql
-- migration 0022:
CREATE SCHEMA crowd;
CREATE TABLE crowd.task (...);  -- + 5 다른 테이블
INSERT INTO crowd.task SELECT ... FROM run.crowd_task;  -- 데이터 복제
INSERT INTO crowd.task_assignment / crowd.review / crowd.task_decision (변환)

DROP TABLE run.crowd_task;
CREATE VIEW run.crowd_task AS
  SELECT crowd_task_id, raw_object_id, partition_date, ocr_result_id,
         task_kind AS reason, status_mapped AS status, payload AS payload_json, ...
    FROM crowd.task t LEFT JOIN crowd.task_decision d ON ... ;
```

view 는 SELECT 만 허용 — Phase 2.2.10 의 ORM 쿼리 (`select(CrowdTask)`) 그대로 동작.
PATCH `/v1/crowd-tasks/{id}/status` 는 *legacy router* 가 신규 `crowd_review` 도메인으로
위임:

```
PATCH /v1/crowd-tasks/{id}/status {status: APPROVED}
   ↓
crowd_review.submit_review(reviewer_user_id, "APPROVE")
   ↓
crowd.review INSERT + (단일 검수) crowd.task_decision INSERT + outbox 발행
```

호출자 (Phase 2.2.10 운영자 화면 + 외부 스크립트) 입장에선 **응답 형태 / 동작 동일**.

### 2.3 이중 검수 정책

`requires_double_review = (priority >= 8) OR (task.requires_double_review = TRUE)`.

- **단일 검수**: 1 review 도착 시 즉시 task_decision (consensus=SINGLE).
- **이중 검수 1번째 도착**: review row 만, task.status=REVIEWING 유지.
- **이중 검수 2번째 일치**: task_decision (consensus=DOUBLE_AGREED).
- **이중 검수 2번째 불일치**: task.status=CONFLICT, 관리자 처리 대기.
- **CONFLICT 해결**: ADMIN/APPROVER 가 final_decision 지정 → consensus=CONFLICT_RESOLVED.

### 2.4 outbox payload

`crowd.task.decided` event 의 effect_payload 는 task_kind + final_decision 조합으로
*어떤 비즈니스 효과* 를 줘야 하는지 명시:

```json
{
  "action": "promote_ocr_to_mart" | "add_alias" | "promote_price_fact" |
            "rollback_stg" | "approve_generic",
  "ocr_result_id": ..., "std_record_id": ..., "raw_object_id": ...
}
```

Phase 4.2.2 의 mart 반영 worker 가 본 페이로드를 보고 분기.

## 3. 대안

### 대안 A — `run.crowd_task` 컬럼 ADD (현 위치에서 확장)
- **장점:** view 우회 비용 0, 마이그 단순.
- **기각 사유:**
  - reason / payload_json / assigned_to / reviewed_by 가 *단일 row* 모델이라 이중
    검수 표현 불가. 별 테이블 필요.
  - schema 위치 — `run.*` 은 *runtime artifact* (outbox / dead_letter / pipeline_run)
    의미. Crowd 는 별 도메인이므로 schema 분리가 자연스러움 (ADR-0006 § 5 의 "crowd
    .* 으로 이동" 약속).

### 대안 B — Drop `run.crowd_task` 즉시 + 클라이언트 코드 마이그
- **장점:** 깔끔.
- **기각 사유:**
  - Phase 2.2.10 의 frontend `CrowdTaskQueue` 가 Phase 4.2.1 의 정식 화면과 *공존* —
    legacy 화면을 즉시 교체하면 운영자가 새 UI 학습 + 마이그 같은 시점에 두 가지 변경.
  - Phase 4.2.2 의 mart 반영 worker 가 정착할 때까지는 Phase 2.2.10 화면이 *임시 마지노선*.
  - **6개월 호환 → Phase 5 진입 시점에 view 제거** 가 안전한 트랜지션.

### 대안 C — Event Sourcing (모든 review 가 이벤트, task 는 view)
- **장점:** lineage 완벽, replay 가능.
- **기각 사유:**
  - 이벤트 + projection 인프라 추가. Phase 4.2.2 mart 반영 worker 도 event projection 으로
    바뀌어야 함. 4-6주 추가 일정.
  - 본 phase 의 가치 (이중 검수 + 합의 + outbox) 는 일반 row 모델로 충분.

## 4. 결과

**긍정적:**
- Phase 2.2.10 운영자 화면이 *변경 0* 으로 동작 (legacy router + view + PATCH 위임).
- 이중 검수 + 합의 + CONFLICT 해결 흐름이 단일 도메인 (`crowd_review`) 에 깔끔히 캡슐.
- outbox 패턴 (ADR-0003) 그대로 활용 — Phase 4.2.2 mart 반영 worker 가 별도 인프라 없이
  consume.
- 검수자 통계 (`ctl.reviewer_stats`) 가 별도 cache — 매번 SELECT 부담 없음.

**부정적:**
- view 는 INSERT/UPDATE 안 됨 — legacy router 의 PATCH 가 sync session + domain 호출
  로 우회. async session 호출자(2.2.10 화면) 입장에선 latency +30~50ms (sync thread
  offload).
- crowd schema 가 6 테이블 → ORM model 정의 늘어남 + relationship 관리 비용. 단순한
  task 1 row 모델 대비 *복잡한 동시성 시나리오* 로 가는 비용.
- 이중 검수에서 같은 reviewer 가 두 번 review 시도 → unique constraint 로 막음. 운영자
  실수 빈도 1주 1건 가정.

**중립:**
- task_kind 8종은 Phase 5 generic 화 시 도메인 별 task_kind 로 늘어날 가능성. 그 시점
  에서 *task_kind 가 namespace + name* 형태 (`agri:OCR_REVIEW` / `iot:ANOMALY_CHECK`) 로
  분리 — 본 ADR 의 마이그 패턴 그대로 적용.

## 5. 검증

- [x] `migrations/versions/0022_crowd_schema.py` — 6 테이블 + run.crowd_task → view.
- [x] `backend/app/models/crowd.py` — 7 ORM (TaskAssignment / Review / TaskDecision /
  Payout / SkillTag + ReviewerStats in ctl).
- [x] `backend/app/domain/crowd_review.py` — 이중 검수 상태머신 + 합의 + outbox.
- [x] `backend/app/api/v1/crowd.py` — legacy_router (Phase 2.2.10 호환) + router (4.2.1
  정식). main.py 에서 둘 다 등록.
- [x] `frontend/src/pages/CrowdTaskQueue.tsx` — V4 탭 신설 (status 5 tab + reviewer 통계
  + V4 detail panel + CONFLICT resolve UI).
- [x] `tests/integration/test_crowd_review.py` — lifecycle / 이중 검수 / 충돌 / outbox.
- [ ] Phase 4.2.2 의 mart 반영 worker 도입 시 outbox event consume 검증.
- [ ] Phase 5 진입 시점 (run.crowd_task view 제거 + crowd schema 도메인 namespace 분리).

## 6. 회수 조건

다음 *어떤 것* 이라도 발생하면 본 ADR 후속 (예: ADR-0011.A) 로 모델 변경:

1. **이중 검수 비율 > 50%** — 모든 task 가 사실상 이중 검수 → 정책 단순화 (priority 임계
   재조정 또는 항상 이중).
2. **CONFLICT 해결 비율 > 20%** — 두 검수자 의견이 자주 다름 → 표준화 가이드 / 검수자
   skill_tag 매칭 강화.
3. **outbox event 적체** — Phase 4.2.2 worker 가 task.decided event 를 1초 안에 처리
   못 하면 — Redis Streams 기반 별 queue 로 분리.
4. **legacy router 사용 0%** — 6개월 후 Phase 5 진입 시점에 legacy_router + view 제거.

## 7. 참고

- ADR-0003 (Outbox + content_hash) — outbox 패턴 정합.
- ADR-0006 (Crowd placeholder) — Phase 2 결정 + 본 ADR 의 출발점.
- `migrations/versions/0022_crowd_schema.py` — 마이그 SQL.
- `backend/app/domain/crowd_review.py` — 이중 검수 상태머신.
- `backend/app/api/v1/crowd.py` — legacy + v4 router.
- `frontend/src/pages/CrowdTaskQueue.tsx` — V4 화면.
- `docs/phases/PHASE_4_ENTERPRISE.md` 4.2.2 — DQ 게이트 + 승인 (outbox consumer 와 결합).
