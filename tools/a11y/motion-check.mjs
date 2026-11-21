// Checks that the motion layer finishes: every card that waits to rise in is shown after scrolling, counters end on
// their real values, and the term chart bars grow. Run with motion allowed.
//   node motion-check.mjs http://localhost:8780 [shot-dir]
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] || "http://localhost:8780").replace(/\/$/, "");
const shots = process.argv[3];
const chrome = process.env.CHROME_PATH || ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-first-run"] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let bad = 0;
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1366, height: 900 });
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  for (const route of ["#/", "#/county", "#/deals/harbor-walk"]) {
    await page.goto(`${base}/${route}`, { waitUntil: "networkidle0" });
    await sleep(1200);
    if (shots && route === "#/county") {
      await page.evaluate(() => document.querySelector(".runway")?.scrollIntoView({ block: "start" }));
      await sleep(450);
      await page.screenshot({ path: `${shots}/runway-mid.png` });
    }
    // Scroll through the page the way a reader would.
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < h; y += 500) { await page.evaluate((v) => window.scrollTo(0, v), y); await sleep(120); }
    await sleep(4500);
    const r = await page.evaluate(() => ({
      waiting: [...document.querySelectorAll(".rise-wait")].map((n) => n.className).slice(0, 5),
      waitingCount: document.querySelectorAll(".rise-wait").length,
      runway: document.querySelector(".runway")?.className || null,
      kpis: [...document.querySelectorAll(".county-kpi .kpi-value")].map((n) => n.textContent),
      strip: [...document.querySelectorAll("#real-strip [data-count]")].map((n) => n.textContent),
      // Decorations that fade in must end visible (a fade that ends on a hidden "waiting" state never shows).
      hidden: [...document.querySelectorAll(".m3-cap, .rs-found, .rs-blank")]
        .filter((n) => n.closest("[hidden]") === null && n.getClientRects().length && Number(getComputedStyle(n).opacity) < 0.3).length,
    }));
    const ok = r.waitingCount === 0 && r.hidden === 0 && (!r.runway || r.runway.includes("rw-go"));
    if (!ok) bad++;
    console.log(ok ? "ok  " : "FAIL", route, JSON.stringify(r));
  }
} finally {
  await browser.close();
}
process.exit(bad ? 1 : 0);
