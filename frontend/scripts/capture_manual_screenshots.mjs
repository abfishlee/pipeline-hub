// Phase 8 시나리오 매뉴얼용 화면 캡처 자동화.
//
// 실행: cd frontend && node scripts/capture_manual_screenshots.mjs
// 결과: docs/manual/screenshots/*.png

import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = join(__dirname, "..", "..");
const OUT_DIR = join(ROOT, "docs", "manual", "screenshots");

const BASE_URL = "http://127.0.0.1:5173";
const ADMIN_LOGIN = "admin";
const ADMIN_PASSWORD = "admin";

const PAGES = [
  // [filename, path, description, optional-wait-for-selector]
  ["01_login", "/login", "로그인", null],
  ["02_dashboard", "/", "Dashboard", null],
  ["03_source_api_connector", "/v2/connectors/public-api", "Source / API Connector — 4 유통사", null],
  ["04_inbound_channel", "/v2/inbound-channels/designer", "Inbound Channel — 외부 push 채널 3개", null],
  ["05_mart_workbench", "/v2/marts/designer", "Mart Workbench — 5 mart drafts + 5 load policies", null],
  ["06_field_mapping_designer", "/v2/mappings/designer", "Field Mapping Designer — 4 contracts + 21 mappings", null],
  ["07_transform_designer", "/v2/transforms/designer", "Transform Designer — SQL Asset / Provider 카탈로그", null],
  ["08_quality_workbench", "/v2/quality/designer", "Quality Workbench — 16 DQ rules + 표준코드", null],
  ["09_etl_canvas", "/v2/pipelines/designer", "ETL Canvas v2 — 17종 노드 palette", null],
  ["10_pipeline_runs", "/pipelines/runs", "Pipeline Runs — 28 runs 이력", null],
  ["11_releases", "/pipelines/releases", "Releases — 4 배포 이력", null],
  ["12_service_mart_viewer", "/v2/service-mart", "Service Mart Viewer — 4 유통사 통합 가격", null],
  ["13_raw_objects", "/raw-objects", "Raw Objects — 127 raw payload", null],
  ["14_collection_jobs", "/jobs", "Collection Jobs — 28 ingest jobs", null],
  ["15_review_queue", "/crowd-tasks", "Review Queue — 9 검수 tasks", null],
  ["16_operations_dashboard", "/v2/operations/dashboard", "Operations Dashboard — 8 channels + heatmap", null],
];

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "ko-KR",
  });
  const page = await context.newPage();

  // 1. 로그인 페이지 먼저 캡처
  console.log("→ /login 캡처 중...");
  await page.goto(BASE_URL + "/login", { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(OUT_DIR, "01_login.png"), fullPage: true });

  // 2. 로그인
  await page.fill('input[type="text"], input[name="login_id"], input[id="login_id"]', ADMIN_LOGIN).catch(() => {});
  // Try common selectors
  const loginInput = await page.$('input[name="login_id"], input[placeholder*="ID"], input[placeholder*="아이디"]');
  if (loginInput) await loginInput.fill(ADMIN_LOGIN);
  else {
    const inputs = await page.$$("input");
    if (inputs[0]) await inputs[0].fill(ADMIN_LOGIN);
    if (inputs[1]) await inputs[1].fill(ADMIN_PASSWORD);
  }
  const passwordInput = await page.$('input[type="password"]');
  if (passwordInput) await passwordInput.fill(ADMIN_PASSWORD);

  // submit (button "로그인" or first submit button)
  await page.click('button[type="submit"], button:has-text("로그인"), button:has-text("Login"), button:has-text("Sign in")').catch(async () => {
    await page.keyboard.press("Enter");
  });
  await page.waitForURL(/^(?!.*\/login).*/, { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1500);

  // 3. 각 페이지 순회
  for (const [name, path, desc] of PAGES.slice(1)) {
    try {
      console.log(`→ ${path} 캡처 중 (${desc})...`);
      await page.goto(BASE_URL + path, { waitUntil: "networkidle", timeout: 15000 });
      await page.waitForTimeout(2500); // 데이터 로드 대기
      await page.screenshot({
        path: join(OUT_DIR, `${name}.png`),
        fullPage: true,
      });
    } catch (e) {
      console.error(`  ⚠ 실패: ${path} — ${e.message}`);
    }
  }

  await browser.close();
  console.log("✅ 완료. " + OUT_DIR);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
