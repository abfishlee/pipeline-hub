# ADR-0009 — Pipeline 버전 관리: DRAFT 유지 + 새 PUBLISHED row

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 3.2.6 — 파이프라인 버전/배포 (도입)

## 1. 컨텍스트

Visual ETL Designer 의 워크플로는 *편집 가능한 DRAFT* 와 *실행 가능한 PUBLISHED* 두
상태가 필요하다. PUBLISH 시점의 그래프는 freeze 되어야 하며, 배포 이력 추적과 diff 비교가
가능해야 한다. 다음 4개 요구가 동시에 있다.

1. **편집 잠금** — PUBLISHED 워크플로의 노드/엣지/config 는 변경 불가. 배포된 그래프가
   사후에 바뀌면 실행 이력 + release 기록의 신뢰성 무너짐.
2. **계속 편집** — 운영자가 PUBLISH 후에도 다음 버전을 위해 계속 편집할 수 있어야 함.
3. **버전 추적** — `(name, version)` 으로 같은 이름 안에서 시간순 정렬. PUBLISHED 간
   diff (added/removed/changed) 표시.
4. **마이그레이션 비용 0** — 기존 (Phase 3.2.1) 의 단순 `transition_workflow_status` 흐름
   에 의존하던 코드/테스트가 깨지지 않게.

## 2. 결정

**DRAFT 는 그대로 두고 PUBLISH 시 *새 PUBLISHED row* 를 만든다. version 은 같은 name
안에서 max+1 자동 증가. 그래프(node/edge) 는 새 row 로 복제 — DRAFT 와 PUBLISHED 가
완전 독립.**

```
[DRAFT v1]   ──PUBLISH──→  [DRAFT v1 그대로] + [PUBLISHED v2 (graph copy)]
                                                      └─→ wf.pipeline_release row
[DRAFT v1 편집]──PUBLISH──→  [DRAFT v1 그대로] + [PUBLISHED v2 그대로] +
                            [PUBLISHED v3 (graph copy)]
                                                      └─→ wf.pipeline_release row
```

원본 DRAFT 의 status 는 절대 변하지 않고, PUBLISH 동작 = 새 row 생성 + nodes/edges 복제
+ release 기록. DRAFT 가 영구히 v1 이라는 점은 운영자가 "다음 PUBLISH 까지의 작업 공간"
으로 자연스럽게 이해.

다음 PUBLISHED 가 등장하면 이전 PUBLISHED 는 그대로 둔다 — version_no 로만 구분, 운영
환경에서 *어떤 PUBLISHED 를 실제로 실행하는지* 는 trigger_run 호출 시 명시적 ID 지정.
일반적으로 가장 최신 PUBLISHED 를 사용하지만, rollback 시 이전 PUBLISHED 를 직접 실행
가능 (Phase 3.2.7 backfill 도 이 ID 지정 정책 위에서 동작).

## 3. 대안

### 대안 A — 같은 row 의 status DRAFT → PUBLISHED in-place 변경
- **흐름:** Phase 3.2.1~3.2.5 까지 사용한 단순한 방식.
- **장점:**
  - 코드 단순. transition_workflow_status 1줄로 끝.
  - workflow_id 가 안정 — frontend route /pipelines/designer/{id} 가 status 변경 후에
    도 같은 ID 유지.
- **기각 사유:**
  - PUBLISH 후 운영자가 같은 워크플로를 더 편집할 수 없음 (PUBLISHED 는 readonly 이라야
    함). "v2 작업하려면 어떻게?" 라는 질문이 즉시 발생.
  - Diff (added/removed/changed) 는 *시점 a 와 시점 b* 의 그래프를 비교해야 하는데
    같은 row 면 시점 a 가 사라짐 (덮어쓰기). 별도 history 테이블 필수 — 결국 본 결정
    (= 새 row) 과 동등 비용.
  - PUBLISHED 인 동안 누가 PATCH 를 시도해 fail 하면 → DRAFT 로 다시 status 전환할
    합당한 흐름이 없음 (배포된 거 다시 풀기).

### 대안 B — DRAFT 와 PUBLISHED 를 같은 name 안에서 둘 다 두되 version 은 일치
- **흐름:** DRAFT v1 → PUBLISH → DRAFT 와 PUBLISHED 둘 다 v1 (둘 다 v2, v3, ...).
- **장점:** 마이그레이션 0.
- **기각 사유:**
  - `(name, version)` UNIQUE 제약 위반. UNIQUE 를 `(name, version, status)` 로 풀면
    같은 (name, v1) 에 DRAFT 1개 + PUBLISHED 1개 + ARCHIVED 다수 — 의미 모호.
  - "v1 의 DRAFT" 가 PUBLISHED 와 다른 그래프를 가질 수 있음 = 사용자 혼란.

### 대안 C — Git-style 브랜치 / 머지 (`branch_id`, `parent_release_id`)
- **장점:** 다중 운영자가 병렬 편집 후 머지 가능.
- **기각 사유 (Phase 3):**
  - 운영팀 합류 전, 1명 사용자 시점에서 다중 브랜치 가치 0.
  - Conflict 해결 UI 가 추가 — 6주 일정 추정. Phase 3 7주 안에 못 넣음.
  - **재평가 트리거 (Phase 4):** 운영팀 6~7명이 같은 워크플로를 동시 편집하는 상황 발생
    + 머지 충돌 빈도가 주 1회 이상.

## 4. 결과

**긍정적:**
- DRAFT 가 워크플로의 *living spec* 이라는 모델이 명확. 사용자가 PUBLISH 하면 *snapshot*
  하나 떴다는 직관 그대로.
- `wf.pipeline_release` 가 매 PUBLISH 의 그래프 스냅샷 + 변경 요약 (added / removed /
  changed) 동봉 — 사후 회고에 충분.
- 한 번 PUBLISHED 된 그래프는 쿼리 / 트리거 / backfill / 재실행 모두 그 freeze 된 ID
  로 안전.
- ADR-0007 의 React Flow 캔버스 그대로 — 같은 page 가 PUBLISHED 진입 시 readonly 자동
  전환만 한다.

**부정적:**
- workflow_id 가 PUBLISH 마다 바뀜 — Designer 페이지가 PUBLISH 후 새 ID 로 redirect
  필요 (3.2.6 commit 에서 이미 처리). bookmark 는 끊김.
- 같은 name 의 워크플로 row 가 시간이 지나면 누적 (v1 DRAFT + v2..vN PUBLISHED). 정리
  정책 = ARCHIVED 전환 (오래된 PUBLISHED) 정도. 수백 버전 누적 시 list API 가 성능
  영향 — 인덱스 `wf_workflow_status_idx` 로 완화, 추가 시점에 partition 검토.
- 그래프 복제 비용 — 100 노드면 100 INSERT + 200 INSERT (edges) ~ 수백 ms. 매 PUBLISH
  마다 발생. 본 단계 트래픽에서 무시 가능.

**중립:**
- DRAFT 가 영구히 v1 (운영자가 다음 PUBLISH 마다 새 PUBLISHED 의 v 만 증가) — *왜 DRAFT
  는 항상 v1 인가* 라는 물음이 운영팀 합류 후 자주 등장 가능. 답: "DRAFT 는 살아 있는
  스펙, 버전 표시는 PUBLISH 시점에 freeze 된 PUBLISHED row 에만 부여." → 합류 자료에
  명시.

## 5. 검증

- [x] PUBLISH 시 새 PUBLISHED row 생성 + version max+1 — `tests/integration/test_pipeline
  _release.py::test_publish_creates_new_workflow_with_incremented_version`
- [x] 두 번째 PUBLISH 가 v3 + diff 정확 — `test_second_publish_increments_version_and_
  diffs_against_prev`
- [x] 빈 워크플로 PUBLISH 거부 (409) — `test_publish_empty_workflow_rejected`
- [x] diff API: 노드 추가 / config 변경 / 엣지 추가 — `test_diff_endpoint_against_published`
- [x] 이력 list/detail 의 nodes_snapshot/edges_snapshot 동봉 — `test_releases_listing
  _filtered_by_name`
- [x] Designer PUBLISH 후 새 PUBLISHED 워크플로로 자동 redirect — Frontend 시연

## 6. 회수 조건 (= 다른 모델로 마이그 트리거)

- 운영팀 합류 후 *다중 운영자 병렬 편집* 이 잦아 conflict 가 주 1회 이상 → Git-style
  브랜치 / 머지 (대안 C) 추가 ADR.
- 같은 name 누적이 1k 이상 row 로 list 응답 P95 > 1s → ARCHIVED 정책 자동화 + 오래된
  PUBLISHED 압축 (snapshot 만 남기고 nodes/edges 삭제 가능 — release.{nodes,edges}_
  snapshot 이 이미 보존).
- 그래프 복제 비용이 P95 > 2s → COPY ... TO ... + INSERT FROM 으로 일괄.

## 7. 참고

- `migrations/versions/0019_pipeline_release.py` — release 이력 + snapshot 컬럼.
- `backend/app/domain/pipeline_release.py` — publish_workflow / compute_diff.
- `backend/app/api/v1/pipelines.py` — PATCH /status 에서 release 흐름 분기.
- `frontend/src/pages/PipelineReleases.tsx` — 이력 표 + 색상 블록.
- ADR-0007 (React Flow 캔버스) — diff 표시 시 같은 캔버스 위 색상 오버레이로 확장 가능.
