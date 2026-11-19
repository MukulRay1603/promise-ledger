// Automated WCAG 2.1 A/AA checks with axe-core, in the system Chrome, on every main view at desktop and phone
// sizes, light and dark. Writes docs/accessibility/axe-report.json and docs/accessibility/AXE-SUMMARY.md.
//
//   cd tools/a11y && npm install && node check.mjs http://localhost:8779
//
// Automated checks find only part of the problems (Deque reports about 57% of issues by volume). Keyboard order,
// focus visibility and screen-reader wording are checked by hand: see docs/accessibility/MANUAL-CHECKS.md.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const base = (process.argv[2] || "http://localhost:8779").replace(/\/$/, "");
const chrome = process.env.CHROME_PATH || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find((p) => existsSync(p));
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const routes = (process.env.A11Y_ROUTES || [
  "#/", "#/deals", "#/county", "#/deals/harbor-walk", "#/deals/harbor-walk/changes", "#/deals/harbor-walk/questions",
  "#/deals/harbor-walk/receipt", "#/deals/harbor-walk/ask", "#/deals/holly-place-cr-044-2026", "#/test", "#/roadmap", "#/about",
].join(",")).split(",");
const sizes = [{ name: "desktop", width: 1280, height: 900 }, { name: "phone", width: 375, height: 812, mobile: true }];
const themes = ["light", "dark"];

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-first-run"] });
const results = [];
try {
  for (const size of sizes) for (const theme of themes) {
    const page = await browser.newPage();
    await page.setViewport({ width: size.width, height: size.height, isMobile: Boolean(size.mobile), deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: theme }, { name: "prefers-reduced-motion", value: "reduce" }]);
    for (const route of routes) {
      await page.goto(`${base}/${route}`, { waitUntil: "networkidle0", timeout: 60000 });
      await new Promise((r) => setTimeout(r, 1200)); // Let the hash route render.
      await page.evaluate(axeSource);
      const run = await page.evaluate(async () => {
        // eslint-disable-next-line no-undef
        const r = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
        return {
          violations: r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
            nodes: v.nodes.slice(0, 5).map((n) => ({ target: n.target.join(" "), summary: n.failureSummary })), count: v.nodes.length })),
          passes: r.passes.length, incomplete: r.incomplete.map((v) => ({ id: v.id, count: v.nodes.length })),
        };
      });
      results.push({ route, size: size.name, theme, ...run });
      const n = run.violations.reduce((s, v) => s + v.count, 0);
      console.log(`${n ? "FAIL" : "ok  "} ${size.name.padEnd(7)} ${theme.padEnd(5)} ${route}  ${n} issue(s)${n ? ": " + run.violations.map((v) => v.id).join(", ") : ""}`);
    }
    await page.close();
  }
} finally {
  await browser.close();
}

const out = join(root, "docs", "accessibility");
mkdirSync(out, { recursive: true });
const date = new Date().toISOString().slice(0, 10);
const axeVersion = JSON.parse(readFileSync(require.resolve("axe-core/package.json"), "utf8")).version;
writeFileSync(join(out, "axe-report.json"), JSON.stringify({ date, axe: axeVersion, base, results }, null, 2) + "\n");
const failing = results.filter((r) => r.violations.length);
const lines = [
  "# Automated accessibility results", "",
  `axe-core ${axeVersion}, WCAG 2.0/2.1 A and AA rules, run ${date} in Chrome by \`tools/a11y/check.mjs\`.`,
  `${routes.length} views × 2 sizes (1280 px, 375 px) × 2 themes = ${results.length} page checks, with reduced motion on.`, "",
  `**${results.length - failing.length} of ${results.length} page checks have no violations.**`, "",
  "| View | Size | Theme | Violations | Rules passed | Needs a person |", "|---|---|---|---|---|---|",
  ...results.map((r) => `| \`${r.route}\` | ${r.size} | ${r.theme} | ${r.violations.reduce((s, v) => s + v.count, 0) || "none"}` +
    `${r.violations.length ? " (" + r.violations.map((v) => v.id).join(", ") + ")" : ""} | ${r.passes} | ${r.incomplete.reduce((s, v) => s + v.count, 0)} |`),
  "", "Automated rules catch only part of accessibility problems. \"Needs a person\" counts items axe could not decide",
  "(usually contrast over gradients or images). Keyboard order, visible focus and screen-reader wording are checked by",
  "hand in [MANUAL-CHECKS.md](MANUAL-CHECKS.md).", "",
];
writeFileSync(join(out, "AXE-SUMMARY.md"), lines.join("\n"));
console.log(`\n${results.length - failing.length}/${results.length} page checks clean. Report: docs/accessibility/`);
process.exit(failing.length ? 1 : 0);
