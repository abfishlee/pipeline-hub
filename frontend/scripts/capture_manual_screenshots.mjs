// Phase 8.5 — 사용자 매뉴얼 스크린샷 자동 캡처.
//
// 실행 (frontend dir 에서, playwright 패키지 활용):
//   cd frontend
//   node scripts/capture_manual_screenshots.mjs
//
// 전제:
//   - backend (port 8000) + frontend dev (port 5173) 가동 중
//   - Phase 8 seed 적용 (admin/admin 계정 + 4 유통사 데이터)

import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE_URL = process.env.MANUAL_BASE_URL ?? "http://127.0.0.1:5173";
const ADMIN_LOGIN = process.env.MANUAL_ADMIN_LOGIN ?? "admin";
const ADMIN_PW = process.env.MANUAL_ADMIN_PW ?? "admin";
const SS_DIR = path.resolve(__dirname, "../../docs/manual/screenshots");

const VIEWPORT = { width: 1366, height: 900 };

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("networkidle");
  await page.fill("#login_id", ADMIN_LOGIN);
  await page.fill('input[type="password"]', ADMIN_PW);
  await Promise.all([
    page
      .waitForURL((u) => !u.toString().endsWith("/login"), { timeout: 15_000 })
      .catch(() => {}),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function shoot(page, fname, opts = {}) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(opts.delay ?? 1200);
  const out = path.join(SS_DIR, fname);
  await page.screenshot({ path: out, fullPage: opts.fullPage ?? true });
  console.log(`[shot] ${fname}`);
}

async function navAndShoot(page, urlPath, fname, opts = {}) {
  await page.goto(`${BASE_URL}${urlPath}`);
  await shoot(page, fname, opts);
}

const SHOTS = [
  // url, filename, opts
  ["__login_screen__", "01_login.png", { fullPage: false }],
  ["/", "02_dashboard.png", {}],
  ["/v2/connectors/public-api", "03_source_api_connector.png", {}],
  ["/v2/inbound-channels/designer", "04_inbound_channel.png", {}],
  ["/v2/marts/designer", "05_mart_workbench.png", {}],
  ["/v2/mappings/designer", "06_field_mapping_designer.png", {}],
  ["/v2/transforms/designer", "07_transform_designer.png", {}],
  ["/v2/quality/designer", "08_quality_workbench.png", {}],
  ["/v2/pipelines/designer", "09_etl_canvas_v2_new.png", { delay: 1800 }],
  ["/pipelines/runs", "10_pipeline_runs.png", {}],
  ["__first_run_detail__", "11_pipeline_run_detail.png", { delay: 1500 }],
  ["/pipelines/releases", "12_releases.png", {}],
  ["/v2/service-mart", "13_service_mart_viewer.png", {}],
  ["/raw-objects", "14_raw_objects.png", {}],
  ["/jobs", "15_collection_jobs.png", {}],
  ["/crowd-tasks", "16_review_queue.png", {}],
  ["/v2/operations/dashboard", "17_operations_dashboard.png", { delay: 1800 }],
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: VIEWPORT });
const page = await context.newPage();

const successes = [];
const failures = [];

let loggedIn = false;

try {
  for (const [target, fname, opts] of SHOTS) {
    try {
      if (target === "__login_screen__") {
        await page.goto(`${BASE_URL}/login`);
        await shoot(page, fname, opts);
        continue;
      }
      // 인증 필요한 첫 페이지 진입 시 한 번만 로그인.
      if (!loggedIn) {
        await login(page);
        loggedIn = true;
      }
      if (target === "__first_run_detail__") {
        // Phase 8 시드된 emart workflow run 1건 (4 nodes 가진 SUCCESS) 으로 진입.
        const runId = process.env.MANUAL_RUN_ID ?? "279";
        await page.goto(`${BASE_URL}/pipelines/runs/${runId}`);
        await shoot(page, fname, opts);
        continue;
      }
      await navAndShoot(page, target, fname, opts);
      successes.push(fname);
    } catch (err) {
      console.error(`[fail] ${fname}:`, err.message);
      failures.push([fname, err.message]);
    }
  }
} finally {
  await browser.close();
}

console.log(`\n=== capture summary ===`);
console.log(`success: ${successes.length} / ${SHOTS.length}`);
if (failures.length) {
  console.log(`\nfailures:`);
  for (const [fname, msg] of failures) console.log(`  - ${fname}: ${msg}`);
}
