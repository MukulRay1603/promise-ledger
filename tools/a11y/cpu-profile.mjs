// CPU profile of one page load (4x slower CPU); prints the functions with the most self time.
//   node cpu-profile.mjs http://localhost:8780/#/county
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";

const url = process.argv[2] || "http://localhost:8780/#/county";
const chrome = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome, headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, isMobile: true, deviceScaleFactor: 2 });
  const cdp = await page.createCDPSession();
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Profiler.enable");
  await cdp.send("Profiler.setSamplingInterval", { interval: 200 });
  await cdp.send("Profiler.start");
  await page.goto(url, { waitUntil: "networkidle0", timeout: 120000 });
  await new Promise((r) => setTimeout(r, 2000));
  const { profile } = await cdp.send("Profiler.stop");
  const dt = {};
  profile.timeDeltas.forEach((d, i) => { const id = profile.samples[i]; dt[id] = (dt[id] || 0) + d; });
  const self = {};
  for (const n of profile.nodes) {
    const f = n.callFrame;
    const key = `${f.functionName || "(anonymous)"} ${f.url.split("/").pop()}:${f.lineNumber + 1}`;
    self[key] = (self[key] || 0) + (dt[n.id] || 0) / 1000;
  }
  Object.entries(self).filter(([k]) => !k.startsWith("(idle)") && !k.startsWith("(program)"))
    .sort((a, b) => b[1] - a[1]).slice(0, 15).forEach(([k, ms]) => console.log(`${ms.toFixed(0).padStart(6)} ms  ${k}`));
} finally {
  await browser.close();
}
