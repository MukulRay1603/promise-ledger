// Screenshot one element: node element-shot.mjs <url> <selector> <out.png> [width] [theme]
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";

const [url, selector, out, width = "1366", theme = "light"] = process.argv.slice(2);
const chrome = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-first-run"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: Number(width), height: 900, deviceScaleFactor: Number(process.env.DPR || 1), isMobile: Number(width) < 500 });
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: theme }, { name: "prefers-reduced-motion", value: "reduce" }]);
  await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
  await new Promise((r) => setTimeout(r, Number(process.env.WAIT_MS || 1500)));
  const el = await page.$(selector);
  if (!el) throw new Error(`no ${selector}`);
  await el.screenshot({ path: out });
  console.log("saved", out);
} finally {
  await browser.close();
}
