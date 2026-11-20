// Full-page screenshots of every main view at desktop and phone width, for a visual layout review.
//   node shots.mjs http://localhost:8780 <out-dir> [tag]
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] || "http://localhost:8780").replace(/\/$/, "");
const out = process.argv[3] || "shots";
const tag = process.argv[4] || "";
mkdirSync(out, { recursive: true });
const chrome = process.env.CHROME_PATH || ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const routes = (process.env.SHOT_ROUTES || "#/,#/deals,#/county,#/deals/harbor-walk,#/deals/harbor-walk/changes,#/deals/harbor-walk/questions,#/deals/harbor-walk/receipt,#/deals/harbor-walk/ask,#/deals/holly-place-cr-044-2026,#/test,#/roadmap,#/about").split(",");
const sizes = (process.env.SHOT_SIZES || "desktop,phone").split(",").map((n) => n === "phone"
  ? { name: "phone", width: 390, height: 844, mobile: true } : { name: "desktop", width: 1366, height: 900 });
const theme = process.env.SHOT_THEME || "light";

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-first-run"] });
try {
  for (const size of sizes) {
    const page = await browser.newPage();
    await page.setViewport({ width: size.width, height: size.height, isMobile: Boolean(size.mobile), deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: theme }, { name: "prefers-reduced-motion", value: "reduce" }]);
    for (const route of routes) {
      await page.goto(`${base}/${route}`, { waitUntil: "networkidle0", timeout: 60000 });
      await new Promise((r) => setTimeout(r, 1500));
      const name = (route.replace(/[#/]+/g, "_").replace(/^_|_$/g, "") || "home") + `-${size.name}${tag ? "-" + tag : ""}.png`;
      if (process.env.SHOT_SLICES) {
        const h = await page.evaluate(() => document.documentElement.scrollHeight);
        for (let y = 0, i = 0; y < h; y += size.height, i++) {
          await page.screenshot({ path: join(out, name.replace(".png", `-${i}.png`)), clip: { x: 0, y, width: size.width, height: Math.min(size.height, h - y) }, captureBeyondViewport: true });
        }
      } else {
        await page.screenshot({ path: join(out, name), fullPage: true });
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      console.log(`${name}${overflow > 0 ? `  OVERFLOW ${overflow}px` : ""}`);
    }
    await page.close();
  }
} finally {
  await browser.close();
}
