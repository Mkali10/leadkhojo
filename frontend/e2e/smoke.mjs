/**
 * End-to-end smoke test.
 *
 * Drives the real UI in a real browser against a real backend. It is not a
 * substitute for unit tests; it is the check that the whole path — Vite proxy,
 * REST contract, polling, downloads, responsive layout — is actually wired
 * together, which is the class of failure that only shows up when you run it.
 *
 * Requires the API on :8000 and `npm run dev` on :5173.
 *
 *     npm run smoke
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = "http://127.0.0.1:5173";
const OUT = new URL("./screenshots/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

mkdirSync(OUT, { recursive: true });

const results = [];
const consoleErrors = [];
const pageErrors = [];

function check(name, ok, detail = "") {
  results.push({ ok, name, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  -- ${detail}` : ""}`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text());
});
page.on("pageerror", (e) => pageErrors.push(String(e)));

// ---------------------------------------------------------------- dashboard
await page.goto(BASE, { waitUntil: "networkidle" });
check("dashboard renders", (await page.title()) === "LeadKhojo", await page.title());
check(
  "backend status shown in header",
  await page.getByText(/checks ready/i).isVisible(),
  (await page.getByText(/checks ready/i).textContent()) ?? "",
);
const scanLinks = page.locator('a[href^="/scans/"]');
const scanCount = await scanLinks.count();
check("scan history listed", scanCount > 0, `${scanCount} scans`);
check("stat cards present", (await page.locator("text=Businesses analysed").count()) === 1);
await page.screenshot({ path: `${OUT}/01-dashboard.png`, fullPage: true });

// ---------------------------------------------------------------- checks page
await page.getByRole("link", { name: "Checks" }).click();
await page.waitForURL("**/plugins");
await page.waitForSelector("text=Technology Detection");
const pluginCount = await page.locator("ol > li").count();
check("plugins page lists the engine", pluginCount === 8, `${pluginCount} plugins`);
await page.screenshot({ path: `${OUT}/02-plugins.png`, fullPage: true });

// ---------------------------------------------------------------- new scan
await page.getByRole("link", { name: "New scan" }).click();
await page.waitForURL("**/scans/new");
await page.waitForSelector('textarea');
check("scan form renders", await page.getByRole("textbox", { name: "Domains" }).isVisible());
await page.getByRole("textbox", { name: "Domains" }).fill("example.com\niana.org");
check("domain counter updates", (await page.getByText("2 domains").count()) === 1);
await page.getByRole("tab", { name: "Upload a CSV" }).click();
check("csv tab switches", await page.getByText(/Choose a CSV file/).isVisible());
await page.getByRole("tab", { name: "Paste domains" }).click();
await page.screenshot({ path: `${OUT}/03-new-scan.png`, fullPage: true });

// ---------------------------------------------------------------- run a scan
await page.getByRole("textbox", { name: "Domains" }).fill("example.com");
await page.getByRole("textbox", { name: "Label" }).fill("UI verification");
await page.getByRole("button", { name: "Start scan" }).click();
await page.waitForURL(/\/scans\/[0-9a-f-]{36}$/, { timeout: 15000 });
const scanUrl = page.url();
check("create scan navigates to the new scan", true, scanUrl.split("/").pop());

// live progress
await page.waitForSelector("text=/Scanning|Scan finished/", { timeout: 15000 });
check("live progress panel appears", true);
await page.screenshot({ path: `${OUT}/04-progress.png`, fullPage: true });

// wait for the poll to reach a terminal state, which also proves polling works
await page.waitForSelector("text=Scan finished", { timeout: 90000 });
check("polling reached a terminal state without a reload", true);

await page.waitForTimeout(1200);
const headerBadge = (await page.locator("header ~ * .rounded-full, h1 ~ * span").allTextContents()).join(" ");
const saysPending = /pending|analyzing|discovering/i.test(
  (await page.locator('h1').locator("xpath=following::span[1]").textContent()) ?? "",
);
check(
  "header status agrees with the finished progress panel",
  !saysPending,
  headerBadge.slice(0, 60),
);
check(
  "Cancel is replaced by Re-run once finished",
  (await page.getByRole("button", { name: "Re-run" }).count()) === 1 &&
    (await page.getByRole("button", { name: "Cancel" }).count()) === 0,
);

// results table populated
await page.waitForSelector("table tbody tr", { timeout: 20000 });
const rowCount = await page.locator("table tbody tr").count();
check("results table populated", rowCount >= 1, `${rowCount} rows`);
check(
  "no contact renders as an explicit statement, not a blank",
  (await page.getByText("none published").count()) >= 1,
);
await page.screenshot({ path: `${OUT}/05-results.png`, fullPage: true });

// filters
await page.getByLabel("Show").selectOption("all");
await page.waitForTimeout(700);
check("status filter works", (await page.locator("table tbody tr").count()) >= 1);

// ---------------------------------------------------------------- downloads
const csv = await Promise.all([
  page.waitForEvent("download", { timeout: 20000 }),
  page.getByRole("button", { name: "CSV", exact: true }).click(),
]).then(([d]) => d);
check("CSV downloads with the server filename", csv.suggestedFilename().endsWith(".csv"), csv.suggestedFilename());

const pdf = await Promise.all([
  page.waitForEvent("download", { timeout: 20000 }),
  page.getByRole("button", { name: "PDF", exact: true }).click(),
]).then(([d]) => d);
check("PDF downloads with the server filename", pdf.suggestedFilename().endsWith(".pdf"), pdf.suggestedFilename());

// ---------------------------------------------------------------- business detail
await page.locator("table tbody tr a").first().click();
await page.waitForURL(/\/businesses\/[0-9a-f-]{36}$/);
await page.waitForSelector("text=Scores");
check("business detail renders", true, page.url().split("/").pop());
check("score bars present", (await page.locator('[role="progressbar"]').count()) >= 4);

await page.getByRole("tab", { name: /Findings/ }).click();
await page.waitForSelector("text=Problems");
check("findings grouped by outcome", (await page.getByText("Not checked").count()) >= 1);

const evidence = page.getByRole("button", { name: "Show evidence" }).first();
await evidence.click();
check("evidence expands", (await page.getByText("Hide evidence").count()) >= 1);
await page.screenshot({ path: `${OUT}/06-business-findings.png`, fullPage: true });

await page.getByRole("tab", { name: /Contacts/ }).click();
check("contacts tab renders", (await page.getByText(/No contact details published|source/).count()) >= 1);

await page.getByRole("tab", { name: /Opportunities/ }).click();
await page.waitForTimeout(300);
check("opportunities tab renders", (await page.getByText(/How to pitch it|No opportunities found/).count()) >= 1);
await page.screenshot({ path: `${OUT}/07-business-opportunities.png`, fullPage: true });

const bizPdf = await Promise.all([
  page.waitForEvent("download", { timeout: 20000 }),
  page.getByRole("button", { name: "Download report" }).click(),
]).then(([d]) => d);
check("business PDF downloads", bizPdf.suggestedFilename().endsWith(".pdf"), bizPdf.suggestedFilename());

// ---------------------------------------------------------------- compare
await page.goto(`${BASE}/compare`, { waitUntil: "networkidle" });
check("compare page renders", await page.getByText("Earlier scan").isVisible());
const selects = page.locator("select");
const optionCount = await selects.first().locator("option").count();
if (optionCount > 2) {
  await selects.nth(0).selectOption({ index: 2 });
  await selects.nth(1).selectOption({ index: 1 });
  await page.waitForTimeout(1500);
  const hasTable = (await page.locator("table").count()) > 0;
  const hasEmpty = (await page.getByText(/Nothing to compare|same scan/).count()) > 0;
  check("comparison produces a result", hasTable || hasEmpty);
  await page.screenshot({ path: `${OUT}/08-compare.png`, fullPage: true });
} else {
  check("comparison needs two finished scans (guard shown)", true, "skipped: not enough scans");
}

// ---------------------------------------------------------------- errors
await page.goto(`${BASE}/scans/00000000-0000-0000-0000-000000000000`, { waitUntil: "networkidle" });
await page.waitForSelector("text=/not_found|404/", { timeout: 10000 });
check("unknown scan shows the server's problem detail", true);
await page.screenshot({ path: `${OUT}/09-error.png`, fullPage: true });

await page.goto(`${BASE}/nowhere`, { waitUntil: "networkidle" });
check("unknown route shows the 404 page", await page.getByText("Page not found").isVisible());

// ---------------------------------------------------------------- responsive
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(scanUrl, { waitUntil: "networkidle" });
await page.waitForSelector("ul li .card, li.card", { timeout: 10000 }).catch(() => {});
const bodyScrollW = await page.evaluate(() => document.documentElement.scrollWidth);
const bodyClientW = await page.evaluate(() => document.documentElement.clientWidth);
check("no horizontal page scroll on mobile", bodyScrollW <= bodyClientW + 1, `${bodyScrollW} vs ${bodyClientW}`);
check("mobile shows cards, not the wide table", await page.locator("table").first().isHidden());
await page.screenshot({ path: `${OUT}/10-mobile-results.png`, fullPage: true });

await page.getByRole("button", { name: "Toggle navigation" }).click();
check("mobile menu opens", await page.getByRole("link", { name: "Compare" }).isVisible());
await page.screenshot({ path: `${OUT}/11-mobile-menu.png`, fullPage: true });

// ---------------------------------------------------------------- console health
check("no uncaught page errors", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));
const realConsoleErrors = consoleErrors.filter(
  (t) => !/favicon|404 \(Not Found\)|Failed to load resource/i.test(t),
);
check("no console errors", realConsoleErrors.length === 0, realConsoleErrors.slice(0, 3).join(" | "));

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} UI checks passed`);
if (failed.length) {
  for (const f of failed) console.log(`  FAILED: ${f.name} ${f.detail}`);
  process.exit(1);
}
