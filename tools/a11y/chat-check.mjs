// Opens "Ask the county", asks a suggested question, and screenshots the answer.
//   node chat-check.mjs <base-url> <out.png> [width]
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const axeSource = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");

const [base = "http://localhost:8780", out = "chat.png", width = "1366"] = process.argv.slice(2);
const chrome = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome, headless: true });
try {
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log("pageerror", e.message));
  await page.setViewport({ width: Number(width), height: 860, deviceScaleFactor: 1.5, isMobile: Number(width) < 500 });
  await page.goto(`${base}/#/county`, { waitUntil: "networkidle0" });
  await page.click(".cc-launch");
  await page.waitForSelector(".cc-panel:not([hidden])");
  const focused = await page.evaluate(() => document.activeElement?.id);
  await page.click(".cc-topic, .cc-chip");
  await page.waitForFunction(() => !document.querySelector(".cc-pending") && document.querySelectorAll(".cc-bot:not(.cc-pending)").length >= 1, { timeout: 90000 });
  const info = await page.evaluate(() => ({ sentences: document.querySelectorAll(".cc-answer > li").length, links: document.querySelectorAll("a.cc-src").length,
    note: document.querySelector(".cc-bot:last-child .cc-note")?.textContent }));
  await page.evaluate(axeSource);
  const axe = await page.evaluate(async () => (await axe.run(".cc-panel", { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } })).violations.map((v) => `${v.id} x${v.nodes.length}`));
  console.log("axe on open panel:", axe.length ? axe.join(", ") : "0 issues");
  await (await page.$(".cc-panel")).screenshot({ path: out });
  await page.keyboard.press("Escape");
  const after = await page.evaluate(() => ({ closed: document.querySelector(".cc-panel").hidden, focus: document.activeElement?.className }));
  console.log(JSON.stringify({ focused, ...info, ...after }));
} finally {
  await browser.close();
}
