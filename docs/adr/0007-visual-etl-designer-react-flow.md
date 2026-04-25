# ADR-0007 — Visual ETL Designer 캔버스로 React Flow 12 채택

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** abfishlee + Claude
- **Phase:** 3.2.4 — Visual Designer 프론트 (도입), 3.2.6 — 배포 이력 (확장 검증)

## 1. 컨텍스트

Phase 3 의 Visual ETL Designer 와 PipelineRunDetail 화면 모두 "노드+엣지 DAG" 를
브라우저에서 그리고 보여줘야 한다. 다음 요구가 동시에 있다.

1. **편집** — drag-and-drop 추가 / `onConnect` 엣지 연결 / `onNodesChange` 위치 변경
   감지 + 백엔드 PATCH.
2. **상태 표시** — 같은 그래프 위에 NodeRun status (PENDING/READY/RUNNING/SUCCESS/
   FAILED/SKIPPED/CANCELLED) 색상 오버레이.
3. **100 노드 규모** — Phase 3 비기능 목표 1초 이내 렌더 (DoD 3.4).
4. **타입 안정성** — TypeScript strict + Pydantic-generated 타입과 정합 — 노드
   data slot 에 `node_key/node_type/config_json` 을 얹어야 한다.
5. **번들 크기** — 현재 frontend 전체 gzip ~180KB. DAG 라이브러리가 +50KB 이상이면 부담.

## 2. 결정

**`@xyflow/react` (구 React Flow) v12 채택. 기본 nodeTypes 사용 + custom data slot 으로
도메인 데이터 얹는 패턴.**

- Designer (`pages/PipelineDesigner.tsx`) — `useNodesState` / `useEdgesState` hook +
  `<NodePalette>` drag → `screenToFlowPosition` 으로 좌표 변환 → `addEdge` 로 연결.
- 상태 색상 (`pages/PipelineRunDetail.tsx`) — 같은 nodes/edges 위에 `data.label` 을
  status 별 styled `<div>` 로 교체 + `STATUS_STYLE` 매핑 7색.
- 편집 잠금 — `nodesDraggable={false}` / `nodesConnectable={false}` (PUBLISHED 워크플로
  진입 시).

## 3. 대안

### 대안 A — drawflow.js
- **장점:** 가볍다 (gzip ~12KB), CSS 만으로 노드 스타일링 충분.
- **기각 사유:**
  - TypeScript 정의가 부실 (`@types/drawflow` 비공식, 메인 패키지가 vanilla JS).
  - 커스텀 노드 = innerHTML 조작 — React 컴포넌트 직접 사용 어려움. 100 노드급이면
    React/DOM 동기화 깨짐 위험.
  - SSE 로 status 변경이 들어올 때 noderef 를 직접 찾아 DOM 변경해야 함 — 본 프로젝트
    의 React 18 + TanStack Query 흐름과 결이 안 맞음.

### 대안 B — vis.js / vis-network
- **장점:** 매우 큰 그래프(수천 노드) 에 강함. 물리 시뮬레이션 레이아웃 무료.
- **기각 사유:**
  - 우리 use case 는 ETL DAG (노드 100 미만) 라 물리 시뮬레이션 가치가 작다.
  - 번들 크기 ~ 220KB (gzip 67KB) — React Flow (gzip ~85KB) 보다 약간 작지만 React
    통합이 wrapper layer 를 강제 (vis-react / react-graph-vis) — wrapper 자체의
    유지보수 약함.

### 대안 C — react-digraph (Uber 출신)
- **장점:** Uber 의 ETL UI 에서 쓰던 안정성.
- **기각 사유:**
  - 2022 년 이후 메인테이너 활동 거의 없음. Issue 회전율 매우 낮음.
  - SVG-only 라 100 노드 이상에서 paint 비용 큼 (React Flow 12 는 viewport 기반
    virtualization 으로 보이는 영역만 그림).

### 대안 D — 직접 구현 (SVG + d3)
- **장점:** 의존성 0, 번들 영향 0.
- **기각 사유:**
  - drag/connect/zoom/pan/minimap/controls 를 모두 직접 구현 — 4~6주 추가 일정.
  - Phase 3 일정 안에 끝낼 가치가 없음 (운영팀 합류 9/1 마감).

## 4. 결과

**긍정적:**
- `@xyflow/react` 12 의 `useNodesState` / `useEdgesState` hook 으로 컨트롤드 상태
  관리가 자연스러움 — 우리의 backend PATCH 흐름과 정합.
- `screenToFlowPosition` API 로 drag drop 좌표 변환을 정확히 처리 (zoom/pan 적용
  후에도).
- `<MiniMap pannable zoomable />` / `<Controls />` 가 무료 — UX 비용 0.
- React Flow 12 의 `data` 가 `Record<string, unknown>` 호환 generic 이라 우리
  `DesignerNodeData` 에 index signature 만 추가하면 통과 (3.2.4 commit 참조).
- Phase 3.2.6 의 release diff 도 같은 그래프 위에 색상 오버레이로 확장 가능 — 별도
  라이브러리 학습 비용 없음.

**부정적:**
- 번들 크기 +85KB (gzip) — 현재 전체 ~180KB 의 47% 차지. Phase 4 에서 dynamic
  import 로 designer 페이지만 lazy load 하면 ~30KB 다이어트 가능.
- React Flow 12 가 `attribution` 워터마크를 기본 표시 — `proOptions={{ hideAttribution:
  true }}` 로 끄지만, 향후 무료 라이선스 정책 변경 시 재평가 필요.
- 100 노드 급 렌더 1초 이내 목표는 측정 미완료 (3.4 표 참조). 미달 시 Phase 4 에서
  noVirtualization 모드 도입 또는 viewport 기반 lazy render.

**중립:**
- 라이브러리 버전 차이 (xyflow 13, 14 …) 에 우리 generic 사용 패턴이 깨질 수 있음
  — TypeScript strict 모드라 타입 깨짐은 빌드 단계에서 감지됨.

## 5. 검증

- [x] Designer drag/connect/save/PUBLISH 흐름 — 3.2.4 통합 시연
- [x] PipelineRunDetail status 색상 7색 매핑 — 3.2.3
- [x] PUBLISHED → ARCHIVED 시 캔버스 readonly 자동 전환 — 3.2.4
- [ ] 100 노드 워크플로 렌더 1초 이내 — `frontend/tests/perf/test_designer_render.spec.ts`
  로 측정 예정 (실 인스턴스 + chromium 필요)

## 6. 회수 조건

- 100 노드 렌더가 2초 이상 — 다음 옵션 재검토:
  1. React Flow `onlyRenderVisibleElements` (viewport 기반 lazy) 활성.
  2. 노드 50개 이상 시 자동 collapse (sub-DAG 그룹).
  3. 그래프 라이브러리 교체 (cytoscape.js — 1만 노드급 검증).
- 무료 라이선스 정책 불투명해지면 — drawflow / 직접 SVG 로 마이그레이션 (PR 단위 ~1
  스프린트 작업 추정).

## 7. 참고

- `frontend/src/pages/PipelineDesigner.tsx` — drag/connect/save 메인.
- `frontend/src/pages/PipelineRunDetail.tsx` — 상태 색상 7색.
- `frontend/src/components/designer/NodePalette.tsx` — 좌측 7노드 카드 + drag MIME.
- `frontend/tests/perf/test_designer_render.spec.ts` — 비기능 측정 스펙.
- ADR-0008 (sandbox 정책) — 같은 페이지의 SQL Studio 와 결합 패턴.
