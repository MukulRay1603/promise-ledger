// Prints each county agreement's one-page brief to PDF and reports its page count.
//   node brief-check.mjs http://localhost:8780 <out-dir> [deal-id ...]
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] || "http://localhost:8780").replace(/\/$/, "");
const out = process.argv[3] || "briefs";
mkdirSync(out, { recursive: true });
const chrome = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-first-run"] });
let worst = 0;
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  let ids = process.argv.slice(4);
  if (!ids.length) {
    await page.goto(`${base}/api/county`);
    ids = JSON.parse(await page.evaluate(() => document.body.innerText)).deals.filter((d) => d.records_read).map((d) => d.id);
  }
  for (const id of ids) {
    await page.goto(`${base}/#/deals/${id}`, { waitUntil: "networkidle0" });
    await page.evaluate(() => { window.print = () => {}; document.getElementById("print-brief")?.remove(); });
    await page.waitForSelector(".brief-btn", { timeout: 15000 });
    await page.click(".brief-btn");
    await page.waitForSelector("#print-brief", { timeout: 15000 });
    await new Promise((r) => setTimeout(r, 400));
    await page.evaluate(() => document.body.classList.add("printing-brief"));
    await page.emulateMediaType("print");
    const pdf = await page.pdf({ path: join(out, `${id}.pdf`), format: "Letter", printBackground: false });
    // Newer Chrome writes page objects inside compressed object streams, so count with the pages tree when it is
    // visible, else from the printed sheet's height (Letter at 0.5in margins: 10in of 96px).
    const raw = pdf.toString("latin1");
    const seen = (raw.match(/\/Type\s*\/Page[^s]/g) || []).length || Number((raw.match(/\/Type\s*\/Pages[^>]*\/Count\s+(\d+)/) || [])[1] || 0);
    const tall = await page.evaluate(() => document.getElementById("print-brief").getBoundingClientRect().height);
    const pages = seen || Math.max(1, Math.ceil(tall / 960));
    worst = Math.max(worst, pages);
    console.log(`${pages === 1 ? "ok  " : "OVER"} ${pages} page(s)  ${id}`);
    await page.emulateMediaType(null);
  }
} finally {
  await browser.close();
}
process.exit(worst > 1 ? 1 : 0);
