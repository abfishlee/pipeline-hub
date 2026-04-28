// Phase 8.6 — 모든 메뉴 자동 테스트 (Playwright).
//
// 각 메뉴 페이지 navigate → console error / network error / 4xx-5xx 응답 수집.
// 실행:
//   cd frontend
//   node scripts/test_all_menus.mjs

import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE = process.env.MENU_TEST_BASE ?? "http://127.0.0.1:5173";
const ADMIN = "admin";
const PW = "admin";

const MENUS = [
  // [path, label, expectsAdmin?]
  ["/", "Dashboard"],
  ["/v2/connectors/public-api", "Source / API Connector", true],
  ["/v2/inbound-channels/designer", "Inbound Channel"],
  ["/v2/marts/designer", "Mart Workbench", true],
  ["/v2/mappings/designer", "Field Mapping Designer", true],
  ["/v2/transforms/designer", "Transform Designer", true],
  ["/v2/quality/designer", "Quality Workbench", true],
  ["/v2/pipelines/designer", "ETL Canvas V2 (new)", true],
  ["/pipelines/runs", "Pipeline Runs"],
  ["/pipelines/releases", "Releases"],
  ["/v2/service-mart", "Service Mart Viewer"],
  ["/raw-objects", "Raw Objects"],
  ["/jobs", "Collection Jobs"],
  ["/master-merge", "Master Merge", true],
  ["/sql-studio", "SQL Studio"],
  ["/crowd-tasks", "Review Queue"],
  ["/v2/operations/dashboard", "Operations Dashboard"],
  ["/runtime", "Runtime Monitor"],
  ["/v2/mock-api", "Mock API (Admin)", true],
  ["/dead-letters", "Dead Letters", true],
  ["/users", "Users", true],
  ["/api-keys", "API Keys", true],
  ["/security-events", "Security Events", true],
  ["/admin/partitions", "Partition Archive", true],
  // 동적 라우트 — 데모 시나리오 (run_demo.py) 가 만든 workflow_id=2, run_id=2
  ["/v2/pipelines/designer/2", "ETL Canvas V2 (existing)", true],
  ["/pipelines/runs/2", "Pipeline Run Detail"],
];

const results = [];

function classify(url, statusCode) {
  // 정상적으로 무시 가능한 에러 (HMR / SSE 끊김 등)
  if (
    url.includes("/sse/") ||
    url.includes("@vite") ||
    url.includes("/__vite") ||
    url.endsWith("/events") ||
    url.includes("/runs/") && url.endsWith("/events")
  ) {
    return "ignore";
  }
  if (statusCode >= 500) return "server_error";
  if (statusCode === 404) return "not_found";
  if (statusCode === 403) return "forbidden";
  if (statusCode >= 400) return "client_error";
  return "ok";
}

async function login(page) {
  await page.goto(`${BASE}/login`);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.fill("#login_id", ADMIN);
  await page.fill('input[type="password"]', PW);
  await Promise.all([
    page
      .waitForURL((u) => !u.toString().endsWith("/login"), { timeout: 15000 })
      .catch(() => {}),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function testMenu(page, urlPath, label) {
  const consoleErrors = [];
  const networkErrors = [];
  const failedResponses = [];

  const onConsole = (msg) => {
    if (msg.type() === "error") {
      const text = msg.text();
      // React 개발 모드 노이즈 무시
      if (text.includes("React DevTools")) return;
      if (text.includes("Download the React DevTools")) return;
      consoleErrors.push(text);
    }
  };
  const onPageError = (err) => {
    consoleErrors.push(`PAGE_ERROR: ${err.message}`);
  };
  const onResponse = (res) => {
    const status = res.status();
    const url = res.url();
    const cls = classify(url, status);
    if (cls === "ignore" || cls === "ok") return;
    failedResponses.push({ url, status, cls });
  };
  const onRequestFailed = (req) => {
    networkErrors.push(`${req.method()} ${req.url()}: ${req.failure()?.errorText}`);
  };

  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  page.on("response", onResponse);
  page.on("requestfailed", onRequestFailed);

  let navError = null;
  try {
    // 'load' 로 완화 — SSE 같은 long-poll 이 있는 페이지에서 networkidle 대기 불가
    await page.goto(`${BASE}${urlPath}`, { waitUntil: "load", timeout: 20000 });
    // 페이지 렌더링 + lazy network 호출 대기
    await page.waitForTimeout(2500);
  } catch (err) {
    navError = err.message;
  }

  page.off("console", onConsole);
  page.off("pageerror", onPageError);
  page.off("response", onResponse);
  page.off("requestfailed", onRequestFailed);

  const finalUrl = page.url();
  const redirectedToLogin = finalUrl.endsWith("/login") && !urlPath.endsWith("/login");

  return {
    path: urlPath,
    label,
    finalUrl,
    redirectedToLogin,
    navError,
    consoleErrors,
    networkErrors,
    failedResponses,
    pass:
      !navError &&
      !redirectedToLogin &&
      consoleErrors.length === 0 &&
      failedResponses.filter((r) => r.cls !== "forbidden").length === 0,
  };
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const page = await context.newPage();

await login(page);
console.log("[login] OK");

for (const [urlPath, label] of MENUS) {
  process.stdout.write(`[test] ${label.padEnd(35)} ${urlPath.padEnd(35)} ... `);
  const res = await testMenu(page, urlPath, label);
  results.push(res);
  if (res.pass) {
    console.log("✓");
  } else {
    console.log("✗");
    if (res.navError) console.log(`     navError: ${res.navError}`);
    if (res.redirectedToLogin) console.log(`     redirected to /login`);
    for (const err of res.consoleErrors) console.log(`     console: ${err.slice(0, 200)}`);
    for (const fr of res.failedResponses)
      console.log(`     ${fr.status} ${fr.url.slice(0, 150)}`);
    for (const ne of res.networkErrors)
      console.log(`     network: ${ne.slice(0, 200)}`);
  }
}

await browser.close();

// summary
const failed = results.filter((r) => !r.pass);
console.log("\n" + "=".repeat(70));
console.log(`총 ${results.length}개 메뉴 — 통과 ${results.length - failed.length}, 실패 ${failed.length}`);
console.log("=".repeat(70));

// JSON 저장
const reportPath = path.resolve(__dirname, "../../docs/menu_guide/test_results.json");
fs.writeFileSync(
  reportPath,
  JSON.stringify({ timestamp: new Date().toISOString(), results }, null, 2),
);
console.log(`\n상세 결과 저장: ${reportPath}`);

if (failed.length > 0) {
  process.exit(1);
}
