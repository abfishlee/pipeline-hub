// 매뉴얼 마크다운 → HTML → PDF 변환 (Chromium Headless 활용).
//
// 실행: node scripts/generate_manual_pdf.mjs
// 결과: docs/manual/PHASE_8_SCENARIO_MANUAL.pdf

import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = join(__dirname, "..", "..");
const MANUAL_DIR = join(ROOT, "docs", "manual");
const MD_FILE = join(MANUAL_DIR, "PHASE_8_SCENARIO_MANUAL.md");
const HTML_FILE = join(MANUAL_DIR, "PHASE_8_SCENARIO_MANUAL.html");
const PDF_FILE = join(MANUAL_DIR, "PHASE_8_SCENARIO_MANUAL.pdf");

// 매우 단순한 마크다운 → HTML 변환기 (외부 라이브러리 없이).
// 표 / 코드블록 / 헤더 / 이미지 / 강조만 지원.
function mdToHtml(md) {
  const lines = md.split(/\r?\n/);
  const out = [];
  let inCode = false;
  let inTable = false;
  let inFrontmatter = false;
  let frontmatter = {};

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    // frontmatter
    if (i === 0 && line === "---") {
      inFrontmatter = true;
      continue;
    }
    if (inFrontmatter) {
      if (line === "---") {
        inFrontmatter = false;
        continue;
      }
      const m = line.match(/^(\w+):\s*(.+)$/);
      if (m) frontmatter[m[1]] = m[2];
      continue;
    }

    // code block
    if (line.startsWith("```")) {
      if (!inCode) {
        out.push("<pre><code>");
        inCode = true;
      } else {
        out.push("</code></pre>");
        inCode = false;
      }
      continue;
    }
    if (inCode) {
      out.push(escape(line));
      continue;
    }

    // table (simple — | header | rows)
    if (line.startsWith("|") && line.includes("|")) {
      if (!inTable) {
        out.push('<table>');
        inTable = true;
        // header
        const cells = line.split("|").slice(1, -1).map((c) => c.trim());
        out.push("<thead><tr>" + cells.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead>");
        // skip separator
        if (lines[i + 1] && /^\|[\s\-:|]+\|$/.test(lines[i + 1])) i++;
        out.push("<tbody>");
        continue;
      }
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      out.push("<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
      continue;
    }
    if (inTable) {
      out.push("</tbody></table>");
      inTable = false;
    }

    // headers
    let m;
    if ((m = line.match(/^####\s+(.+)$/))) {
      out.push(`<h4>${inline(m[1])}</h4>`);
      continue;
    }
    if ((m = line.match(/^###\s+(.+)$/))) {
      out.push(`<h3>${inline(m[1])}</h3>`);
      continue;
    }
    if ((m = line.match(/^##\s+(.+)$/))) {
      out.push(`<h2>${inline(m[1])}</h2>`);
      continue;
    }
    if ((m = line.match(/^#\s+(.+)$/))) {
      out.push(`<h1>${inline(m[1])}</h1>`);
      continue;
    }

    // hr
    if (line.match(/^-{3,}$/)) {
      out.push("<hr/>");
      continue;
    }

    // image — ![alt](path)
    if ((m = line.match(/^!\[(.*)\]\((.+)\)$/))) {
      out.push(`<figure><img src="${m[2]}" alt="${escape(m[1])}"/><figcaption>${escape(m[1])}</figcaption></figure>`);
      continue;
    }

    // unordered list
    if (line.match(/^(\s*)[-*]\s+/)) {
      out.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`);
      continue;
    }

    // empty
    if (line.trim() === "") {
      out.push("<br/>");
      continue;
    }

    // paragraph
    out.push(`<p>${inline(line)}</p>`);
  }

  if (inTable) out.push("</tbody></table>");
  if (inCode) out.push("</code></pre>");

  return { html: out.join("\n"), frontmatter };
}

function inline(s) {
  // bold
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // italic
  s = s.replace(/(?<!\w)\*([^*]+)\*(?!\w)/g, "<em>$1</em>");
  // inline code
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  // links
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  return s;
}

function escape(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function main() {
  const md = await readFile(MD_FILE, "utf-8");
  const { html: body, frontmatter } = mdToHtml(md);
  const title = frontmatter.title || "Pipeline Hub Manual";
  const subtitle = frontmatter.subtitle || "";
  const date = frontmatter.date || "";

  const html = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>${title}</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  body { font-family: 'Malgun Gothic', 'NanumGothic', sans-serif; line-height: 1.55; color: #222; font-size: 11pt; }
  h1 { font-size: 22pt; border-bottom: 3px solid #2563eb; padding-bottom: 6px; margin-top: 22pt; }
  h2 { font-size: 17pt; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 24pt; page-break-before: auto; }
  h3 { font-size: 13pt; color: #2563eb; margin-top: 14pt; }
  h4 { font-size: 11pt; color: #1f2937; }
  p { margin: 6pt 0; }
  br { display: none; }
  hr { border: none; border-top: 1px dashed #aaa; margin: 14pt 0; }
  ul, ol { margin: 4pt 0; padding-left: 22pt; }
  li { margin: 2pt 0; }
  table { width: 100%; border-collapse: collapse; margin: 10pt 0; font-size: 9.5pt; }
  th, td { border: 1px solid #ccc; padding: 4pt 6pt; text-align: left; vertical-align: top; }
  th { background: #f1f5f9; font-weight: 600; }
  code { background: #f3f4f6; padding: 1pt 4pt; border-radius: 3px; font-family: 'Consolas', monospace; font-size: 9.5pt; }
  pre { background: #1e293b; color: #e2e8f0; padding: 10pt; border-radius: 4px; font-size: 8.5pt; overflow-x: auto; }
  pre code { background: transparent; color: inherit; padding: 0; }
  figure { margin: 14pt 0; page-break-inside: avoid; }
  img { max-width: 100%; height: auto; border: 1px solid #d1d5db; border-radius: 3px; }
  figcaption { font-size: 9pt; color: #6b7280; text-align: center; margin-top: 4pt; font-style: italic; }
  a { color: #2563eb; text-decoration: none; }
  strong { color: #111; }
  .cover { page-break-after: always; padding: 50pt 0; text-align: center; }
  .cover h1 { font-size: 30pt; border: none; }
  .cover .subtitle { font-size: 14pt; color: #6b7280; margin-top: 12pt; }
  .cover .date { font-size: 11pt; color: #9ca3af; margin-top: 22pt; }
</style></head><body>
<div class="cover">
  <h1>${title}</h1>
  <div class="subtitle">${subtitle}</div>
  <div class="date">${date}</div>
</div>
${body}
</body></html>`;

  await writeFile(HTML_FILE, html, "utf-8");
  console.log("HTML written: " + HTML_FILE);

  // Chromium 으로 PDF 생성
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(pathToFileURL(HTML_FILE).href, { waitUntil: "networkidle" });
  await page.emulateMedia({ media: "print" });
  await page.pdf({
    path: PDF_FILE,
    format: "A4",
    printBackground: true,
    margin: { top: "16mm", bottom: "16mm", left: "14mm", right: "14mm" },
  });
  await browser.close();
  console.log("PDF written: " + PDF_FILE);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
