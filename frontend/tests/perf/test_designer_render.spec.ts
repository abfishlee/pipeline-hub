// Phase 3 비기능 측정 — Visual ETL Designer 의 100-노드 렌더 1초 이내.
//
// 실행:
//   cd frontend
//   pnpm add -D @playwright/test
//   pnpm exec playwright install chromium
//   pnpm exec playwright test tests/perf/test_designer_render.spec.ts
//
// 본 스펙은 Playwright 가 설치돼 있어야만 동작 — 일반 vite/tsc 빌드와는 무관.
// frontend dev 서버가 떠 있어야 함 (`pnpm dev`).
//
// 측정 방법:
//   1. /pipelines/designer 에 진입.
//   2. 미리 만들어둔 100-노드 워크플로 ID (env BENCH_WORKFLOW_ID) 로 navigate.
//   3. React Flow 캔버스의 첫 paint (<div data-testid="rf-canvas">) 렌더 시각 측정.
//   4. measurement.toBeLessThan(1000) 검증.
//
// `BENCH_WORKFLOW_ID` 가 없으면 skip — 운영자가 미리 backend seed 로 만들어 두는 게 전제.

// @ts-nocheck — Playwright 가 설치돼야만 import 가 해석됨. tsc 빌드에서는 skip.

import { expect, test } from "@playwright/test";

const BENCH_WF = process.env.BENCH_WORKFLOW_ID;
const BASE_URL = process.env.BENCH_BASE_URL ?? "http://localhost:5173";
const ADMIN_LOGIN = process.env.BENCH_ADMIN_LOGIN ?? "it_admin";
const ADMIN_PW = process.env.BENCH_ADMIN_PW ?? "it-admin-pw-0425";

test.describe("Visual ETL Designer — 100 nodes render perf", () => {
  test.skip(!BENCH_WF, "BENCH_WORKFLOW_ID env not set");

  test("renders within 1000ms (target Phase 3 비기능)", async ({ page }) => {
    // 로그인.
    await page.goto(`${BASE_URL}/login`);
    await page.getByPlaceholder("login_id").fill(ADMIN_LOGIN);
    await page.getByPlaceholder("password").fill(ADMIN_PW);
    await page.getByRole("button", { name: /로그인/i }).click();
    await expect(page).toHaveURL(/\/(?!login)/);

    // 측정 시작 직전 navigate.
    const t0 = Date.now();
    await page.goto(`${BASE_URL}/pipelines/designer/${BENCH_WF}`);
    // React Flow 캔버스의 viewport <div class="react-flow__viewport"> 첫 transform 적용까지.
    await page.locator(".react-flow__viewport").waitFor({ state: "attached" });
    await page.locator(".react-flow__node").first().waitFor({ state: "visible" });
    const t1 = Date.now();

    const elapsedMs = t1 - t0;
    // 결과는 콘솔로 — runner 가 stdout 캡처해 PHASE_3 표에 기록.
    // eslint-disable-next-line no-console
    console.log(`[PERF designer] elapsed=${elapsedMs}ms target=1000ms workflow_id=${BENCH_WF}`);

    expect(elapsedMs).toBeLessThan(1000);
  });
});
