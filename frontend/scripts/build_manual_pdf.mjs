// Phase 8.5 — 매뉴얼 마크다운 → HTML → PDF 자동 생성.
//
// 실행 (frontend dir 에서):
//   cd frontend
//   node scripts/build_manual_pdf.mjs
//
// 입력:  ../docs/manual/PHASE_8_SCENARIO_MANUAL.md
// 출력:  ../docs/manual/PHASE_8_SCENARIO_MANUAL.html
//        ../docs/manual/PHASE_8_SCENARIO_MANUAL.pdf

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ROOT = path.resolve(__dirname, "../../docs/manual");
const MD_PATH = path.join(ROOT, "PHASE_8_SCENARIO_MANUAL.md");
const HTML_PATH = path.join(ROOT, "PHASE_8_SCENARIO_MANUAL.html");
const PDF_PATH = path.join(ROOT, "PHASE_8_SCENARIO_MANUAL.pdf");

const md = fs.readFileSync(MD_PATH, "utf8");

// ---------------------------------------------------------------------------
// Minimal markdown → HTML converter (CommonMark subset).
// 지원: front-matter / h1~h4 / 단락 / 줄바꿈 / 굵게(**...**) / 코드(`...`) /
//       링크 / 이미지 / 코드블록(```) / 리스트 / 표 / hr.
// ---------------------------------------------------------------------------
function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inlineMd(s) {
  // image first to avoid link conflict
  s = s.replace(
    /!\[([^\]]*)\]\(([^)]+)\)/g,
    (_, alt, src) =>
      `<figure><img src="${src}" alt="${escapeHtml(alt)}" />` +
      (alt ? `<figcaption>${escapeHtml(alt)}</figcaption>` : "") +
      `</figure>`,
  );
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return s;
}

function convertMarkdown(src) {
  // strip front-matter
  src = src.replace(/^---\n[\s\S]*?\n---\n/, "");

  const lines = src.split(/\r?\n/);
  const out = [];
  let inCode = false;
  let codeLang = "";
  let codeBuf = [];
  let listType = null; // "ul" or "ol"
  let listBuf = [];
  let tableHeader = null;
  let tableBuf = [];

  function flushList() {
    if (listType) {
      out.push(`<${listType}>`);
      for (const item of listBuf) {
        out.push(`<li>${inlineMd(item)}</li>`);
      }
      out.push(`</${listType}>`);
      listType = null;
      listBuf = [];
    }
  }
  function flushTable() {
    if (tableHeader) {
      out.push("<table>");
      out.push(
        "<thead><tr>" +
          tableHeader.map((c) => `<th>${inlineMd(c.trim())}</th>`).join("") +
          "</tr></thead>",
      );
      out.push("<tbody>");
      for (const row of tableBuf) {
        out.push(
          "<tr>" +
            row.map((c) => `<td>${inlineMd(c.trim())}</td>`).join("") +
            "</tr>",
        );
      }
      out.push("</tbody></table>");
      tableHeader = null;
      tableBuf = [];
    }
  }

  for (let raw of lines) {
    const line = raw;

    // code block fence
    if (/^```/.test(line)) {
      flushList();
      flushTable();
      if (!inCode) {
        inCode = true;
        codeLang = line.replace(/^```/, "").trim();
        codeBuf = [];
      } else {
        out.push(
          `<pre><code class="lang-${codeLang || "txt"}">${escapeHtml(codeBuf.join("\n"))}</code></pre>`,
        );
        inCode = false;
      }
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      continue;
    }

    // table?
    if (/^\|.*\|/.test(line) && line.includes("|")) {
      const cells = line.replace(/^\|/, "").replace(/\|$/, "").split("|");
      if (tableHeader === null) {
        // could be header — peek next line for separator
        tableHeader = cells;
      } else if (/^\|?\s*[-: ]+\|/.test(line)) {
        // separator — ignore
      } else {
        tableBuf.push(cells);
      }
      continue;
    } else if (tableHeader !== null) {
      flushTable();
    }

    // heading
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flushList();
      flushTable();
      out.push(`<h${h[1].length}>${inlineMd(h[2])}</h${h[1].length}>`);
      continue;
    }

    // hr
    if (/^---+\s*$/.test(line)) {
      flushList();
      flushTable();
      out.push("<hr/>");
      continue;
    }

    // unordered list
    const ul = /^[-*]\s+(.*)$/.exec(line);
    if (ul) {
      if (listType !== "ul") flushList();
      listType = "ul";
      listBuf.push(ul[1]);
      continue;
    }
    // ordered list
    const ol = /^\d+\.\s+(.*)$/.exec(line);
    if (ol) {
      if (listType !== "ol") flushList();
      listType = "ol";
      listBuf.push(ol[1]);
      continue;
    }
    if (listType && /^\s+/.test(line) && line.trim()) {
      // continuation
      listBuf[listBuf.length - 1] += " " + line.trim();
      continue;
    }
    flushList();

    // blank
    if (!line.trim()) {
      out.push("");
      continue;
    }

    // paragraph
    out.push(`<p>${inlineMd(line)}</p>`);
  }
  flushList();
  flushTable();
  if (inCode) {
    out.push(
      `<pre><code class="lang-${codeLang || "txt"}">${escapeHtml(codeBuf.join("\n"))}</code></pre>`,
    );
  }
  return out.join("\n");
}

// front-matter title/subtitle 추출
function extractFrontMatter(src) {
  const m = /^---\n([\s\S]*?)\n---\n/.exec(src);
  if (!m) return {};
  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^(\w+):\s*(.*)$/.exec(line);
    if (kv) meta[kv[1]] = kv[2];
  }
  return meta;
}

const meta = extractFrontMatter(md);
const body = convertMarkdown(md);

const html = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>${escapeHtml(meta.title ?? "Pipeline Hub Manual")}</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  body { font-family: 'Malgun Gothic', 'NanumGothic', 'Apple SD Gothic Neo', sans-serif; line-height: 1.55; color: #222; font-size: 10.5pt; }
  h1 { font-size: 22pt; border-bottom: 3px solid #2563eb; padding-bottom: 6px; margin-top: 22pt; }
  h2 { font-size: 16pt; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 22pt; page-break-after: avoid; }
  h3 { font-size: 12.5pt; color: #2563eb; margin-top: 14pt; page-break-after: avoid; }
  h4 { font-size: 11pt; color: #1f2937; page-break-after: avoid; }
  p { margin: 5pt 0; }
  hr { border: none; border-top: 1px dashed #aaa; margin: 14pt 0; }
  ul, ol { margin: 4pt 0; padding-left: 22pt; }
  li { margin: 2pt 0; }
  table { width: 100%; border-collapse: collapse; margin: 10pt 0; font-size: 9.5pt; page-break-inside: avoid; }
  th, td { border: 1px solid #ccc; padding: 4pt 6pt; text-align: left; vertical-align: top; }
  th { background: #f1f5f9; font-weight: 600; }
  code { background: #f3f4f6; padding: 1pt 4pt; border-radius: 3px; font-family: 'Consolas', monospace; font-size: 9.5pt; }
  pre { background: #1e293b; color: #e2e8f0; padding: 10pt; border-radius: 4px; font-size: 8.5pt; overflow-x: auto; page-break-inside: avoid; }
  pre code { background: transparent; color: inherit; padding: 0; }
  figure { margin: 12pt 0; page-break-inside: avoid; }
  img { max-width: 100%; height: auto; border: 1px solid #d1d5db; border-radius: 3px; }
  figcaption { font-size: 9pt; color: #6b7280; text-align: center; margin-top: 3pt; font-style: italic; }
  a { color: #2563eb; text-decoration: none; }
  strong { color: #111; }
  .cover { page-break-after: always; padding: 60pt 0; text-align: center; }
  .cover h1 { font-size: 28pt; border: none; }
  .cover .subtitle { font-size: 13pt; color: #6b7280; margin-top: 12pt; }
  .cover .date { font-size: 11pt; color: #9ca3af; margin-top: 22pt; }
  .cover .version { font-size: 10pt; color: #2563eb; margin-top: 6pt; font-weight: 600; }
</style></head><body>
<div class="cover">
  <h1>${escapeHtml(meta.title ?? "Pipeline Hub Manual")}</h1>
  <div class="subtitle">${escapeHtml(meta.subtitle ?? "")}</div>
  <div class="version">${escapeHtml(meta.version ?? "")}</div>
  <div class="date">${escapeHtml(meta.date ?? "")}</div>
</div>
${body}
</body></html>`;

fs.writeFileSync(HTML_PATH, html, "utf8");
console.log(`[html] ${path.relative(process.cwd(), HTML_PATH)}`);

// ---------------------------------------------------------------------------
// HTML → PDF via Chromium
// ---------------------------------------------------------------------------
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const page = await context.newPage();
const fileUrl = "file:///" + HTML_PATH.replace(/\\/g, "/");
await page.goto(fileUrl, { waitUntil: "networkidle" });
await page.waitForTimeout(800);
await page.pdf({
  path: PDF_PATH,
  format: "A4",
  printBackground: true,
  margin: { top: "18mm", right: "16mm", bottom: "18mm", left: "16mm" },
});
console.log(`[pdf]  ${path.relative(process.cwd(), PDF_PATH)}`);
await browser.close();
