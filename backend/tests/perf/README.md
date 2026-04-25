# Phase 3 비기능 측정 — 수동 실행 스크립트

본 디렉토리의 테스트는 일반 pytest 실행에 포함되지 않는다 (`PERF=1` 환경변수가 없으면
모두 skip). 인프라(실 PG / 실 Redis / 실 FastAPI 인스턴스)가 켜져 있는 환경에서 한 번
돌려 baseline 을 잡고 결과를 `docs/phases/PHASE_3_VISUAL_ETL.md` 3.4 표에 기록한다.

## 실행 방법

PG + Redis + 백엔드(`.venv/Scripts/python -m uvicorn app.main:app --port 8000`)가 떠 있어야
함. 그리고 같은 셸에서:

```bash
cd backend
PERF=1 .venv/Scripts/python -m pytest tests/perf/test_sandbox_isolation.py -q -s
PERF=1 .venv/Scripts/python -m pytest tests/perf/test_sse_latency.py        -q -s
```

각 테스트는 `pass/fail` 판정 외에 측정값(ms / row count)을 stdout 으로 출력한다.

프런트의 React Flow 렌더 perf 는 [frontend/tests/perf/](../../../frontend/tests/perf/) 의
Playwright 스펙으로 측정. 다음을 한 번 실행:

```bash
cd frontend
pnpm add -D @playwright/test
pnpm exec playwright install chromium
pnpm exec playwright test tests/perf/test_designer_render.spec.ts
```

## 결과 기록

- baseline 은 PHASE_3_VISUAL_ETL.md 3.4 표에 (측정 일자 / 환경 / 측정값 / 통과 여부) 4
  컬럼으로 기록.
- 실패 / 미달 항목은 GitHub Issue 를 만들고 표에 링크.
