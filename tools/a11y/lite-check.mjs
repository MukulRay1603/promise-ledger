// A device with 2 cores should get lite mode: no looping decoration, no spotlight. A fast one should not.
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] || "http://localhost:8780").replace(/\/$/, "");
const chrome = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome, headless: true });
let bad = 0;
try {
  for (const cores of [2, 16]) {
    const page = await browser.newPage();
    await page.evaluateOnNewDocument((c) => { Object.defineProperty(navigator, "hardwareConcurrency", { get: () => c }); Object.defineProperty(navigator, "deviceMemory", { get: () => (c > 4 ? 8 : 2) }); }, cores);
    await page.goto(`${base}/#/county`, { waitUntil: "networkidle0" });
    await page.evaluate(() => document.querySelector(".m3")?.scrollIntoView({ block: "center" }));
    await new Promise((r) => setTimeout(r, 3500));
    const r = await page.evaluate(() => ({
      lite: document.documentElement.classList.contains("lite"),
      sweep: getComputedStyle(document.querySelector(".m3-sweep")).display,
      beamsShown: [...document.querySelectorAll(".m3-cap")].filter((n) => Number(getComputedStyle(n).opacity) > 0.5).length,
    }));
    const ok = cores === 2 ? r.lite && r.sweep === "none" && r.beamsShown > 10 : !r.lite && r.sweep !== "none";
    if (!ok) bad++;
    console.log(`${ok ? "ok  " : "FAIL"} ${cores} cores`, JSON.stringify(r));
    await page.close();
  }
} finally {
  await browser.close();
}
process.exit(bad ? 1 : 0);
