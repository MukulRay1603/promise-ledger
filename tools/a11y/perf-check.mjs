// Load-time check on a low-end phone profile (4x slower CPU, slow 4G) and a fast desktop.
// Reports first paint, largest paint, layout shift, main-thread blocking (long tasks over 50 ms) and bytes.
//   node perf-check.mjs http://localhost:8780
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] || "http://localhost:8780").replace(/\/$/, "");
const chrome = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome"].find((p) => existsSync(p));
const profiles = [
  { name: "low-end phone", width: 390, height: 844, mobile: true, cpu: 4, net: { download: 1.6e6 / 8, upload: 750e3 / 8, latency: 150 } },
  { name: "desktop", width: 1440, height: 900, mobile: false, cpu: 1, net: null },
];
const routes = (process.env.PERF_ROUTES || "#/,#/county").split(",");
const browser = await puppeteer.launch({ executablePath: chrome, headless: true });
try {
  for (const p of profiles) for (const route of routes) {
    const page = await browser.newPage();
    await page.setViewport({ width: p.width, height: p.height, isMobile: p.mobile, deviceScaleFactor: p.mobile ? 2 : 1 });
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    const cdp = await page.createCDPSession();
    await cdp.send("Network.enable");
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    if (p.net) await cdp.send("Network.emulateNetworkConditions", { offline: false, downloadThroughput: p.net.download, uploadThroughput: p.net.upload, latency: p.net.latency });
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: p.cpu });
    let bytes = 0;
    const urls = {}, sizes = [];
    cdp.on("Network.responseReceived", (e) => { urls[e.requestId] = e.response.url; });
    cdp.on("Network.loadingFinished", (e) => { bytes += e.encodedDataLength; sizes.push([e.encodedDataLength, urls[e.requestId]]); });
    await page.evaluateOnNewDocument(() => {
      window.__perf = { lcp: 0, cls: 0, tbt: 0 };
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true });
      new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value; }).observe({ type: "layout-shift", buffered: true });
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.tbt += Math.max(0, e.duration - 50); }).observe({ type: "longtask", buffered: true });
    });
    const t0 = Date.now();
    await page.goto(`${base}/${route}`, { waitUntil: "networkidle0", timeout: 120000 });
    const loaded = Date.now() - t0;
    // Scroll through once, as a reader would, then let animations run.
    await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 150)); } });
    await new Promise((r) => setTimeout(r, 2500));
    const m = await page.evaluate(() => ({ fcp: performance.getEntriesByName("first-contentful-paint")[0]?.startTime || 0, ...window.__perf,
      lite: document.documentElement.classList.contains("lite") }));
    console.log(`${p.name.padEnd(13)} ${route.padEnd(9)} FCP ${(m.fcp / 1000).toFixed(2)}s  LCP ${(m.lcp / 1000).toFixed(2)}s  CLS ${m.cls.toFixed(3)}  ` +
      `blocking ${Math.round(m.tbt)}ms  loaded ${(loaded / 1000).toFixed(1)}s  ${Math.round(bytes / 1024)} KB${m.lite ? "  (lite)" : ""}`);
    if (process.env.PERF_LIST) sizes.sort((a, b) => b[0] - a[0]).slice(0, 8).forEach(([n, u]) => console.log(`    ${String(Math.round(n / 1024)).padStart(5)} KB  ${String(u).replace(base, "").slice(0, 90)}`));
    await page.close();
  }
} finally {
  await browser.close();
}
