// Promise Ledger v1 interface. Hash routes: #/ home, #/deals, #/deals/{id}[/{tab}], #/r/{token} (also /r/{token}).
// Every figure comes from the API, which counts it from the records. Record text goes in through text nodes only.
const byId = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const STAGES = ["proposed", "supported", "signed", "delivered"];
const TAB_IDS = ["claims", "ask", "changes", "questions", "receipt", "extract", "glossary"];
const MAX_UPLOAD = 20 * 1024 * 1024;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// ---------- Small helpers ----------
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.flat(3).filter((child) => child !== null && child !== undefined && child !== false));
  return node;
}

function svg(viewBox, paths) {
  const root = document.createElementNS(SVG_NS, "svg");
  root.setAttribute("viewBox", viewBox);
  root.setAttribute("aria-hidden", "true");
  for (const [tag, attrs] of paths) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    root.append(node);
  }
  return root;
}

function formatDate(iso) {
  if (!iso) return "No date";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}
const daysFromToday = (iso) => Math.round((new Date(`${iso.slice(0, 10)}T00:00:00`) - new Date(new Date().toDateString())) / 86400000);
const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const stageLabel = (status) => (status ? status[0].toUpperCase() + status.slice(1) : "None yet");
// An agreement whose record shows no completed signature says so, so its terms are not read as signed.
const docLabel = (claim) => (/agreement/i.test(claim.document_type || "") && !["signed", "delivered"].includes(claim.status)
  ? `${claim.document_type} (not signed)` : claim.document_type);
const sourceShort = (claim) => `${docLabel(claim)} · ${formatDate(claim.date)} · p. ${claim.page}`;
const fileSize = (bytes) => (bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

const ICONS = {
  proposed: [["circle", { cx: 8, cy: 8, r: 6, "stroke-dasharray": "2.6 2.2" }]],
  supported: [["circle", { cx: 8, cy: 8, r: 6 }], ["path", { d: "M5.2 8h5.6" }]],
  signed: [["circle", { cx: 8, cy: 8, r: 6.5 }], ["path", { d: "M5 8.3l2 2 4-4.3" }]],
  delivered: [["path", { d: "M2.5 7.5 8 3l5.5 4.5V13h-11z" }], ["path", { d: "M6.5 13V9.5h3V13" }]],
  not_located: [["circle", { cx: 8, cy: 8, r: 6 }], ["path", { d: "M6.4 6.3a1.7 1.7 0 1 1 2.3 1.6c-.5.2-.7.6-.7 1.1v.4M8 11.4v.1" }]],
  differs: [["path", { d: "M3 6h10M3 10h10M10.5 3.2 5.5 12.8" }]],
  machine: [["path", { d: "M4 2h5.5L12 4.5V14H4z" }], ["path", { d: "M6 7.5h4M6 10.5h4" }]],
  ok: [["path", { d: "M3.5 8.5l3 3 6-7" }]],
  none: [["path", { d: "M4 8h8" }]],
};
const TAG_TEXT = { not_located: "Not located", differs: "Wording differs", machine: "Machine-extracted, verify at source", none: "None yet" };
const tag = (kind, text = TAG_TEXT[kind] || stageLabel(kind)) => el("span", { class: `tag tag-${kind}` }, svg("0 0 16 16", ICONS[kind] || []), text);

const quoteBadge = (claim) => (claim.quote_checked
  ? el("span", { class: "badge badge-ok" }, svg("0 0 16 16", ICONS.ok), "Quote found · ", el("span", { class: "mono" }, `p. ${claim.page}`))
  : el("span", { class: "badge badge-warn" }, svg("0 0 16 16", ICONS.not_located), "Flagged for human review · ", el("span", { class: "mono" }, `p. ${claim.page}`)));

const UI_ICONS = {
  upload: [["path", { d: "M12 16V4M7 9l5-5 5 5" }], ["path", { d: "M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" }]],
  sheet: [["rect", { x: 4, y: 3, width: 16, height: 18, rx: 2 }], ["path", { d: "M4 9h16M4 15h16M10 3v18" }]],
  file: [["path", { d: "M6 3h8l4 4v14H6z" }], ["path", { d: "M14 3v4h4M9 13h6M9 17h6" }]],
  link: [["path", { d: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" }], ["path", { d: "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
  arrow: [["path", { d: "M5 12h14M13 6l6 6-6 6" }]],
  ask: [["path", { d: "M4 5h16v11H9l-5 4z" }], ["path", { d: "M9 10h6M9 13h4" }]],
  share: [["circle", { cx: 18, cy: 5, r: 2.5 }], ["circle", { cx: 6, cy: 12, r: 2.5 }], ["circle", { cx: 18, cy: 19, r: 2.5 }], ["path", { d: "M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4" }]],
  print: [["path", { d: "M7 9V3h10v6M7 18H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" }], ["rect", { x: 7, y: 14, width: 10, height: 7 }]],
  calendar: [["rect", { x: 3, y: 5, width: 18, height: 16, rx: 2 }], ["path", { d: "M3 10h18M8 3v4M16 3v4" }]],
  docq: [["path", { d: "M6 3h8l4 4v14H6z" }], ["path", { d: "M10.3 11a1.8 1.8 0 1 1 2.4 1.7c-.5.2-.7.6-.7 1.1M12 17v.1" }]],
  bell: [["path", { d: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" }], ["path", { d: "M10 20a2 2 0 0 0 4 0" }]],
  check: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M8 12.5l2.5 2.5 5-5.5" }]],
  warn: [["path", { d: "M12 3 2 20h20z" }], ["path", { d: "M12 10v4M12 17v.1" }]],
  info: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M12 11v5M12 8v.1" }]],
  prev: [["path", { d: "M15 6l-6 6 6 6" }]],
  next: [["path", { d: "M9 6l6 6-6 6" }]],
  home: [["path", { d: "M3 11 12 4l9 7" }], ["path", { d: "M5 10v10h14V10" }], ["path", { d: "M10 20v-5h4v5" }]],
  refresh: [["path", { d: "M20 11a8 8 0 1 0-2.3 5.7" }], ["path", { d: "M20 5v6h-6" }]],
  code: [["path", { d: "M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14" }]],
  spark: [["path", { d: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" }], ["path", { d: "M19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" }]],
  copy: [["rect", { x: 9, y: 9, width: 11, height: 11, rx: 2 }], ["path", { d: "M5 15V5a1 1 0 0 1 1-1h10" }]],
  expand: [["path", { d: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" }]],
  shrink: [["path", { d: "M20 10h-6V4M4 14h6v6M14 10l7-7M10 14l-7 7" }]],
  x: [["path", { d: "M6 6l12 12M18 6 6 18" }]],
  menu: [["path", { d: "M4 7h16M4 12h16M4 17h16" }]],
  map: [["path", { d: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2z" }], ["path", { d: "M9 4v14M15 6v14" }]],
  road: [["path", { d: "M4 20 8 4M20 20 16 4M12 6v2M12 11v2M12 16v2" }]],
};
const icon = (name) => svg("0 0 24 24", UI_ICONS[name]);

// ---------- Toasts ----------
function toast(message, { kind = "ok", detail = null, timeout = 4500 } = {}) {
  const node = el("div", { class: `toast ${kind}` }, icon(kind === "ok" ? "check" : kind === "warn" ? "warn" : "info"),
    el("div", {}, el("p", {}, message), detail));
  byId("toasts").append(node);
  const remove = () => node.remove();
  let timer = setTimeout(remove, timeout);
  node.addEventListener("mouseenter", () => clearTimeout(timer));
  node.addEventListener("focusin", () => clearTimeout(timer));
  node.addEventListener("mouseleave", () => { timer = setTimeout(remove, 2500); });
  // Leaving the toast (or its link field) restarts the clock, so a focused toast cannot stay forever.
  node.addEventListener("focusout", (event) => { if (!node.contains(event.relatedTarget)) timer = setTimeout(remove, 2500); });
  node.append(el("button", { type: "button", class: "toast-close", "aria-label": "Dismiss", onclick: remove }, "×"));
  while (byId("toasts").children.length > 3) byId("toasts").firstElementChild.remove();
}

// ---------- API: the live server, or the in-browser mock until it is live ----------
class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
let mock = null;
let dealIsReal = false; // The open deal is a real county record: the nav marks County, and the banner says so.

// The banner says what the visitor is looking at: made-up demo data, or a real public record.
const BANNER_DEMO = "Demo deals use made-up data. Deals marked Real record are public records of Prince George's County, Maryland.";
const BANNER_REAL = "Real public records of Prince George's County, Maryland. Promise Ledger lists what the records say; it does not judge whether anyone met an obligation.";
function setBanner(real) {
  const banner = document.querySelector(".demo-banner");
  if (!banner) return;
  banner.classList.toggle("real-banner", Boolean(real));
  banner.querySelector("strong").textContent = real ? "Real records:" : "Demo:";
  byId("demo-banner").textContent = real ? BANNER_REAL : BANNER_DEMO;
}
let ready = null;

async function loadSeed() {
  const inline = byId("review-data");
  if (inline && inline.textContent.trim()) return JSON.parse(inline.textContent);
  const res = await fetch("/api/review");
  if (!res.ok) throw new ApiError(res.status, `The sample review did not load (${res.status}).`);
  return res.json();
}

async function detectMode() {
  const forceMock = new URLSearchParams(location.search).has("mock");
  if (!forceMock) {
    try {
      const res = await fetch("/api/deals", { headers: { Accept: "application/json" } });
      if (res.ok && (res.headers.get("content-type") || "").includes("json")) {
        document.documentElement.toggleAttribute("data-demo", res.headers.get("x-demo-mode") === "1");
        return "live";
      }
    } catch (err) { /* Not reachable. Use the mock. */ }
  }
  const [{ createMock }, seed] = await Promise.all([import("./mock.js"), loadSeed()]);
  mock = createMock(seed);
  return "mock";
}

// A random id this browser keeps. On sample deals the server keeps each browser's review apart with it.
let memorySession = null;
function demoSession() {
  const make = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join(""));
  try {
    let id = localStorage.getItem("pl-demo-session");
    if (!/^[A-Za-z0-9_-]{16,64}$/.test(id || "")) { id = make(); localStorage.setItem("pl-demo-session", id); }
    return id;
  } catch (err) {
    memorySession ||= make();
    return memorySession;
  }
}

// Term labels read "Homes" and "Income limit" everywhere, whatever an older server sends.
const PLAIN_LABELS = { units: "Homes", income_basis: "Income limit" };
function plainLabels(data) {
  if (!data || typeof data !== "object") return data;
  if (data.topics) Object.assign(data.topics, PLAIN_LABELS);
  for (const term of Array.isArray(data.terms) ? data.terms : []) if (PLAIN_LABELS[term.key]) term.label = PLAIN_LABELS[term.key];
  return data;
}

async function api(path, options = {}) { return plainLabels(await rawApi(path, options)); }

async function rawApi(path, { method = "GET", body = null, onProgress = null, reviewer = null } = {}) {
  await ready;
  if (mock) {
    try { return await mock.handle(method, path, body, { onProgress, reviewer, session: demoSession() }); } catch (err) { throw new ApiError(err.status || 500, err.message); }
  }
  if (body instanceof FormData) return uploadWithProgress(path, body, onProgress);
  const headers = { Accept: "application/json", "X-Demo-Session": demoSession() };
  if (body) headers["Content-Type"] = "application/json";
  if (reviewer) headers["X-Reviewer-Name"] = encodeURIComponent(reviewer); // Read by current_reviewer() on the server.
  // Self-healing: a read that hits a dropped connection or a busy server (502, 503, 504) is tried again twice,
  // after 0.4 s and 1.2 s. Writes are never repeated, so nothing is sent twice.
  let res;
  for (const wait of method === "GET" ? [400, 1200, null] : [null]) {
    try {
      res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : null });
      if (wait === null || ![502, 503, 504].includes(res.status)) break;
    } catch (err) {
      if (wait === null) throw new ApiError(0, navigator.onLine === false ? "You're offline." : "The server could not be reached.");
    }
    await new Promise((r) => setTimeout(r, wait));
  }
  const type = res.headers.get("content-type") || "";
  if (!res.ok) {
    let message = `The server returned ${res.status}.`;
    if (type.includes("json")) { const data = await res.json().catch(() => null); if (data?.detail) message = typeof data.detail === "string" ? data.detail : message; }
    throw new ApiError(res.status, message);
  }
  return type.includes("json") ? res.json() : res.blob();
}

function uploadWithProgress(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-Demo-Session", demoSession());
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => { if (event.lengthComputable) onProgress?.(event.loaded / event.total); });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else if (xhr.status === 413) reject(new ApiError(413, "The file is over 20 MB."));
      else reject(new ApiError(xhr.status, (xhr.response && typeof xhr.response.detail === "string" && xhr.response.detail) || `The upload failed (${xhr.status}).`));
    });
    xhr.addEventListener("error", () => reject(new ApiError(0, "The upload did not reach the server. Check the connection.")));
    xhr.send(form);
  });
}

const fileUrl = (dealId, docId) => (mock ? mock.fileUrl(dealId, docId) : `/api/deals/${encodeURIComponent(dealId)}/documents/${encodeURIComponent(docId)}/file`);

// ---------- Glossary ----------
const GLOSSARY = {
  deal: { title: "Deal", text: "Public support for one housing development: a tax abatement, PILOT, grant or land sale that a city or county gives a developer, and the affordable-housing commitments made in return. It is not a home for sale or rent." },
  ami: { title: "AMI (area median income)", text: "Area median income: the midpoint income for a metro area or county, from figures HUD publishes each year. Income limits are set as a percent of AMI (for example 60 or 80 percent) and adjusted for household size." },
  abatement: { title: "Tax abatement / PILOT", text: "A tax abatement lowers or delays property taxes for a set time. A PILOT (payment in lieu of taxes) replaces regular property taxes with an agreed payment. Cities often ask for affordable homes in return." },
  term: { title: "Affordability term", text: "How long the restrictions last, counted from a start date the agreement names (for example first occupancy, placed in service, or a fixed date)." },
  remedies: { title: "Remedies", text: "What the agreement says happens if a term is not met, such as cure periods, repayment of the tax benefit (clawback or recapture), penalties or ending the abatement." },
  stages: { title: "Stages", text: "Proposed: described as a plan or idea. Supported: recommended by staff or backed by a vote. Signed: stated in a record with at least one completed signature. Check who signed. A letter signed by one party is not an agreement signed by both. Delivered: a certificate or occupancy record states the homes were built, leased or certified. It reports what the record says; it is not an inspection. Each claim sits only at the stage its own record shows." },
  rent_limits: { title: "Rent limits", text: "The most rent allowed for a restricted home, usually based on HUD figures (often 30 percent of the income limit, adjusted for unit size)." },
  regulatory_agreement: { title: "Regulatory agreement", text: "A recorded contract between the owner and the public agency that sets the affordability terms." },
  deed_restriction: { title: "Deed restriction", text: "Affordability terms recorded against the property so they bind later owners." },
  compliance_certificate: { title: "Compliance certificate", text: "The owner's own yearly statement that it met the terms. It is not an inspection." },
  certificate_of_occupancy: { title: "Certificate of occupancy", text: "A building-department approval to occupy a building. It does not show who rents the homes or at what rent." },
  income_restricted: { title: "Income-restricted", text: "Homes limited to households at or below a set income." },
  not_located: { title: "Not located", text: "The item was not found in this packet. It may exist in a record that is not here. It is not a finding that the item is missing from the deal." },
};
const popoverSupported = typeof HTMLElement !== "undefined" && "popover" in HTMLElement.prototype;

function setupGlossaryPopovers() {
  if (!popoverSupported) return;
  byId("glossary-popovers").replaceChildren(...Object.entries(GLOSSARY).map(([key, entry]) => el("div", {
    class: "glossary-pop", id: `pop-${key}`, popover: "auto", role: "dialog", "aria-labelledby": `pop-${key}-title`,
  },
  el("h3", { id: `pop-${key}-title` }, entry.title),
  el("p", {}, entry.text),
  el("div", { class: "pop-actions" },
    el("button", { type: "button", class: "btn btn-secondary", onclick: () => { byId(`pop-${key}`).hidePopover(); openGlossary(key); } }, "Open glossary"),
    el("button", { type: "button", class: "btn btn-primary", popovertarget: `pop-${key}`, popovertargetaction: "hide" }, "Close")))));
}

function openGlossary(key) {
  if (!byId("glossary")) return;
  activateTab("glossary", { updateHash: true });
  const entry = byId(`g-${key}`);
  entry.scrollIntoView({ block: "center" });
  entry.focus({ preventScroll: true });
}

function termButton(key, text) {
  if (popoverSupported) {
    return el("button", { type: "button", class: "term", popovertarget: `pop-${key}` }, text, el("span", { class: "visually-hidden" }, " (definition)"));
  }
  return el("button", { type: "button", class: "term", onclick: () => openGlossary(key) }, text, el("span", { class: "visually-hidden" }, " (open glossary)"));
}

// A record type with a glossary entry ("Regulatory agreement", "Compliance certificate", ...) gets its definition on click.
function docType(type) {
  const key = String(type || "").toLowerCase().replace(/[^a-z]+/g, "_");
  return GLOSSARY[key] ? termButton(key, type) : type;
}

function withTerm(text, phrase, key) {
  const at = text.indexOf(phrase);
  if (at === -1) return [text];
  return [text.slice(0, at), termButton(key, phrase), text.slice(at + phrase.length)];
}

// ---------- Router ----------
let current = { view: null };
// Pages that are plain markup in index.html: route name -> title.
const STATIC_PAGES = { roadmap: "Roadmap", about: "About", test: "Help us test" };
let sampleId = "harbor-walk";

function parseRoute() {
  const pathMatch = location.pathname.match(/^\/r\/([\w.-]+)/);
  if (pathMatch) return { view: "shared", token: pathMatch[1] };
  let hash;
  try { hash = decodeURIComponent(location.hash.replace(/^#/, "")); } catch { return { view: "missing" }; } // "%E0%A4%A"
  if (!hash || hash === "/") return { view: "home" };
  if (TAB_IDS.includes(hash)) return { view: "deal", id: sampleId, tab: hash }; // Links from the earlier one-page version.
  if (!hash.startsWith("/")) return { view: "home" };
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "deals" && parts.length === 1) return { view: "deals" };
  if (parts[0] === "county" && parts.length === 1) return { view: "county" };
  if (STATIC_PAGES[parts[0]] && parts.length === 1) return { view: parts[0] };
  if (parts[0] === "deals" && parts[1] && parts[2] === "source" && parts[3]) return { view: "deal", id: parts[1], tab: "claims", source: parts[3] };
  if (parts[0] === "deals" && parts[1] && parts[2] === "tour") return { view: "deal", id: parts[1], tab: "claims", tour: true };
  if (parts[0] === "deals" && parts[1]) return { view: "deal", id: parts[1], tab: TAB_IDS.includes(parts[2]) ? parts[2] : null };
  if (parts[0] === "r" && parts[1]) return { view: "shared", token: parts[1] };
  return { view: "missing" };
}

function showView(view) {
  for (const section of document.querySelectorAll(".view")) section.hidden = section.dataset.view !== view;
  document.documentElement.classList.toggle("route-shared", view === "shared");
  document.documentElement.classList.toggle("route-app", view !== "home" && view !== "shared");
  // The county chat is offered on Home, County and every real county agreement, where it starts with that agreement.
  document.documentElement.classList.toggle("cc-on", view === "home" || view === "county" || (view === "deal" && dealIsReal));
  countyChat?.setContext(view === "deal" && dealIsReal && dealState?.deal ? { id: dealState.id, name: dealState.deal.name } : null);
  for (const link of document.querySelectorAll("[data-nav]")) {
    const on = link.dataset.nav === view || (view === "deal" && link.dataset.nav === (dealIsReal ? "county" : "deals"));
    if (on) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  placeNavIndicator();
  setMenu(false, { focus: false });
}

async function route({ initial = false } = {}) {
  const next = parseRoute();
  const sameDeal = next.view === "deal" && current.view === "deal" && current.id === next.id && dealState;
  if (sameDeal) {
    activateTab(next.tab || "claims", { focus: false });
    if (next.source) { openSourceFromLink(next.source); return; }
    if (next.tour) { history.replaceState(null, "", `#/deals/${encodeURIComponent(next.id)}`); startTour(); return; }
    if (next.tab) byId("tablist").scrollIntoView({ block: "start", behavior: reducedMotion.matches ? "auto" : "smooth" });
    current = next;
    return;
  }
  current = next;
  stopPolling();
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  dealIsReal = false; // renderDeal sets it once the deal has loaded.
  setBanner(next.view === "county");
  showView(next.view);
  if (!initial) {
    window.scrollTo(0, 0);
    byId("main").focus({ preventScroll: true });
  }
  if (next.view === "home") { document.title = "Promise Ledger"; setupVideos(); setupRealStrip(); if (!hero.running && hero.loops < HERO_LOOPS) heroPlay(); return; }
  if (STATIC_PAGES[next.view]) { document.title = `${STATIC_PAGES[next.view]} · Promise Ledger`; if (next.view === "test") setupTester(); return; }
  if (next.view === "deals") return renderDeals();
  if (next.view === "county") return renderCounty();
  if (next.view === "deal") return renderDeal(next.id, next.tab, next.source, next.tour);
  if (next.view === "shared") return renderShared(next.token);
  document.title = "Page not found · Promise Ledger";
}

// ---------- Recovery ----------
// A view that throws while rendering shows a card that says so, with Try again, instead of a blank page. If the
// browser is offline it tries again by itself when the connection returns.
let routeFailed = false;
async function safeRoute(options) {
  try {
    routeFailed = false;
    await route(options);
  } catch (err) {
    routeFailed = true;
    console.error(err);
    const view = document.querySelector(".view:not([hidden])") || byId("view-missing");
    const again = el("button", { type: "button", class: "btn btn-primary", onclick: () => safeRoute() }, "Try again");
    view.replaceChildren(el("div", { class: "empty recover" },
      el("h1", {}, "This page did not load"),
      el("p", {}, navigator.onLine === false ? "You're offline. It will load again as soon as you reconnect." : "Something went wrong while drawing it. Trying again usually fixes it."),
      el("div", { class: "page-actions" }, again, el("a", { class: "btn btn-secondary", href: "#/" }, "Go home"))));
    view.hidden = false;
  }
}
function setupConnectivity() {
  const bar = el("div", { class: "net-banner", role: "status", hidden: true }, icon("warn"), "You're offline. What's on screen stays; anything new loads when you reconnect.");
  document.body.prepend(bar);
  window.addEventListener("offline", () => { bar.hidden = false; });
  window.addEventListener("online", () => {
    bar.hidden = true;
    toast("Back online.");
    if (routeFailed || document.querySelector(".view:not([hidden]) .empty .btn")) safeRoute();
  });
  if (navigator.onLine === false) bar.hidden = false;
}

// ---------- Home ----------
// The server says where the videos live (MEDIA_BASE_URL or /static/media/) and which are present.
// Missing videos keep their placeholder. Ready ones get their thumbnail and open in the viewer dialog.
// Captions are burned into the videos, so the caption track is offered but off by default.
let videosSetUp = false;
const viewer = { list: [], index: 0, root: "/static/media/", cross: false, opener: null };
const clock = (secs) => secs ? `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}` : "";
// The overview video: a still until pressed, so YouTube loads only on request (privacy-enhanced domain).
const OVERVIEW_EMBED = "https://www.youtube-nocookie.com/embed/aD03n_4KfFc?autoplay=1&rel=0";
function setupOverview() {
  const play = byId("overview-play");
  if (!play || play.dataset.ready) return;
  play.dataset.ready = "1";
  play.addEventListener("click", () => {
    const frame = el("iframe", { src: OVERVIEW_EMBED, title: "Promise Ledger overview video", allow: "autoplay; encrypted-media; picture-in-picture; fullscreen",
      allowfullscreen: true, referrerpolicy: "strict-origin-when-cross-origin" });
    byId("overview-frame").replaceChildren(frame);
    frame.focus();
  });
}

async function setupVideos() {
  setupOverview();
  if (videosSetUp) return;
  videosSetUp = true;
  let list = [];
  try {
    const res = await fetch("/api/media", { headers: { Accept: "application/json" } });
    if (!res.ok) return;
    const data = await res.json();
    list = data.videos || [];
    viewer.root = data.base || viewer.root;
  } catch (err) { return; }
  viewer.cross = new URL(viewer.root, location.href).origin !== location.origin;
  viewer.list = list.filter((video) => video.ready);
  viewer.list.forEach((video, index) => {
    const card = document.querySelector(`[data-video="${video.slug}"]`);
    if (!card) return;
    const base = `${viewer.root}${video.slug}`;
    const open = el("button", { type: "button", class: "video-play", "aria-haspopup": "dialog",
      "aria-label": `Play ${video.title}${video.secs ? `, ${clock(video.secs)}` : ""}` },
      el("span", { class: "video-len" }, svg("0 0 24 24", [["path", { d: "M8 5v14l11-7z" }]]), video.secs ? clock(video.secs) : "Play"));
    open.addEventListener("click", () => openViewer(index, open));
    card.classList.add("is-ready");
    card.querySelector(".video-frame").replaceChildren(
      el("img", { src: `${base}.jpg`, alt: "", loading: "lazy", decoding: "async", width: 1280, height: 720 }), open);
  });
  buildStrip();
}

function buildStrip() {
  const strip = byId("vv-strip");
  strip.replaceChildren(...viewer.list.map((video, index) => el("li", {},
    el("button", { type: "button", class: "vv-thumb", "data-index": index, "aria-label": `${video.slug.slice(0, 2)}: ${video.title}` },
      el("img", { src: `${viewer.root}${video.slug}.jpg`, alt: "", loading: "lazy", decoding: "async", width: 160, height: 90 })))));
  strip.addEventListener("click", (event) => {
    const button = event.target.closest(".vv-thumb");
    if (button) showVideo(Number(button.dataset.index), true);
  });
}

function openViewer(index, opener) {
  viewer.opener = opener;
  byId("video-dialog").showModal();
  showVideo(index, true);
}

function showVideo(index, autoplay) {
  const count = viewer.list.length;
  if (!count) return;
  viewer.index = (index + count) % count;
  const video = viewer.list[viewer.index];
  const n = video.slug.slice(0, 2);
  const base = `${viewer.root}${video.slug}`;
  byId("vv-n").textContent = n;
  byId("vv-title").textContent = video.title;
  byId("vv-meta").textContent = [`Explainer ${Number(n)} of ${count}`, clock(video.secs), "Captions in the video"].filter(Boolean).join(" · ");
  const player = el("video", { controls: true, playsinline: true, preload: "metadata", poster: `${base}.jpg`,
    "aria-label": video.title, crossorigin: viewer.cross ? "anonymous" : null },
    el("source", { src: `${base}.mp4`, type: "video/mp4" }),
    el("track", { kind: "captions", srclang: "en", label: "English (text track)", src: `${base}.vtt` }));
  player.addEventListener("ended", () => showEnd());
  byId("vv-stage").replaceChildren(player);
  for (const button of byId("vv-strip").querySelectorAll(".vv-thumb")) {
    const on = Number(button.dataset.index) === viewer.index;
    button.toggleAttribute("aria-current", on);
    if (on) button.scrollIntoView({ block: "nearest", inline: "nearest", behavior: reducedMotion.matches ? "auto" : "smooth" });
  }
  byId("vv-prev").disabled = viewer.index === 0;
  byId("vv-next").disabled = viewer.index === count - 1;
  if (autoplay) {
    player.focus({ preventScroll: true });
    player.play().catch(() => { /* The browser may wait for a press. Controls are there. */ });
  }
}

function showEnd() {
  const next = viewer.list[viewer.index + 1];
  const card = el("div", { class: "vv-end" },
    el("p", { class: "vv-end-label" }, next ? "Up next" : "That's all eight"),
    next ? el("p", { class: "vv-end-title" }, next.title) : el("p", { class: "vv-end-title" }, "Try it on Harbor Walk"));
  const go = next
    ? el("button", { type: "button", class: "btn btn-primary" }, `Play ${next.slug.slice(0, 2)}`)
    : el("a", { class: "btn btn-primary", href: "#/deals/harbor-walk" }, "Open Harbor Walk");
  const again = el("button", { type: "button", class: "btn btn-secondary" }, "Watch again");
  if (next) go.addEventListener("click", () => showVideo(viewer.index + 1, true));
  again.addEventListener("click", () => showVideo(viewer.index, true));
  card.append(el("div", { class: "vv-end-actions" }, go, again));
  byId("vv-stage").append(card);
  go.focus();
}

function setupViewer() {
  const dialog = byId("video-dialog");
  byId("vv-close").addEventListener("click", () => dialog.close());
  byId("vv-prev").addEventListener("click", () => showVideo(viewer.index - 1, true));
  byId("vv-next").addEventListener("click", () => showVideo(viewer.index + 1, true));
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("keydown", (event) => {
    if (event.target.closest?.("video") || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowRight" && viewer.index < viewer.list.length - 1) { event.preventDefault(); showVideo(viewer.index + 1, true); }
    if (event.key === "ArrowLeft" && viewer.index > 0) { event.preventDefault(); showVideo(viewer.index - 1, true); }
  });
  dialog.addEventListener("close", () => {
    // Stop the download as well as the sound.
    const player = byId("vv-stage").querySelector("video");
    if (player) { player.pause(); player.removeAttribute("src"); player.replaceChildren(); player.load(); }
    byId("vv-stage").replaceChildren();
    viewer.opener?.focus();
  });
}

function fillHeroReceipt(review) {
  const signed = (key) => {
    const term = review.terms.find((item) => item.key === key);
    return term?.signed_claim_id ? review.claims.find((claim) => claim.id === term.signed_claim_id) : null;
  };
  const rows = [["units", "Homes"], ["income_basis", "Income limit"], ["term", "Term"], ["remedies", "Remedies"]].map(([key, label]) => {
    const claim = signed(key);
    const term = review.terms.find((item) => item.key === key);
    const value = claim ? el("span", { class: "rc-val" }, claim.value) : el("span", { class: "rc-val rc-muted" }, "No wording found");
    let badge = claim ? quoteBadge(claim) : el("span", { class: "badge badge-warn" }, svg("0 0 16 16", ICONS.not_located), "Not located");
    if (claim && term?.wording_differs) badge = el("span", { class: "badge badge-warn" }, svg("0 0 16 16", ICONS.differs), "Wording differs");
    return el("li", {}, el("span", { class: "rc-term" }, label), value, badge);
  });
  const card = byId("hero-receipt");
  const shown = card.querySelectorAll(".rc-rows li.on").length;
  if (card.classList.contains("assembling")) rows.forEach((row, index) => { if (!hero.running || card.classList.contains("done") || index < shown) row.classList.add("on"); });
  byId("hero-receipt-rows").replaceChildren(...rows);
  byId("hero-receipt-title").textContent = `${review.project} · ${review.city}`;
  byId("hero-receipt-checks").textContent = `${review.checks.passed} of ${review.checks.total}`;
}

// ---------- Deals ----------
const REMINDER_ICON = { term_end: "calendar", missing_record: "docq" };

// Days until the reminder is due: the server's count when it sends one (sample deals count from their
// "as of" date, so they read the same on any day), otherwise counted from today in the browser.
function reminderDays(item) {
  if (Number.isInteger(item?.days)) return item.days;
  const due = item?.due || item?.date;
  return due ? daysFromToday(due) : null;
}

function inDays(days) {
  if (days > 1) return `in ${days} days`;
  if (days === 1) return "tomorrow";
  if (days === 0) return "today";
  return `${plural(-days, "day")} ago`;
}

// Short, plain reminder wording built from the reminder's kind and date. The server's own sentence is the fallback.
function reminderText(item) {
  const due = item.due || item.date;
  if (!due) return item.text;
  const when = formatDate(due);
  const days = reminderDays(item);
  const past = days < 0;
  // Sample deals are read as of the file's date, not today, so the count always names its reference date.
  const asOf = item.as_of && item.as_of !== localToday() ? `, as of ${formatDate(item.as_of)}` : "";
  const count = days === null ? "" : ` · ${inDays(days)}${asOf}`;
  if (item.kind === "term_end") return `${past ? `Affordability term ended ${when}` : `Affordability term ends ${when}`}, per signed record${count}`;
  if (item.kind === "missing_record") return `Yearly certificate due ${when}: not located in this file${count}`;
  if (item.kind === "other") return `${past ? `Yearly certificate was due ${when}` : `Yearly certificate due ${when}`}${count}`;
  return item.text;
}

// The deals table has little room: what is due and when, then how far off. The Reminders list keeps the full text.
function reminderShort(item) {
  const due = item.due || item.date;
  if (!due) return [item.text, ""];
  const when = formatDate(due);
  const days = reminderDays(item);
  const what = { term_end: "Term ends", missing_record: "Certificate not on file, due", other: "Certificate due" }[item.kind];
  return [what ? `${what} ${when}` : item.text, days === null ? "" : inDays(days)];
}

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const sourceHref = (dealId, claimId) => `#/deals/${encodeURIComponent(dealId)}${claimId ? `/source/${encodeURIComponent(claimId)}` : ""}`;

// Four segments, filled up to the furthest stage. Decorative: the tag next to it says the stage in words.
function stageBar(status) {
  const reached = STAGES.indexOf(status) + 1;
  return el("span", { class: "stage-bar", "aria-hidden": "true" }, STAGES.map((stage, index) => el("span", { class: index < reached ? "on" : null })));
}

function flagCell(deal, next = null) {
  const items = [];
  if (deal.terms_differ) items.push(tag("differs", `${deal.terms_differ} differ`));
  if (deal.terms_not_located) items.push(tag("not_located", `${deal.terms_not_located} not located`));
  // Dates need attention too: a certificate past due and not in the file, or a term ending within a year.
  const days = next ? reminderDays(next) : null;
  if (next?.kind === "missing_record" && days !== null && days < 0) items.push(tag("not_located", "Certificate missing"));
  if (next?.kind === "term_end" && days !== null && days <= 365) items.push(tag("differs", days < 0 ? "Term ended" : days > 1 ? `Term ends in ${days} days` : "Term ends soon"));
  return items.length ? el("span", { class: "counts" }, items) : el("span", { class: "cell-muted" }, deal.documents ? "None" : "No documents yet");
}

function dealsSkeleton() {
  const line = (width) => el("span", { class: "skeleton sk-line", style: `width:${width}` });
  return [1, 2, 3].map(() => el("tr", {}, el("td", {}, line("10rem"), line("6rem")), el("td", {}, line("2rem")), el("td", {}, line("5rem")), el("td", {}, line("7rem")), el("td", {}, line("12rem"))));
}

async function renderDeals() {
  document.title = "Deals · Promise Ledger";
  const view = byId("view-deals");
  const tbody = el("tbody", {}, dealsSkeleton());
  const reminderList = el("ul", { class: "reminder-list", "aria-busy": "true" },
    [1, 2].map(() => el("li", { class: "reminder" }, el("span", { class: "skeleton reminder-ico" }), el("span", { class: "skeleton sk-line", style: "width:80%" }), el("span", { class: "skeleton sk-line", style: "width:50%" }))));
  const reminderCount = el("span", { class: "hint" });
  const modeNote = el("p", { class: "hint", hidden: true }, "Showing built-in sample deals because the deals service is not connected. Changes last until you reload.");

  view.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", { id: "deals-title" }, "Deals"), el("p", { class: "page-sub" }, "Developments that got a tax break or other public support, how far their affordable-housing commitments got, and what is due next.")),
      el("div", { class: "page-actions" }, el("button", { type: "button", class: "btn btn-primary", "data-new-deal": true }, icon("plus"), "New deal"))),
    el("div", { class: "deals-layout" },
      el("section", { class: "card deals-scroll", "aria-labelledby": "deals-table-cap" },
        el("table", { class: "deals-table stack", "aria-describedby": "deals-mode" },
          el("caption", { class: "visually-hidden", id: "deals-table-cap" }, "All deals"),
          el("thead", {}, el("tr", {}, ["Deal", "Documents", "Furthest stage (any term)", "Flags", "Next reminder"].map((text) => el("th", { scope: "col" }, text)))),
          tbody)),
      el("aside", { class: "card reminders", "aria-labelledby": "reminders-title" },
        el("div", { class: "card-head" }, el("h2", { id: "reminders-title" }, "Reminders"), reminderCount),
        reminderList)),
    el("div", { id: "deals-mode", style: "margin-top:1rem" }, modeNote),
  );

  let deals;
  let reminders;
  try {
    [deals, reminders] = await Promise.all([api("/api/deals"), api("/api/reminders").catch(() => [])]);
  } catch (err) {
    tbody.replaceChildren(el("tr", {}, el("td", { colspan: 5 }, `The deals did not load. ${err.message} Reload the page to try again.`)));
    reminderList.replaceChildren();
    return;
  }
  if (current.view !== "deals") return;
  modeNote.hidden = !mock;
  rememberSample(deals);
  // Real county deals have their own page; this table keeps the demo deals and the visitor's own.
  const realCount = deals.filter((deal) => deal.real).length;
  deals = deals.filter((deal) => !deal.real);
  reminders = (Array.isArray(reminders) ? reminders : []).filter((r) => deals.some((deal) => deal.id === r.deal_id));
  if (realCount) {
    view.querySelector(".page-head").after(el("a", { class: "card county-callout", href: "#/county" },
      el("span", { class: "real-badge" }, icon("check"), "Real records"),
      el("span", { class: "cc-text" }, el("b", {}, `${realCount} Prince George's County agreements`), " read from the County Council's own records"),
      el("span", { class: "cc-go", "aria-hidden": "true" }, "→")));
  }
  // The deal row's next reminder may lack the as-of date; the full reminder list has it for each deal.
  const asOfByDeal = new Map((Array.isArray(reminders) ? reminders : []).filter((r) => r.as_of).map((r) => [r.deal_id, r.as_of]));

  tbody.replaceChildren(...(deals.length ? deals.map((deal) => {
    const next = deal.next_reminder ? { as_of: asOfByDeal.get(deal.id) || deal.as_of, ...deal.next_reminder } : null;
    const docs = typeof deal.documents === "number" ? deal.documents : (deal.documents || []).length;
    return el("tr", {},
      el("th", { scope: "row", "data-label": "Deal" },
        el("a", { class: "deal-name", href: `#/deals/${encodeURIComponent(deal.id)}` }, deal.name),
        el("span", { class: "deal-city" }, deal.city)),
      el("td", { "data-label": "Documents" }, el("span", { class: "num" }, String(docs))),
      el("td", { "data-label": "Furthest stage (any term)" }, el("span", { class: "stage-cell" },
        deal.furthest_status ? tag(deal.furthest_status) : tag("none"), stageBar(deal.furthest_status))),
      el("td", { "data-label": "Flags" }, flagCell({ ...deal, documents: docs }, next)),
      el("td", { "data-label": "Next reminder", class: "reminder-cell", title: next ? reminderText(next) : null }, next
        ? [el("span", {}, reminderShort(next)[0]),
          el("span", { class: "reminder-when" }, reminderShort(next)[1]),
          deal.next_reminder.claim_id ? el("a", { class: "reminder-source", href: sourceHref(deal.id, deal.next_reminder.claim_id) }, "Source", el("span", { class: "visually-hidden" }, ` for ${deal.name} reminder`)) : null]
        : el("span", { class: "cell-muted" }, "None")));
  }) : [el("tr", {}, el("td", { colspan: 5 }, "No deals yet. Use New deal to add one."))]));

  reminderList.removeAttribute("aria-busy");
  reminderCount.textContent = plural(reminders.length, "item");
  reminderList.replaceChildren(...(reminders.length ? reminders.map((item) => el("li", { class: "reminder" },
    el("span", { class: `reminder-ico${item.kind === "term_end" ? "" : " soft"}` }, icon(REMINDER_ICON[item.kind] || "bell")),
    el("p", { class: "reminder-text" }, reminderText(item)),
    el("p", { class: "reminder-sub" },
      el("a", { href: `#/deals/${encodeURIComponent(item.deal_id)}` }, item.deal_name || "Open deal"),
      item.claim_id ? [" · ", el("a", { href: sourceHref(item.deal_id, item.claim_id) }, "Source", el("span", { class: "visually-hidden" }, ` for: ${reminderText(item)}`))] : null)))
    : [el("li", { class: "reminder" }, el("p", { class: "reminder-text" }, "Nothing due."))]));
}

// ---------- Home: real records strip ----------
// Live totals from the real county agreements, and one real quote of unfilled template text. Hidden if none are loaded.
let realStripDone = false;
async function setupRealStrip() {
  const first = !realStripDone;
  realStripDone = true;
  const strip = byId("real-strip");
  if (!strip) return;
  let board;
  try { board = await api("/api/county"); } catch { return; }
  const t = board?.totals;
  if (!t?.deals_read) return;
  strip.hidden = false;
  const values = { deals: t.deals_read, homes: t.homes, template_text: t.template_text };
  for (const dd of strip.querySelectorAll("[data-count]")) {
    const end = values[dd.dataset.count] || 0;
    if (!first) { dd.textContent = end.toLocaleString(); continue; }
    animateNumber(dd, end, 1100, (v) => Math.round(v).toLocaleString());
  }
  const effort = byId("rs-effort");
  if (effort && t.pages && t.cost_usd != null) {
    effort.replaceChildren(el("strong", {}, `${t.pages.toLocaleString()} pages`), " of council records: about ",
      el("strong", {}, `${Math.round((t.pages * PAGE_MINUTES) / 60)} hours`), ` to read by hand at ${PAGE_MINUTES} minutes a page, `,
      el("strong", { class: "rs-cost" }, `$${t.cost_usd.toFixed(2)}`), " to read them all here once.");
    effort.hidden = false;
  }
  const pick = board.deals.find((r) => r.template_text?.length);
  if (pick) {
    const q = pick.template_text[0];
    byId("rs-quote-text").textContent = `“${q.quote}”`;
    byId("rs-quote-cite").replaceChildren(
      el("a", { href: sourceHref(pick.id, q.claim_id) }, pick.name), `, ${q.document || "record"}${q.page ? `, p. ${q.page}` : ""} · council file ${pick.file}. `,
      el("span", { class: "rs-note" }, "Approved text that still holds a template blank."));
    byId("rs-quote").hidden = false;
    // The real page of that quote, when it is the agreement the picture was made from (tools: element-shot.mjs).
    const page = byId("rs-page");
    if (page && page.dataset.deal === pick.id) {
      page.hidden = false;
      if (!reducedMotion.matches && "IntersectionObserver" in window) {
        page.classList.add("rs-wait");
        const seen = new IntersectionObserver(([entry]) => {
          if (!entry.isIntersecting) return;
          page.classList.add("rs-go"); page.classList.remove("rs-wait"); seen.disconnect();
        }, { threshold: 0.4 });
        seen.observe(page);
      }
    }
  }
}

// ---------- Tester page (#/test) ----------
// Timed tasks and a short form. Times are measured by the page; nothing about the tester is sent unless they type it.
let testerReady = false;
function setupTester() {
  if (testerReady) return;
  testerReady = true;
  const form = byId("tester-form");
  const times = {};
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  for (const step of form.querySelectorAll("[data-timed]")) {
    const key = step.dataset.timed;
    const start = step.querySelector(".t-start"), stop = step.querySelector(".t-stop"), clock = step.querySelector(".t-clock");
    let began = 0, tick = null;
    start.addEventListener("click", () => {
      began = Date.now();
      start.disabled = true; stop.disabled = false; stop.focus();
      clearInterval(tick);
      tick = setInterval(() => { clock.textContent = fmt(Math.round((Date.now() - began) / 1000)); }, 1000);
    });
    stop.addEventListener("click", () => {
      clearInterval(tick);
      times[key] = Math.round((Date.now() - began) / 1000);
      clock.textContent = fmt(times[key]);
      stop.disabled = true; start.disabled = false; start.textContent = "Start again";
    });
  }
  const named = form.querySelector(".t-named");
  form.addEventListener("change", (event) => { if (event.target.name === "quote") named.hidden = event.target.value !== "named"; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const f = new FormData(form);
    const err = byId("t-error");
    if (!f.get("role")) { err.textContent = "Choose which describes you best (step 1)."; byId("t-role").focus(); return; }
    const num = (k) => (f.get(k) ? Number(f.get(k)) : null);
    const timed = (k) => ({ seconds: times[k] ?? null, found: f.get(`${k}_found`) || "skipped", answer: (f.get(`${k}_answer`) || "").trim() });
    const body = { role: f.get("role"), by_hand: timed("by_hand"), with_tool: timed("with_tool"), county_task: timed("county_task"),
      ask_rating: num("ask_rating"), easy_to_learn: num("easy_to_learn"), trust: num("trust"), would_use: num("would_use"),
      confusing: (f.get("confusing") || "").trim(), more_useful: (f.get("more_useful") || "").trim(), quote: f.get("quote") || "no",
      name: (f.get("name") || "").trim(), title: (f.get("title") || "").trim() };
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    err.textContent = "";
    try {
      await api("/api/feedback", { method: "POST", body });
      form.hidden = true;
      byId("tester-thanks").hidden = false;
      byId("tester-thanks").focus();
    } catch (e) {
      err.textContent = `Your answers were not sent. ${e.message} Try again.`;
    } finally {
      button.disabled = false;
    }
  });
}

// ---------- County board ----------
// Every PILOT agreement the Prince George's County Council considered since 2023, from its own records. Each number
// links back to checked quotes; "not found" means no wording was found in the records read, never a finding about
// a party.
const OBLIGATIONS = [
  ["reporting", "Reporting", "A yearly report or certification to the County"],
  ["remedies", "Remedies", "What happens if the terms are not met"],
  ["rent_limits", "Rent limit", "A cap on rents"],
  ["income_basis", "Income limit", "Who qualifies, as a share of area median income"],
  ["term", "Term", "How many years the homes stay affordable"],
];

// A label that fits the term chart: "New Carrollton - Affordable - Phase 1" → "New Carrollton Ph. 1",
// "Park Place at Addison Road Apartments" → "Park Place at Addison Rd". The full name stays in the title and label.
function shortDealName(name) {
  return name.replace(/\s+-\s+Affordable\s+-\s+Phase\s+/i, " Ph. ").replace(/\s+-\s+Affordable\s+-\s+/i, " · ")
    .replace(/\s+Apartments$/i, "").replace(/\bRoad\b/, "Rd");
}

function countyTimeline(rows) {
  // One bar per agreement from the Council's adoption to the end of its longest stated term, soonest first, so the
  // terms that run out first sit at the top. Amber bars end within 15 years: the window to plan for keeping them.
  const dated = rows.filter((r) => r.term_end).sort((a, b) => a.term_end.localeCompare(b.term_end));
  if (!dated.length) return null;
  const now = new Date().getFullYear();
  const yr = (iso) => Number(iso.slice(0, 4)) + (Number(iso.slice(5, 7)) - 1) / 12;
  const startOf = (r) => (r.passed ? yr(r.passed) : r.term_years ? yr(r.term_end) - r.term_years : now);
  const first = Math.floor(Math.min(now, ...dated.map(startOf)) / 5) * 5;
  const latest = Math.max(...dated.map((r) => yr(r.term_end)));
  const cap = Math.min(Math.ceil(latest / 10) * 10, Math.max(now + 50, 2080));
  const x = (y) => (100 * (Math.min(y, cap) - first)) / (cap - first);
  const ticks = [];
  for (let y = Math.ceil(first / 10) * 10; y <= cap; y += 10) ticks.push(y);
  const soonEnd = now + 15;
  const fig = el("figure", { class: "runway" },
    el("figcaption", { class: "rw-head" },
      el("div", {},
        el("h2", { id: "county-timeline-title" }, "How long each agreement's homes stay affordable"),
        el("p", { class: "hint" }, "Each bar runs from the Council's adoption to the end of the longest term the records state. A year with + is counted from adoption, so the real end is then or later. Amber bars run out within 15 years.")),
      el("a", { class: "btn btn-secondary btn-small", href: "/api/reminders.ics?county=1", download: "prince-georges-terms.ics" }, icon("calendar"), "Add end dates to a calendar")),
    el("div", { class: "rw-chart" },
      el("div", { class: "rw-grid", "aria-hidden": "true" },
        el("span", { class: "rw-window", style: `left:${x(now)}%;width:${x(soonEnd) - x(now)}%` }, el("span", {}, "Next 15 years")),
        ...ticks.map((y) => el("span", { class: `rw-tick${y % 20 ? " rw-minor" : ""}`, style: `left:${x(y)}%` }, el("span", {}, String(y)))),
        el("span", { class: "rw-today", style: `left:${x(now)}%` }, el("span", {}, "Today"))),
      el("ol", { class: "rw-rows", "aria-labelledby": "county-timeline-title" },
        ...dated.map((r, i) => {
          const endY = yr(r.term_end);
          const soon = Number(r.term_end.slice(0, 4)) <= soonEnd;
          const est = r.term_end_estimated;
          const over = endY > cap;
          const left = x(startOf(r));
          const label = `${r.term_end.slice(0, 4)}${est ? "+" : ""}`;
          return el("li", { class: `rw-row${soon ? " rw-soon" : ""}${est ? " rw-est" : ""}${over ? " rw-over" : ""}`, style: `--i:${i}` },
            el("a", { class: "rw-name", href: `#/deals/${encodeURIComponent(r.id)}`, title: r.name,
              "aria-label": `${r.name}: ${r.term_years ? `${r.term_years}-year term, ` : ""}runs to ${est ? `about ${r.term_end.slice(0, 4)} or later` : formatDate(r.term_end)}${r.homes ? `, ${plural(r.homes, "affordable home")}` : ""}` }, shortDealName(r.name)),
            el("span", { class: "rw-track", "aria-hidden": "true" },
              el("span", { class: "rw-bar", style: `left:${left}%;width:${Math.max(1, x(endY) - left)}%` }),
              el("span", { class: "rw-end", style: `left:${x(endY)}%` }, over ? `${label} →` : label)));
        }))));
  if (!reducedMotion.matches && "IntersectionObserver" in window) {
    fig.classList.add("rw-wait");
    const seen = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      fig.classList.add("rw-go");
      seen.disconnect();
    }, { threshold: 0.15 });
    requestAnimationFrame(() => seen.observe(fig));
  }
  return fig;
}

// ---------- County map ----------
// Each agreement at the property address its own records state (record and page shown), sized by the affordable
// homes stated, amber when the stated term runs out by 2040. Deals whose records state no street address are listed,
// never placed by guess.
const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  node.append(...kids.filter((k) => k != null));
  return node;
}
function countyMap(board) {
  // A tilted night view of the county: the land as a raised slab, the highways people navigate by, and a column of
  // light at each agreement, as tall as the affordable homes its records state. Pins come only from addresses the
  // records state; nothing here is placed by guess.
  const m = board.map;
  const placed = board.deals.filter((r) => r.location?.lat);
  if (!m?.shapes || !placed.length) return null;
  const TILT = 0.6, W = 760, TOP = 120, DEPTH = 14;
  const lons = placed.map((r) => r.location.lon), lats = placed.map((r) => r.location.lat);
  const padLon = Math.max(0.05, 0.3 * (Math.max(...lons) - Math.min(...lons)));
  const padLat = Math.max(0.04, 0.3 * (Math.max(...lats) - Math.min(...lats)));
  const [minLon, maxLon, minLat, maxLat] = [Math.min(...lons) - padLon, Math.max(...lons) + padLon, Math.min(...lats) - padLat, Math.max(...lats) + padLat];
  const k = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const scale = W / ((maxLon - minLon) * k);
  const H = Math.round(TOP + (maxLat - minLat) * scale * TILT + 24);
  const P = (lon, lat) => [(lon - minLon) * k * scale, TOP + (maxLat - lat) * scale * TILT];
  const d = (rings, dy = 0) => rings.map((ring) => "M" + ring.map(([x, y]) => { const [a, b] = P(x, y); return `${a.toFixed(1)},${(b + dy).toFixed(1)}`; }).join("L") + "Z").join("");
  const line = (pts) => "M" + pts.map(([x, y]) => P(x, y).map((v) => v.toFixed(1)).join(",")).join("L");
  const county = m.shapes["Prince George's County"] || [], dc = m.shapes["Washington, DC"] || [];
  const maxHomes = Math.max(1, ...placed.map((r) => r.homes || 0));
  const uid = `m${Math.random().toString(36).slice(2, 7)}`;

  // Grid lines every 0.02 degrees, clipped to the county top face.
  const grid = [];
  for (let lon = Math.ceil(minLon / 0.02) * 0.02; lon < maxLon; lon += 0.02) grid.push(line([[lon, minLat - 0.2], [lon, maxLat + 0.2]]));
  for (let lat = Math.ceil(minLat / 0.02) * 0.02; lat < maxLat; lat += 0.02) grid.push(line([[minLon - 0.2, lat], [maxLon + 0.2, lat]]));

  const roads = Object.entries(m.roads || {}).map(([name, r]) => ({ name, kind: r.kind, d: r.lines.map(line).join("") }));
  // One shield per route, on its longest stretch inside the frame.
  const inView = ([x, y]) => x > 40 && x < W - 40 && y > TOP + 10 && y < H - 30;
  const inside = ([lon, lat], rings) => rings.some((ring) => {
    let hit = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  });
  const shields = Object.entries(m.roads || {}).filter(([, r]) => r.kind !== "state").map(([name, r]) => {
    const pts = r.lines.flat().filter((pt) => !inside(pt, dc)).map(([x, y]) => P(x, y)).filter(inView);
    return pts.length > 6 ? { name, kind: r.kind, at: pts[Math.floor(pts.length / 2)] } : null;
  }).filter(Boolean);
  let places = Object.entries(m.places || {}).map(([name, [lon, lat]]) => ({ name, at: P(lon, lat) })).filter((p) => inView(p.at));

  // Agreements at the same site fan out; beams are drawn back to front.
  const seen = {};
  const pins = placed.map((r, i) => {
    const key = `${r.location.lat.toFixed(3)},${r.location.lon.toFixed(3)}`;
    const n = (seen[key] = (seen[key] || 0) + 1) - 1;
    let [x, y] = P(r.location.lon, r.location.lat);
    if (n) { x += 12 * Math.cos(n * 2.1); y += 7 * Math.sin(n * 2.1); }
    return { r, x, y, i, soon: Boolean(r.term_end && r.term_end < "2041-01-01"), h: 18 + 92 * Math.sqrt((r.homes || 0) / maxHomes) };
  }).sort((a, b) => a.y - b.y);
  // Labels never sit under a column or on top of each other: a town label is dropped near a site, and a home count
  // shows only where it fits (largest first); every count still shows on hover or focus.
  places = places.filter((pl) => pins.every((p) => Math.abs(pl.at[0] + 28 - p.x) > 34 || pl.at[1] < p.y - p.h - 12 || pl.at[1] > p.y + 10));
  const taken = [];
  for (const p of [...pins].sort((a, b) => (b.r.homes || 0) - (a.r.homes || 0))) {
    const box = [p.x - 13, p.y - p.h - 20, p.x + 13, p.y - p.h - 6];
    p.label = !taken.some((t) => box[0] < t[2] && box[2] > t[0] && box[1] < t[3] && box[3] > t[1]);
    if (p.label) taken.push(box);
  }

  const hud = el("div", { class: "m3-hud", "aria-live": "polite" });
  let svg;
  const show = (p) => {
    const r = p.r, loc = r.location;
    hud.replaceChildren(
      el("p", { class: "m3-hud-kicker" }, p.soon ? "Term ends by 2040" : "Agreement"),
      el("p", { class: "m3-hud-name" }, r.name),
      el("p", { class: "m3-hud-addr" }, `${loc.address}${loc.city ? `, ${loc.city}` : ""}`, loc.approx ? " · street located" : ""),
      el("dl", { class: "m3-hud-facts" },
        el("div", {}, el("dt", {}, "Affordable homes"), el("dd", {}, r.homes ? `${r.homes_approx ? "Over " : ""}${r.homes.toLocaleString()}` : "Not stated")),
        el("div", {}, el("dt", {}, "Stated term to"), el("dd", { class: p.soon ? "m3-amber" : "" }, r.term_end ? `${r.term_end.slice(0, 4)}${r.term_end_estimated ? "+" : ""}` : "Not stated")),
        el("div", {}, el("dt", {}, "Key terms found"), el("dd", {}, `${Object.values(r.found).filter(Boolean).length} of ${Object.keys(r.found).length}`))),
      el("p", { class: "m3-hud-src" }, `Council file ${r.file || "—"} · address from ${loc.record}, p. ${loc.page}`),
      el("a", { class: "m3-hud-go", href: `#/deals/${encodeURIComponent(r.id)}` }, "Open the agreement", icon("arrow")));
    svg?.querySelectorAll(".m3-pin").forEach((g) => g.classList.toggle("on", g === p.node));
  };

  svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "m3-svg", role: "group", "aria-labelledby": "county-map-title" },
    svgEl("defs", {},
      svgEl("linearGradient", { id: `${uid}-beam`, x1: "0", y1: "1", x2: "0", y2: "0" },
        svgEl("stop", { offset: "0", "stop-color": "#5EEAD4", "stop-opacity": ".95" }), svgEl("stop", { offset: "1", "stop-color": "#5EEAD4", "stop-opacity": "0" })),
      svgEl("linearGradient", { id: `${uid}-beam-soon`, x1: "0", y1: "1", x2: "0", y2: "0" },
        svgEl("stop", { offset: "0", "stop-color": "#FBBF24", "stop-opacity": ".95" }), svgEl("stop", { offset: "1", "stop-color": "#FBBF24", "stop-opacity": "0" })),
      svgEl("linearGradient", { id: `${uid}-land`, x1: "0", y1: "0", x2: "1", y2: "1" },
        svgEl("stop", { offset: "0", "stop-color": "#123B44" }), svgEl("stop", { offset: "1", "stop-color": "#0C2530" })),
      svgEl("filter", { id: `${uid}-glow`, x: "-100%", y: "-100%", width: "300%", height: "300%" },
        svgEl("feGaussianBlur", { stdDeviation: "3", result: "b" }), svgEl("feMerge", {}, svgEl("feMergeNode", { in: "b" }), svgEl("feMergeNode", { in: "SourceGraphic" }))),
      svgEl("clipPath", { id: `${uid}-clip` }, svgEl("path", { d: d(county) }))),
    svgEl("g", { class: "m3-terrain", "aria-hidden": "true" },
      svgEl("path", { class: "m3-dc", d: d(dc) }),
      svgEl("path", { class: "m3-side", d: d(county, DEPTH) }),
      svgEl("path", { class: "m3-land", d: d(county), fill: `url(#${uid}-land)` }),
      svgEl("g", { "clip-path": `url(#${uid}-clip)` }, svgEl("path", { class: "m3-grid", d: grid.join("") })),
      svgEl("path", { class: "m3-edge-glow", d: d(county) }),
      svgEl("path", { class: "m3-edge", d: d(county), pathLength: "1" }),
      ...roads.map((r) => svgEl("path", { class: `m3-road m3-${r.kind}`, d: r.d, pathLength: "1" })),
      ...places.map((p) => svgEl("g", { class: "m3-place" }, svgEl("circle", { cx: p.at[0].toFixed(1), cy: p.at[1].toFixed(1), r: "1.8" }),
        svgEl("text", { x: (p.at[0] + 5).toFixed(1), y: (p.at[1] + 3).toFixed(1) }, p.name.toUpperCase()))),
      ...shields.map((s) => svgEl("g", { class: `m3-shield m3-${s.kind}`, transform: `translate(${s.at[0].toFixed(1)} ${s.at[1].toFixed(1)})` },
        svgEl("rect", { x: -16, y: -8, width: 32, height: 16, rx: s.kind === "interstate" ? 4 : 8 }),
        svgEl("text", { y: 3.5, "text-anchor": "middle" }, s.name))),
      (() => { const [x, y] = P(minLon + 0.012, 38.9); return svgEl("text", { class: "m3-dc-label", x: x.toFixed(1), y: y.toFixed(1) }, "WASHINGTON, DC"); })()),
    ...pins.map((p) => {
      const g = svgEl("a", { class: `m3-pin${p.soon ? " m3-soon" : ""}${p.r.location.approx ? " m3-approx" : ""}`, href: `#/deals/${encodeURIComponent(p.r.id)}`,
        style: `--i:${p.i}`,
        "aria-label": `${p.r.name}: ${p.r.homes ? plural(p.r.homes, "affordable home") : "home count not stated"}, ${p.r.location.address}${p.r.term_end ? `, stated term to ${p.r.term_end.slice(0, 4)}` : ""}` },
        svgEl("ellipse", { class: "m3-ring", rx: 13, ry: 13 * TILT }),
        svgEl("ellipse", { class: "m3-base", rx: 7, ry: 7 * TILT }),
        svgEl("rect", { class: "m3-beam", x: -3, y: -p.h, width: 6, height: p.h, rx: 3, fill: `url(#${uid}-beam${p.soon ? "-soon" : ""})` }),
        svgEl("circle", { class: "m3-halo", cy: -p.h, r: 8 }),
        svgEl("circle", { class: "m3-cap", cy: -p.h, r: 4.2 }),
        p.r.homes ? svgEl("text", { class: `m3-num${p.label ? "" : " m3-num-hide"}`, y: -p.h - 9, "text-anchor": "middle" }, p.r.homes.toLocaleString()) : null,
        svgEl("ellipse", { class: "m3-hit", rx: 14, ry: 14, cy: -p.h / 2, "fill-opacity": 0 }));
      p.node = g;
      g.addEventListener("mouseenter", () => show(p));
      g.addEventListener("focus", () => show(p));
      return svgEl("g", { transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})` }, g);
    }));

  show(pins.reduce((a, b) => ((b.r.homes || 0) > (a.r.homes || 0) ? b : a)));
  const missing = board.deals.filter((r) => !r.location?.lat);
  const fig = el("section", { class: "county-map m3", "aria-labelledby": "county-map-title" },
    el("div", { class: "m3-head" },
      el("div", {},
        el("p", { class: "m3-kicker" }, el("span", { class: "m3-live", "aria-hidden": "true" }), "Prince George's County · live from public records"),
        el("h2", { id: "county-map-title" }, "Where the homes are"),
        el("p", { class: "m3-sub" }, `${placed.length} of ${board.deals.length} agreements at the address their own records state. Each column of light is as tall as the affordable homes stated; amber terms end by 2040.`)),
      el("p", { class: "m3-total", "aria-hidden": "true" }, el("span", {}, placed.reduce((s, p) => s + (p.homes || 0), 0).toLocaleString()), " homes on the map")),
    el("div", { class: "m3-body" },
      el("div", { class: "m3-stage" }, svg,
        el("span", { class: "m3-sweep", "aria-hidden": "true" }),
        el("p", { class: "m3-legend", "aria-hidden": "true" },
          el("span", {}, el("i", { class: "k-teal" }), "Term past 2040"),
          el("span", {}, el("i", { class: "k-amber" }), "Term ends by 2040"),
          el("span", {}, el("i", { class: "k-road" }), "Interstate"),
          el("span", {}, el("i", { class: "k-approx" }), "Street located"))),
      el("div", { class: "m3-side-col" }, hud,
        missing.length ? el("div", { class: "m3-missing" },
          el("p", { class: "m3-m-title" }, `Not on the map (${missing.length})`),
          el("p", {}, "Their records state no street address, so they are not placed by guess."),
          el("ul", {}, ...missing.map((r) => el("li", {}, el("a", { href: `#/deals/${encodeURIComponent(r.id)}` }, r.name))))) : null)),
    el("p", { class: "m3-credit" }, "Addresses from the records. Located with the U.S. Census Geocoder",
      placed.some((r) => r.location.geocoder?.includes("OpenStreetMap")) ? "; street-level ones with OpenStreetMap (© OpenStreetMap contributors)" : "",
      ". Outlines, highways and places: U.S. Census Bureau."));
  if (!reducedMotion.matches && "IntersectionObserver" in window) {
    fig.classList.add("m3-wait");
    const io = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      fig.classList.add("m3-go"); fig.classList.remove("m3-wait"); io.disconnect();
    }, { threshold: 0.2 });
    requestAnimationFrame(() => io.observe(fig));
  }
  return fig;
}

// Reading the council records by hand, next to what one read here cost. Pages and cost are counted; the hours are
// an estimate at a stated pace, labeled as such.
const PAGE_MINUTES = 2;
function countyEffort(t) {
  if (!t.pages || t.cost_usd == null) return null;
  const hours = Math.round((t.pages * PAGE_MINUTES) / 60);
  const counters = [];
  const fact = (value, fmt, label, sub, tone = "") => {
    const n = el("span", { class: "ef-n" }, fmt(value));
    counters.push([n, value, fmt]);
    return el("div", { class: `ef-fact ${tone}` }, el("p", { class: "ef-v" }, n), el("p", { class: "ef-l" }, label), el("p", { class: "ef-s" }, sub));
  };
  const box = el("section", { class: "effort", "aria-label": "By hand compared with Promise Ledger" },
    fact(t.pages, (v) => Math.round(v).toLocaleString(), "pages of council records", `${t.records} records, ${t.deals} agreements`),
    el("span", { class: "ef-arrow", "aria-hidden": "true" }, "→"),
    fact(hours, (v) => `≈${Math.round(v)} h`, "to read them by hand", `at ${PAGE_MINUTES} minutes a page (an estimate)`, "ef-hand"),
    el("span", { class: "ef-arrow", "aria-hidden": "true" }, "vs"),
    fact(t.cost_usd, (v) => `$${v.toFixed(2)}`, "to read them all here, once", "total model cost; every quote then checked by code", "ef-tool"));
  requestAnimationFrame(() => { for (const [n, v, f] of counters) animateNumber(n, v, 1100, f); });
  return box;
}

// Search every checked quote across the county agreements. Results are quotes found word for word on their page.
const TOPIC_LABEL = { units: "Homes", income_basis: "Income limit", rent_limits: "Rent limits", term: "Term", responsible_party: "Responsible party", reporting: "Reporting", remedies: "Remedies" };
const SEARCH_EXAMPLES = ["how long must the homes stay affordable", "annual income certification", "what if the owner sells the property", "penalty if the owner defaults"];
function countySearch() {
  const input = el("input", { type: "search", id: "county-q", maxlength: "200", autocomplete: "off",
    placeholder: "e.g. how long must the homes stay affordable", "aria-describedby": "county-search-note" });
  const note = el("p", { class: "hint", id: "county-search-note", role: "status" },
    "Finds matching sentences in every agreement's checked quotes.");
  const list = el("ol", { class: "search-results" });
  let seq = 0;
  const run = async (q) => {
    q = q.trim();
    if (!q) { list.replaceChildren(); return; }
    const mine = ++seq;
    note.textContent = "Searching…";
    try {
      const res = await api(`/api/county/search?q=${encodeURIComponent(q)}`);
      if (mine !== seq) return;
      note.textContent = res.results.length ? `${plural(res.results.length, "match", "matches")}. ${res.notice}` : `No checked quote matches “${q}”. ${res.notice}`;
      list.replaceChildren(...res.results.map((r) => el("li", {},
        el("a", { class: "sr-quote", href: sourceHref(r.deal_id, r.claim_id) }, `“${r.quote}”`),
        el("p", { class: "sr-meta" }, el("a", { href: `#/deals/${encodeURIComponent(r.deal_id)}` }, r.deal), ` · ${r.file} · ${r.document || "Record"}`,
          r.page ? ` · p. ${r.page}` : "", ` · ${TOPIC_LABEL[r.topic] || r.topic}`))));
    } catch (err) {
      if (mine === seq) note.textContent = `Search did not run. ${err.message}`;
    }
  };
  const form = el("form", { class: "county-search", role: "search", "aria-label": "Search the county agreements",
    onsubmit: (event) => { event.preventDefault(); run(input.value); } },
    el("label", { for: "county-q" }, "Search every agreement"),
    el("div", { class: "cs-row" }, input, el("button", { type: "submit", class: "btn btn-primary" }, "Search")),
    el("div", { class: "cs-examples" }, el("span", { class: "hint" }, "Try:"),
      ...SEARCH_EXAMPLES.map((q) => el("button", { type: "button", class: "q-chip", onclick: () => { input.value = q; run(q); } }, q))));
  return el("section", { class: "card county-search-card", "aria-label": "Search" }, form, note, list);
}

// Quick filters for the table: each shows only the agreements a busy reviewer would look at first.
const COUNTY_FILTERS = [
  ["all", "All"],
  ["no-reporting", "No reporting wording"],
  ["no-remedies", "No remedy wording"],
  ["blanks", "Template blanks"],
  ["soon", "Terms run out by 2040"],
];
function countyFlags(r) {
  if (!r.records_read) return [];
  return [
    !r.found.reporting && "no-reporting",
    !r.found.remedies && "no-remedies",
    r.template_text?.length && "blanks",
    r.term_end && r.term_end < "2041-01-01" && "soon",
  ].filter(Boolean);
}
function countyFilters(rows) {
  const count = (key) => (key === "all" ? rows.length : rows.filter((r) => countyFlags(r).includes(key)).length);
  const status = el("p", { class: "visually-hidden", role: "status" });
  const group = el("div", { class: "county-filters", role: "group", "aria-label": "Show agreements" },
    ...COUNTY_FILTERS.map(([key, label]) => el("button", { type: "button", class: "q-chip", "aria-pressed": String(key === "all"),
      onclick: (event) => {
        group.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === event.currentTarget)));
        let shown = 0;
        document.querySelectorAll(".county-table tbody tr").forEach((tr) => {
          const on = key === "all" || (tr.dataset.flags || "").split(" ").includes(key);
          tr.hidden = !on;
          shown += on;
        });
        status.textContent = `Showing ${plural(shown, "agreement")}.`;
      } }, `${label} (${count(key)})`)));
  return [group, status];
}

async function renderCounty() {
  document.title = "Prince George's County · Promise Ledger";
  setBanner(true);
  const view = byId("view-county");
  const body = el("div", { class: "county-body", "aria-busy": "true" }, el("div", { class: "skeleton", style: "height:10rem;border-radius:var(--r-lg)" }));
  view.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("p", { class: "eyebrow" }, el("span", { class: "real-badge" }, icon("check"), "Real public records")),
        el("h1", { id: "county-title" }, "Prince George's County"),
        el("p", { class: "page-sub" }, "Every payment-in-lieu-of-taxes (PILOT) agreement the County Council considered since 2023, read from the Council's own records. Open any deal to see each commitment's quote and page.")),
    ),
    body);
  let board;
  try {
    board = await api("/api/county");
  } catch (err) {
    body.replaceChildren(el("p", {}, `The county records did not load. ${err.message} Reload the page to try again.`));
    return;
  }
  if (current.view !== "county") return;
  const t = board.totals;
  const read = board.deals.filter((r) => r.records_read);
  if (!board.deals.length) {
    body.replaceChildren(el("p", {}, "No county records are loaded on this server yet."));
    return;
  }
  const pct = (n) => (read.length ? Math.round((100 * n) / read.length) : 0);
  const counters = [];
  const kpi = (value, label, sub, tone = "", of = 0) => {
    const n = el("span", { class: "kv-n" }, typeof value === "number" ? value.toLocaleString() : value);
    if (typeof value === "number") counters.push([n, value]);
    return el("div", { class: `kpi county-kpi ${tone}` },
      el("p", { class: "kpi-label" }, label),
      el("p", { class: "kpi-value" }, n, of ? el("span", { class: "kv-of" }, ` of ${of}`) : null),
      of ? el("span", { class: "kpi-mini frac", "aria-hidden": "true", style: `--f:${value / of}` }, el("span")) : null,
      el("p", { class: "kpi-sub" }, sub));
  };
  const dot = (found, row, key, label) => !row.records_read
    ? el("td", { class: "ob-cell ob-unread", "data-label": label }, el("span", { class: "ob-text-always" }, "Not read yet"))
    : el("td", { class: `ob-cell ${found ? "ob-found" : "ob-missing"}`, "data-label": label },
      el("span", { class: "ob-dot", "aria-hidden": "true" }),
      el("span", { class: "visually-hidden" }, found ? "Wording found" : "No wording found"),
      el("span", { class: "ob-text", "aria-hidden": "true" }, found ? "Found" : "Not found"));
  body.removeAttribute("aria-busy");
  body.replaceChildren(
    el("div", { class: "kpi-row county-kpis" },
      kpi(t.deals, "Agreements", `${t.records_read} of ${t.records} council records read`, "kpi-hero"),
      kpi(t.homes || "—", "Affordable homes stated", t.deals_with_homes ? `in the ${plural(t.deals_with_homes, "agreement")} whose records state a count` : "No counts found yet", "kpi-hero"),
      kpi(t.found.reporting, "Have reporting wording", `${pct(t.found.reporting)}% of agreements read`, t.found.reporting < read.length ? "kpi-warn" : "", read.length),
      kpi(t.found.remedies, "Have remedy wording", `${pct(t.found.remedies)}% of agreements read`, t.found.remedies < read.length ? "kpi-warn" : "", read.length),
      kpi(t.ending_by_2040, "Terms run out by 2040", `of ${plural(t.term_ends_known, "agreement")} that state a term`, t.ending_by_2040 ? "kpi-warn" : ""),
      kpi(t.template_text, "Approved with blanks", "Unfilled template text, like “(insert specific dates)”", t.template_text ? "kpi-warn" : "")),
    countyEffort(t),
    countyMap(board),
    countySearch(),
    countyTimeline(read),
    el("section", { class: "card county-table-card", "aria-labelledby": "county-table-cap" },
      el("div", { class: "card-head" }, el("h2", { id: "county-table-cap" }, "What each agreement's records say"),
        el("p", { class: "hint" }, "Found means wording for that term was found and checked on its page in the records read. Not found is a question to ask, not a finding."),
        el("p", { class: "ob-legend", "aria-hidden": "true" },
          el("span", { class: "ob-found" }, el("span", { class: "ob-dot" }), "Found"),
          el("span", { class: "ob-missing" }, el("span", { class: "ob-dot" }), "Not found")),
        countyFilters(board.deals)),
      el("div", { class: "county-scroll" },
        el("table", { class: "county-table stack" },
          el("caption", { class: "visually-hidden" }, "County PILOT agreements, newest first"),
          el("thead", {}, el("tr", {},
            ["Agreement", "Council action", "Affordable homes", "Income limits", "Longest stated term"].map((h) => el("th", { scope: "col" }, h)),
            ...OBLIGATIONS.map(([, label, help]) => el("th", { scope: "col", class: "ob-head", title: help }, label)))),
          el("tbody", {}, ...board.deals.map((r) => el("tr", { class: r.records_read ? null : "row-pending", "data-flags": countyFlags(r).join(" ") },
            el("th", { scope: "row", "data-label": "Agreement" },
              el("a", { class: "deal-name", href: `#/deals/${encodeURIComponent(r.id)}` }, r.name),
              el("span", { class: "deal-city" }, r.file, " · ", r.records_read < r.records ? `${r.records_read} of ${r.records} records read` : plural(r.records, "record")),
              r.template_text?.length ? el("a", { class: "tag tag-differs template-flag", href: sourceHref(r.id, r.template_text[0].claim_id),
                title: `“${r.template_text[0].quote}”` }, "Template blanks in the approved text") : null),
            el("td", { "data-label": "Council action" },
              el("span", { class: "ca-status" }, r.council_status || "—"), r.passed ? el("span", { class: "ca-date" }, formatDate(r.passed)) : null,
              r.source_url ? el("a", { class: "reminder-source", href: r.source_url, target: "_blank", rel: "noopener" }, "Council record", el("span", { class: "visually-hidden" }, ` for ${r.name} (opens in a new tab)`)) : null),
            el("td", { "data-label": "Affordable homes", class: "num" }, r.homes
              ? [el("span", { title: r.homes_approx ? "The record says over this number" : null }, `${r.homes}${r.homes_approx ? "+" : ""}`), r.homes_claim_id ? el("a", { class: "reminder-source", href: sourceHref(r.id, r.homes_claim_id) }, "Quote", el("span", { class: "visually-hidden" }, ` for ${r.name} homes`)) : null]
              : el("span", { class: "cell-muted" }, "—")),
            el("td", { "data-label": "Income limits" }, r.income_limit || el("span", { class: "cell-muted" }, "—")),
            el("td", { "data-label": "Longest stated term" }, r.term_end
              ? [el("span", {}, r.term_years ? `${r.term_years} years` : formatDate(r.term_end)),
                el("span", { class: "deal-city" }, r.term_end_estimated ? `to about ${r.term_end.slice(0, 4)} or later` : `ends ${formatDate(r.term_end)}`),
                r.term_claim_id ? el("a", { class: "reminder-source", href: sourceHref(r.id, r.term_claim_id) }, "Quote", el("span", { class: "visually-hidden" }, ` for ${r.name} term`)) : null]
              : el("span", { class: "cell-muted" }, "—")),
            ...OBLIGATIONS.map(([key, label]) => dot(r.found[key], r, key, label)))))))),
    el("p", { class: "hint county-source" }, `Source: ${board.source}. Each record is read once and every quote is checked word for word against its page.`),
  );
  for (const [node, value] of counters) animateNumber(node, value, 900, (v) => Math.round(v).toLocaleString());
  riseIn(body);
}

function rememberSample(deals) {
  const sample = deals.find((deal) => /harbor walk/i.test(deal.name)) || deals.find((deal) => deal.documents);
  if (!sample) return;
  sampleId = sample.id;
  document.querySelectorAll(".js-sample").forEach((link) => { link.href = `#/deals/${encodeURIComponent(sample.id)}`; });
  document.querySelectorAll(".js-sample-tour").forEach((link) => { link.href = `#/deals/${encodeURIComponent(sample.id)}/tour`; });
}

// ---------- New deal dialog ----------
function setupNewDeal() {
  const dialog = byId("new-deal-dialog");
  const form = byId("new-deal-form");
  let opener = null;
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-new-deal]");
    if (!trigger) return;
    opener = trigger;
    form.reset();
    byId("nd-error").textContent = "";
    dialog.showModal();
    byId("nd-name").focus();
  });
  byId("nd-cancel").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => opener?.focus());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      const deal = await api("/api/deals", { method: "POST", body: { name: form.name.value.trim(), city: form.city.value.trim() } });
      opener = null;
      dialog.close();
      toast(`${deal.name} created. Add its documents to start.`);
      location.hash = `#/deals/${encodeURIComponent(deal.id)}`;
    } catch (err) {
      byId("nd-error").textContent = err.message;
    } finally {
      button.disabled = false;
    }
  });
}

// ---------- Deal ----------
let dealState = null; // { id, deal, review, claimsById, documentsById, termsByKey }
const counted = new Set();
let pollTimer = null;
const uploads = new Map(); // local uploads still sending: key -> { name, size, progress, docId, error }

const DEAL_TEMPLATE = `
  <ol class="crumbs" aria-label="Breadcrumb"><li><a href="#/deals">Deals</a></li><li aria-current="page" id="crumb-name"><span class="skeleton" style="display:inline-block;width:6rem">&nbsp;</span></li></ol>
  <div class="page-head">
    <div><h1 id="deal-title"><span class="skeleton" style="display:inline-block;width:14rem">&nbsp;</span></h1><p class="page-sub" id="deal-sub">Loading the deal.</p></div>
    <div class="page-actions" id="deal-actions"></div>
  </div>
  <div class="deal-grid" id="deal-dashboard">
    <section class="glance" aria-labelledby="glance-heading">
      <div class="summary-box"><h2 id="glance-heading">At a glance</h2><ul class="glance-list" id="glance-list"></ul><p class="glance-foot" id="glance-foot"></p></div>
      <ul class="kpis" id="kpis" aria-label="Key figures"></ul>
    </section>
    <section class="card promise-scene" id="promise-scene" aria-labelledby="scene-title" hidden></section>
    <div class="stepper-wrap"><h2 class="stepper-heading" id="stepper-heading"><span id="stage-term">Stages</span> on record</h2><ol class="stepper" id="stepper" aria-labelledby="stepper-heading"></ol></div>
    <section class="card review-panel" id="review-panel" aria-labelledby="review-title"></section>
  </div>
  <section class="card docs-card" id="docs-card" aria-labelledby="docs-title" style="margin-top:1rem">
    <div class="card-head"><h2 id="docs-title">Documents</h2><p class="hint" id="docs-count"></p></div>
    <div class="card-body">
      <ul class="doc-list" id="doc-list" aria-live="polite"></ul>
      <div class="dropzone" id="dropzone">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/></svg>
        <p><strong>Drag PDFs here</strong> or</p>
        <button type="button" class="btn btn-secondary" id="choose-files">Choose PDFs</button>
        <input type="file" id="file-input" accept="application/pdf,.pdf" multiple hidden>
        <p class="hint">PDF only, up to 20 MB each. AI reads the text, code checks every quote, and you decide.</p>
        <p class="demo-note">Public demo: please don&rsquo;t upload real records. Uploads are deleted after 24 hours.</p>
      </div>
      <div class="readonly-note" id="readonly-note" hidden>
        <p>Sample deals are read-only. Start a new deal to try your own PDFs.</p>
        <button type="button" class="btn btn-secondary btn-small" data-new-deal>New deal</button>
      </div>
    </div>
  </section>
  <section class="tabs-wrap" id="details" aria-label="Review details">
    <div class="tablist" role="tablist" aria-label="Review details" id="tablist">
      <button type="button" role="tab" id="tab-claims" aria-controls="claims">Claims<span class="tab-count" id="count-claims"></span></button>
      <button type="button" role="tab" id="tab-ask" aria-controls="ask">Ask</button>
      <button type="button" role="tab" id="tab-changes" aria-controls="changes">What changed</button>
      <button type="button" role="tab" id="tab-questions" aria-controls="questions">Open questions<span class="tab-count" id="count-questions"></span></button>
      <button type="button" role="tab" id="tab-receipt" aria-controls="receipt">Receipt</button>
      <button type="button" role="tab" id="tab-extract" aria-controls="extract">Read new text</button>
      <button type="button" role="tab" id="tab-glossary" aria-controls="glossary">Glossary</button>
    </div>
    <div class="panel" role="tabpanel" id="claims" aria-labelledby="tab-claims" tabindex="0">
      <div class="panel-head"><h2>Claims</h2><p class="panel-note" id="check-line"></p></div>
      <table class="data-table claims-table stack">
        <caption class="visually-hidden">Every reviewed claim, grouped by term, with its exact quote, source and stage.</caption>
        <thead><tr><th scope="col">Term</th><th scope="col">Exact quote</th><th scope="col">Source</th><th scope="col">Stage</th><th scope="col">Wording</th><th scope="col">Review</th></tr></thead>
        <tbody id="claim-rows"></tbody>
      </table>
    </div>
    <div class="panel" role="tabpanel" id="ask" aria-labelledby="tab-ask" tabindex="0" hidden>
      <div class="panel-head"><h2>Ask this deal</h2><p class="panel-note">Answers come only from this deal’s checked quotes, and each sentence links to its source. Code removes any sentence its quotes do not back. Nothing is saved.</p></div>
      <form id="ask-form" class="extract-form ask-form">
        <div class="ask-audience" role="group" aria-labelledby="ask-audience-label">
          <span class="ask-audience-label" id="ask-audience-label">Answer for</span>
          <button type="button" class="chip" data-audience="staff" aria-pressed="true">Housing staff</button>
          <button type="button" class="chip" data-audience="resident" aria-pressed="false">Residents, in plain words</button>
        </div>
        <label for="ask-text">Your question</label>
        <div class="ask-row">
          <input id="ask-text" name="question" type="text" required minlength="3" maxlength="300" autocomplete="off" aria-describedby="ask-hint" placeholder="Type a question about this deal">
          <button type="button" class="btn btn-secondary" id="ask-mic" hidden aria-pressed="false">Speak</button>
          <button type="submit" class="btn btn-primary">Ask</button>
        </div>
        <p id="ask-hint" class="hint">Do not type names, phone numbers or other personal details. Questions are not saved.</p>
        <div class="ask-suggest" id="ask-suggest" role="group" aria-label="Example questions"></div>
      </form>
      <div id="ask-status" class="extract-status" role="status"></div>
      <ol class="candidates ask-answer" id="ask-answer" aria-label="Answer"></ol>
      <button type="button" class="btn btn-secondary btn-small ask-speak" id="ask-speak" hidden>Read answer aloud</button>
    </div>
    <div class="panel" role="tabpanel" id="changes" aria-labelledby="tab-changes" tabindex="0" hidden>
      <div class="panel-head"><h2>What changed</h2><p class="panel-note">For each term, every record in date order. Words dropped since the previous record are struck through and labeled "Removed". New words are underlined and labeled "Added".</p></div>
      <div id="paper-trail" class="trail-wrap" hidden></div>
      <div id="change-list" class="change-list"></div>
    </div>
    <div class="panel" role="tabpanel" id="questions" aria-labelledby="tab-questions" tabindex="0" hidden>
      <div class="panel-head"><h2>Open questions</h2><p class="panel-note" id="question-note"></p></div>
      <ul class="task-list" id="question-list"></ul>
    </div>
    <div class="panel" role="tabpanel" id="receipt" aria-labelledby="tab-receipt" tabindex="0" hidden>
      <div class="panel-head"><h2 id="receipt-heading">Promise Receipt</h2><button type="button" class="btn btn-secondary" id="print-receipt"></button></div>
      <div class="printer"><div class="printer-slot" aria-hidden="true"></div><div class="paper-clip"><article class="receipt paper" id="receipt-body" aria-labelledby="receipt-heading"></article></div></div>
    </div>
    <div class="panel" role="tabpanel" id="extract" aria-labelledby="tab-extract" tabindex="0" hidden>
      <div class="panel-head"><h2>Read new text</h2><p class="panel-note">The model finds candidate quotes. Code keeps only quotes that match your text word for word. Nothing here is saved or given a stage.</p></div>
      <form id="extract-form" class="extract-form">
        <label for="extract-text">Text from a record</label>
        <p id="extract-hint" class="hint">Use public records only. Do not paste names, phone numbers or other personal details. Text is not saved.</p>
        <textarea id="extract-text" name="text" rows="7" required minlength="20" aria-describedby="extract-hint"></textarea>
        <button type="submit" class="btn btn-primary">Find quotes</button>
      </form>
      <div id="extract-status" class="extract-status" role="status"></div>
      <ul class="candidates" id="extract-results" aria-label="Candidate quotes"></ul>
    </div>
    <div class="panel" role="tabpanel" id="glossary" aria-labelledby="tab-glossary" tabindex="0" hidden>
      <div class="panel-head"><h2>Glossary</h2><p class="panel-note">Plain-language meanings for terms used on this page.</p></div>
      <dl class="glossary" id="glossary-list"></dl>
    </div>
  </section>`;

async function renderDeal(id, tab, sourceClaim = null, withTour = false) {
  dealState = null;
  const view = byId("view-deal");
  view.innerHTML = DEAL_TEMPLATE; // Static markup only. Data is added below as text nodes.
  byId("glance-list").replaceChildren(...[1, 2, 3].map(() => el("li", {}, el("span", { class: "skeleton sk-line", style: "width:80%" }))));
  byId("kpis").replaceChildren(...[1, 2, 3, 4].map(() => el("li", { class: "kpi" }, el("span", { class: "skeleton sk-line", style: "width:60%" }), el("span", { class: "skeleton", style: "height:2.2rem;width:3rem" }))));
  byId("details").hidden = true;
  renderActions(id, { name: id, documents: [true] }); // Drawn now so the header does not move when the data arrives.
  setupDropzone(id);

  let deal;
  let review;
  try {
    [deal, review] = await Promise.all([api(`/api/deals/${encodeURIComponent(id)}`), api(`/api/deals/${encodeURIComponent(id)}/review`)]);
  } catch (err) {
    if (current.view !== "deal" || current.id !== id) return;
    document.title = `${err.status === 404 ? "Deal not found" : "Deal did not load"} · Promise Ledger`;
    view.replaceChildren(el("div", { class: "empty" },
      el("h1", { id: "deal-title" }, err.status === 404 ? "Deal not found" : "The deal did not load"),
      el("p", {}, err.status === 404 ? "There is no deal at this address." : `${err.message} Reload the page to try again.`),
      el("a", { class: "btn btn-primary", href: "#/deals" }, "Go to deals")));
    return;
  }
  if (current.view !== "deal" || current.id !== id) return;
  setDeal(id, deal, review);
  document.title = `${deal.name} · Promise Ledger`;
  dealIsReal = Boolean(deal.real);
  setBanner(dealIsReal);
  showView("deal"); // Re-marks the nav: a real deal belongs to County.
  byId("crumb-name").textContent = deal.name;
  byId("deal-title").textContent = deal.name;
  byId("deal-sub").textContent = deal.city;
  if (dealIsReal) {
    const crumb = document.querySelector("#view-deal .crumbs a");
    if (crumb) { crumb.href = "#/county"; crumb.textContent = "Prince George's County"; }
    const src = deal.source || {};
    byId("deal-sub").replaceChildren(
      el("span", { class: "real-badge" }, icon("check"), "Real record"), " ",
      src.file ? `Council file ${src.file}` : deal.city,
      src.status ? ` · ${src.status}${src.passed ? ` ${formatDate(src.passed)}` : ""}` : "",
      ...(src.url ? [" · ", el("a", { href: src.url, target: "_blank", rel: "noopener" }, "County record", el("span", { class: "visually-hidden" }, " (opens in a new tab)"))] : []));
  }
  renderActions(id, deal);
  if (dealIsReal) { addShareButton(id, deal.name); addBriefButton(id); }
  renderDocs();
  renderReview({ tab: sourceClaim ? null : tab });
  if (!sourceClaim && !withTour) riseIn(view);
  if (sourceClaim) openSourceFromLink(sourceClaim);
  if (withTour) {
    history.replaceState(null, "", `#/deals/${encodeURIComponent(id)}`);
    current = { view: "deal", id, tab: null };
    setTimeout(() => startTour(), reducedMotion.matches ? 0 : 400);
  }
  pollIfBusy();
}

function setDeal(id, deal, review) {
  dealState = {
    id, deal, review,
    claimsById: new Map(review.claims.map((claim) => [claim.id, claim])),
    documentsById: new Map(review.documents.map((doc) => [doc.id, doc])),
    termsByKey: new Map(review.terms.map((term) => [term.key, term])),
  };
  // Sample deals take no uploads (the server answers 403), so the dropzone gives way to a short note.
  const readOnly = isReadOnly();
  byId("dropzone")?.toggleAttribute("hidden", readOnly);
  byId("readonly-note")?.toggleAttribute("hidden", !readOnly);
}

const isReadOnly = () => Boolean(dealState?.review?.decisions?.sandboxed);

function renderActions(id, deal) {
  const base = `/api/deals/${encodeURIComponent(id)}`;
  // Excel and CSV open a preview of the file first; the downloads are inside it.
  const exportButton = (ext, label) => el("button", {
    type: "button", class: "btn btn-secondary", "data-export": ext, "aria-haspopup": "dialog",
    onclick: (event) => openExport(id, ext, event.currentTarget),
  }, icon(ext === "xlsx" ? "sheet" : "file"), label);
  byId("deal-actions").replaceChildren(...[
    deal.documents?.length || deal.claim_count ? tourButton() : null,
    exportButton("xlsx", "Excel"),
    exportButton("csv", "CSV"),
    el("button", { type: "button", class: "btn btn-primary", id: "share-btn", onclick: (event) => shareLink(id, event.currentTarget) }, icon("link"), "Share read-only link"),
  ].filter(Boolean));
}

// Exports download through fetch, so the demo session travels in a header and never in a link (S3).
async function downloadFile(path, filename) {
  try {
    const blob = await api(path);
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: filename });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(`Saved ${filename}.`, { kind: "ok" });
  } catch (err) {
    toast(`The download did not finish. ${err.message}`, { kind: "warn" });
  }
}

async function mockDownload(path, filename, ext) {
  const blob = await api(path);
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  toast(ext === "xlsx" ? "Saved as CSV. Excel export needs the deals service." : `Saved ${filename}.`, { kind: ext === "xlsx" ? "info" : "ok" });
}

async function shareLink(id, button) {
  button.disabled = true;
  try {
    const { url } = await api(`/api/deals/${encodeURIComponent(id)}/share`, { method: "POST" });
    const full = new URL(url, location.origin).href;
    const field = el("input", { type: "text", readonly: true, value: full, "aria-label": "Read-only link", onfocus: (event) => event.target.select() });
    let copied = false;
    try { await navigator.clipboard.writeText(full); copied = true; } catch (err) { /* Clipboard can be blocked. The link is shown instead. */ }
    toast(copied ? "Read-only link copied." : "Copy this read-only link.", { kind: copied ? "ok" : "info", detail: field, timeout: copied ? 6000 : 15000 });
    if (!copied) field.focus();
  } catch (err) {
    toast(`The link was not created. ${err.message}`, { kind: "warn" });
  } finally {
    button.disabled = false;
  }
}

// The dashboard: at a glance, KPIs, stepper, then the tabs.
function renderReview({ tab = null, keepTab = false } = {}) {
  const { review } = dealState;
  const empty = review.claims.length === 0;
  byId("deal-dashboard").hidden = empty;
  byId("details").hidden = empty;
  byId("docs-card").classList.toggle("empty-deal", empty);
  noClaimsNote({ canShow: true });
  renderNextRecords();
  if (empty) return;

  byId("stage-term").replaceChildren(termButton("stages", "Stages"));
  renderSummary();
  renderReviewPanel();
  // Draw the open tab now and the rest when the browser is idle, so the first paint is not held up.
  const selected = keepTab ? document.querySelector('[role="tab"][aria-selected="true"]')?.id.replace("tab-", "") : null;
  const open = selected || tab || "claims";
  const panels = {
    claims: renderClaims, ask: renderAsk, changes: renderChanges, questions: renderQuestions,
    receipt: () => renderReceipt(byId("receipt-body"), review), glossary: renderGlossaryList, extract: () => {},
  };
  panels[open]?.();
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1));
  const queue = Object.entries(panels).filter(([key]) => key !== open);
  const drawNext = () => {
    if (dealState?.review !== review || !queue.length) return;
    queue.shift()[1]();
    idle(drawNext, { timeout: 400 });
  };
  idle(drawNext, { timeout: 400 });
  byId("count-claims").textContent = String(review.claims.length);
  byId("count-questions").textContent = String(review.questions.length);
  byId("print-receipt").replaceChildren(icon("print"), "Print receipt");
  byId("print-receipt").onclick = () => window.print();
  byId("extract-text").value = review.extraction?.sample_text || "";
  if (review.extraction?.max_chars) byId("extract-text").maxLength = review.extraction.max_chars;
  byId("extract-form").onsubmit = submitExtraction;
  setupTabs();
  activateTab(open);
  if (tab && !keepTab) requestAnimationFrame(() => byId("tablist").scrollIntoView({ block: "start" }));
}

function viewSourceButton(claim, label = "View source") {
  return el("button", {
    type: "button", class: "btn btn-secondary btn-small",
    "aria-label": `${label}: ${claim.document_type}, ${formatDate(claim.date)}, page ${claim.page}`, "data-claim": claim.id,
    onclick: (event) => openSource(claim, event.currentTarget),
  }, label);
}

// The real number is always in the page text (screen readers, copy, print); only a decorative copy counts up.
function animateNumber(node, end, duration, format = (v) => String(Math.round(v))) {
  if (typeof end !== "number" || !Number.isFinite(end)) { node.textContent = String(end); return; } // e.g. "Signed".
  node.textContent = format(end);
  if (!end || reducedMotion.matches) return;
  const shown = el("span", { class: "count-anim", "aria-hidden": "true" }, format(0));
  node.replaceChildren(shown, el("span", { class: "visually-hidden" }, format(end)));
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    shown.textContent = format(end * (1 - (1 - t) ** 3));
    if (t < 1) requestAnimationFrame(step);
    else node.textContent = format(end);
  };
  requestAnimationFrame(step);
}

function countUp(node, value) {
  animateNumber(node, value, 650);
}

function renderSummary() {
  const { review, claimsById, id } = dealState;
  const s = review.summary;
  const lead = claimsById.get(s.homes_claim_id);
  byId("glance-list").replaceChildren(...s.sentences.map((sentence) => el("li", {}, withTerm(sentence, "not located", "not_located"))));
  byId("glance-foot").replaceChildren(...[
    lead ? el("span", {}, `Home count from: ${sourceShort(lead)}`) : null,
    lead ? viewSourceButton(lead) : null,
    el("span", {}, `Quotes checked: ${review.checks.passed} of ${review.checks.total} found word for word on their cited pages.`),
  ].filter(Boolean));

  const stageIndex = STAGES.indexOf(s.furthest_status) + 1;
  // Each figure gets a small picture of itself: a share bar, stage segments, or one dot per term. All decorative.
  const dots = (count, total) => el("span", { class: "kpi-mini", "aria-hidden": "true" }, Array.from({ length: total || 0 }, (_, i) => el("span", { class: i < count ? "on" : null })));
  const share = s.homes_total && s.homes_described ? el("span", { class: "kpi-mini frac", "aria-hidden": "true", style: `--f:${s.homes_described / s.homes_total}` }, el("span")) : null;
  const kpis = [
    ["Homes described as affordable", s.homes_described ?? "None", s.homes_total ? `of ${s.homes_total} homes` : "homes", false, share],
    // A letter only the developer signed is not a signed agreement: say so and mark it amber.
    s.furthest_status === "signed" && s.signed_by_developer_only
      ? ["Furthest stage (any term)", "Signed", `by the developer only · stage ${stageIndex} of ${s.stages_total}`, true, dots(stageIndex, s.stages_total)]
      : ["Furthest stage (any term)", s.furthest_label, stageIndex ? `stage ${stageIndex} of ${s.stages_total}` : "nothing located", false, dots(stageIndex, s.stages_total)],
    ["Terms that differ", s.terms_differ, `of ${s.terms_total} terms`, s.terms_differ > 0, dots(s.terms_differ, s.terms_total)],
    ["Terms not located", s.terms_not_located, `of ${s.terms_total} terms`, s.terms_not_located > 0, dots(s.terms_not_located, s.terms_total)],
  ];
  const animate = !counted.has(id);
  counted.add(id);
  byId("kpis").replaceChildren(...kpis.map(([label, value, unit, warn, mini]) => {
    const valueNode = el("span", { class: "kpi-value" }, String(value));
    if (animate) countUp(valueNode, value);
    return el("li", { class: `kpi${warn ? " kpi-warn" : ""}` }, el("span", { class: "kpi-label" }, label), valueNode, el("span", { class: "kpi-unit" }, unit), mini);
  }));

  byId("stepper").replaceChildren(...review.stages.map((stage, index) => {
    const located = stage.claim_ids.length > 0;
    const iconNode = located
      ? svg("0 0 28 28", [["circle", { cx: 14, cy: 14, r: 13, class: "ico-located" }], ["path", { d: "M8.5 14.5l3.5 3.5 7.5-8", class: "ico-located-check" }]])
      : svg("0 0 28 28", [["circle", { cx: 14, cy: 14, r: 12, class: "ico-missing" }]]);
    const nextLocated = review.stages[index + 1]?.claim_ids.length > 0;
    return el("li", { class: `step${located && nextLocated ? " done" : ""}`, style: `--i:${index}`, "aria-current": stage.status === s.furthest_status ? "step" : null },
      el("span", { class: "step-dot" }, iconNode),
      el("span", { class: "step-text" },
        el("span", { class: "step-name" }, stage.label),
        el("span", { class: "step-detail" }, located ? `Located · ${plural(stage.claim_ids.length, "claim")}` : "Not located")));
  }));
  byId("stepper").classList.toggle("draw", animate);
  renderScene();
}

// ---------- Promise building ----------
// An isometric building drawn from the deal's own checked numbers: one window per home, the promised homes lit
// in the color of the stage a record reached. Nothing here decides anything; it pictures the checked claims.
const SCENE_STAGE_TEXT = { proposed: "Proposed", supported: "Supported", signed: "Signed", delivered: "Delivered" };

function homesOf(claim) {
  const n = claim.homes?.count ?? parseInt(String(claim.value || "").match(/\d+/)?.[0] || "", 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function sceneData(review) {
  const units = review.claims.filter((c) => c.topic === "units");
  if (!units.length) return null;
  const total = Math.max(0, ...units.map((c) => c.homes?.of || 0)) || null;
  // For each stage, the record that went furthest at that stage (latest date), and how many homes it states.
  const stages = STAGES.map((status) => {
    const at = units.filter((c) => c.status === status && homesOf(c));
    const lead = at.sort((a, b) => (b.date || "").localeCompare(a.date || ""))[0] || null;
    return { status, claim: lead, homes: lead ? homesOf(lead) : null };
  });
  const furthest = [...stages].reverse().find((s) => s.homes);
  if (!furthest) return null;
  const promised = furthest.homes;
  return { total: Math.max(total || 0, promised), totalStated: Boolean(total), stages, furthest, promised };
}

// Isometric projection: x runs right-down, y runs left-down, z is height.
const ISO = (x, y, z) => [(x - y) * 0.866, (x + y) * 0.5 - z];
const pts = (list) => list.map(([x, y, z]) => ISO(x, y, z).map((v) => v.toFixed(2)).join(",")).join(" ");

function buildingLayout(total) {
  const per = total >= 96 ? 12 : total >= 40 ? 10 : 6;   // Homes per floor.
  const side = per >= 10 ? 4 : 2;                         // Windows on the short side.
  const front = per - side;
  const floors = Math.ceil(total / per);
  return { per, side, front, floors };
}

function sceneSvg(data) {
  const { per, side, front, floors } = buildingLayout(data.total);
  const W = front + 0.6, D = side + 0.6, H = floors * 1.15 + 0.4;
  // Spread the promised homes through the building, as regulatory agreements usually require.
  // A golden-ratio order scatters them evenly without stripes, and is the same on every load.
  const order = Array.from({ length: data.total }, (_, u) => u).sort((a, b) => ((a * 0.618034) % 1) - ((b * 0.618034) % 1));
  const lit = new Set(order.slice(0, data.promised).sort((a, b) => a - b));
  const root = document.createElementNS(SVG_NS, "svg");
  // The frame includes the ground plate, so the plate is never cut off by the card edge.
  const G = 1.2;
  const corners = [ISO(0, 0, H), ISO(W, 0, H), ISO(0, D, H), ISO(-G, -G, 0), ISO(W + G, -G, 0), ISO(W + G, D + G, 0), ISO(-G, D + G, 0)];
  const xs = corners.map((p) => p[0]), ys = corners.map((p) => p[1]);
  const pad = 0.3;
  root.setAttribute("viewBox", `${(Math.min(...xs) - pad).toFixed(2)} ${(Math.min(...ys) - pad).toFixed(2)} ${(Math.max(...xs) - Math.min(...xs) + 2 * pad).toFixed(2)} ${(Math.max(...ys) - Math.min(...ys) + 2 * pad).toFixed(2)}`);
  root.setAttribute("class", "scene-svg");
  root.setAttribute("aria-hidden", "true");
  const add = (parent, tag, attrs) => { const n = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); parent.append(n); return n; };
  add(root, "polygon", { class: "scene-ground", points: pts([[-G, -G, 0], [W + G, -G, 0], [W + G, D + G, 0], [-G, D + G, 0]]) });
  let unit = 0;
  for (let f = 0; f < floors; f += 1) {
    const g = add(root, "g", { class: "scene-floor", style: `--f:${f}` });
    const z0 = 0.2 + f * 1.15, z1 = z0 + 1.15;
    add(g, "polygon", { class: "scene-wall scene-wall-front", points: pts([[0, D, z0], [W, D, z0], [W, D, z1], [0, D, z1]]) });
    add(g, "polygon", { class: "scene-wall scene-wall-side", points: pts([[W, 0, z0], [W, D, z0], [W, D, z1], [W, 0, z1]]) });
    const windows = [];
    for (let i = 0; i < front; i += 1) windows.push(pts([[0.4 + i, D, z0 + 0.3], [1.0 + i, D, z0 + 0.3], [1.0 + i, D, z0 + 0.9], [0.4 + i, D, z0 + 0.9]]));
    for (let j = 0; j < side; j += 1) windows.push(pts([[W, 0.4 + j, z0 + 0.3], [W, 1.0 + j, z0 + 0.3], [W, 1.0 + j, z0 + 0.9], [W, 0.4 + j, z0 + 0.9]]));
    for (const points of windows) {
      if (unit >= data.total) break;
      const on = lit.has(unit);
      add(g, "polygon", { class: on ? "scene-win scene-lit" : "scene-win", points, style: on ? `--n:${[...lit].indexOf(unit)}` : "" });
      unit += 1;
    }
  }
  const roofZ = 0.2 + floors * 1.15;
  add(root, "polygon", { class: "scene-roof", points: pts([[0, 0, roofZ], [W, 0, roofZ], [W, D, roofZ], [0, D, roofZ]]), style: `--f:${floors}` });
  return root;
}

// What the picture means, in words: was the count kept, and does any record show the homes delivered?
// Each line comes straight from the stage counts and the server's "wording differs" flag.
function sceneFacts(data, review) {
  const promisedAt = data.stages.filter((s) => s.homes && s.status !== "delivered");
  const delivered = data.stages.find((s) => s.status === "delivered");
  const lines = [];
  const first = promisedAt[0], last = promisedAt[promisedAt.length - 1];
  if (first && last && first !== last) {
    lines.push(first.homes === last.homes
      ? ["ok", `Same count, ${plural(last.homes, "home")}, at every stage that states one.`]
      : ["warn", `Count changed: ${SCENE_STAGE_TEXT[first.status]} ${plural(first.homes, "home")}, ${SCENE_STAGE_TEXT[last.status]} ${plural(last.homes, "home")}.`]);
  }
  if (delivered?.homes && last) {
    lines.push(delivered.homes >= last.homes
      ? ["ok", `A record shows ${delivered.homes} of ${plural(last.homes, "promised home")} delivered.`]
      : ["warn", `A record shows only ${delivered.homes} of ${plural(last.homes, "promised home")} delivered.`]);
  } else if (!delivered?.homes) {
    lines.push(["warn", "No record in this packet shows the homes delivered yet."]);
  }
  const units = review.terms.find((t) => t.key === "units");
  if (units?.wording_differs) {
    lines.push(["warn", ["The wording of the home count changed between records. ",
      el("a", { href: `#/deals/${encodeURIComponent(dealState.id)}/changes` }, "See the paper trail")]]);
  }
  if (!lines.length) return null;
  return el("ul", { class: "scene-facts" }, ...lines.map(([tone, text]) => el("li", { class: `fact-${tone}` }, text)));
}

function renderScene() {
  const host = byId("promise-scene");
  if (!host || !dealState) return;
  const data = sceneData(dealState.review);
  host.hidden = !data;
  if (!data) { host.replaceChildren(); return; }
  const picture = sceneSvg(data);
  const figure = el("div", { class: "scene-figure", "data-stage": data.furthest.status });
  figure.append(picture);
  const show = (status) => {
    figure.dataset.stage = status;
    const row = data.stages.find((s) => s.status === status);
    const lit = picture.querySelectorAll(".scene-lit");
    lit.forEach((w, i) => w.classList.toggle("scene-off", !row?.homes || i >= row.homes));
    host.querySelectorAll(".scene-step").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.status === status)));
  };
  const steps = el("ol", { class: "scene-steps" }, ...data.stages.map((s) => el("li", {},
    el("button", {
      type: "button", class: `scene-step stage-${s.status}`, "data-status": s.status, "aria-pressed": String(s.status === data.furthest.status),
      disabled: s.homes ? null : true, onmouseenter: () => s.homes && show(s.status), onfocus: () => s.homes && show(s.status),
      onclick: () => s.homes && show(s.status),
    },
      el("span", { class: "scene-swatch", "aria-hidden": "true" }),
      el("span", { class: "scene-step-name" }, SCENE_STAGE_TEXT[s.status]),
      el("span", { class: "scene-step-count" }, s.homes ? plural(s.homes, "home") : "No home count"),
      el("span", { class: "scene-step-src" }, s.claim ? sourceShort(s.claim) : "No record at this stage states a number of homes",
        s.status === "signed" && s.claim && dealState.review.summary.signed_by_developer_only ? " · signed by the developer only" : "")),
    s.claim ? viewSourceButton(s.claim, "Quote") : null)));
  steps.addEventListener("mouseleave", () => show(data.furthest.status));
  const label = `${data.promised} of ${data.total} homes${data.totalStated ? "" : " (total not stated)"} promised as affordable; furthest stage ${SCENE_STAGE_TEXT[data.furthest.status]}.`;
  const facts = sceneFacts(data, dealState.review);
  host.replaceChildren(
    el("div", { class: "scene-visual", role: "img", "aria-label": label }, figure),
    el("div", { class: "scene-text" },
      el("p", { class: "kicker" }, "The promise, pictured"),
      el("h2", { id: "scene-title", class: "scene-title" }, el("span", { class: "scene-big" }, String(data.promised)), ` of ${data.total} homes`),
      el("p", { class: "scene-lede" }, data.totalStated
        ? `Each window is one home. Lit windows are the homes described as affordable, in the color of the furthest stage a record reached. Point at a stage to see what that record promised.`
        : `Each window is one home described as affordable; no record states the building's total.`),
      facts,
      steps,
      el("p", { class: "scene-note" }, "Drawn from checked quotes only. Where the homes sit in the building is illustrative.")));
  show(data.furthest.status);
  const animate = !reducedMotion.matches && !sceneSeen.has(dealState.id);
  sceneSeen.add(dealState.id);
  host.classList.toggle("scene-animate", animate);
  // Hold the animation until the building is on screen, so it plays where someone can see it.
  host.classList.toggle("scene-wait", animate && "IntersectionObserver" in window);
  if (animate && "IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { host.classList.remove("scene-wait"); seen.disconnect(); }
    }, { threshold: 0.35 });
    seen.observe(host);
    setTimeout(() => { host.classList.remove("scene-wait"); seen.disconnect(); }, 5000); // Never leave it hidden.
  }
}
const sceneSeen = new Set();


// Tabs: ARIA tabs with arrow keys, Home and End. The hash names the open tab.
let printed = null; // The deal whose receipt has already printed this visit.
function activateTab(id, { focus = false, updateHash = false } = {}) {
  if (!TAB_IDS.includes(id) || !byId(`tab-${id}`)) return;
  for (const tabId of TAB_IDS) {
    const on = tabId === id;
    const tabButton = byId(`tab-${tabId}`);
    tabButton.setAttribute("aria-selected", String(on));
    tabButton.tabIndex = on ? 0 : -1;
    byId(tabId).hidden = !on;
  }
  if (focus) byId(`tab-${id}`).focus();
  moveTabInk(byId(`tab-${id}`));
  if (id === "receipt" && dealState && printed !== dealState.id) {
    printed = dealState.id;
    requestAnimationFrame(() => printOut(byId("receipt-body")));
  }
  if (updateHash && dealState) {
    const hash = `#/deals/${encodeURIComponent(dealState.id)}/${id}`;
    if (location.hash !== hash) { history.replaceState(null, "", hash); current.tab = id; }
  }
}

function moveTabInk(tab) {
  const list = byId("tablist");
  if (!list || !tab) return;
  let ink = list.querySelector(".tab-ink");
  if (!ink) {
    ink = el("span", { class: "tab-ink", "aria-hidden": "true" });
    list.prepend(ink);
    list.classList.add("has-ink");
  }
  const box = list.getBoundingClientRect();
  const at = tab.getBoundingClientRect();
  ink.style.width = `${at.width}px`;
  ink.style.transform = `translateX(${at.left - box.left - list.clientLeft + list.scrollLeft}px)`;
}
const realignInk = () => { const tab = document.querySelector('#tablist [aria-selected="true"]'); if (tab) moveTabInk(tab); };
window.addEventListener("resize", realignInk);
document.fonts?.addEventListener?.("loadingdone", realignInk); // Web fonts change tab widths.

function setupTabs() {
  const tabs = TAB_IDS.map((id) => byId(`tab-${id}`));
  tabs.forEach((tabButton, index) => {
    tabButton.onclick = () => activateTab(TAB_IDS[index], { updateHash: true });
    tabButton.onkeydown = (event) => {
      const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 };
      if (!(event.key in moves)) return;
      event.preventDefault();
      activateTab(TAB_IDS[(moves[event.key] + tabs.length) % tabs.length], { focus: true, updateHash: true });
    };
  });
}

function renderGlossaryList() {
  byId("glossary-list").replaceChildren(...Object.entries(GLOSSARY).flatMap(([key, entry]) => [
    el("dt", { id: `g-${key}`, tabindex: "-1" }, entry.title),
    el("dd", {}, entry.text),
  ]));
}

function termLabel(key) {
  const label = dealState.review.topics[key] || key;
  if (key === "term") return termButton("term", label);
  if (key === "remedies") return termButton("remedies", label);
  if (key === "rent_limits") return termButton("rent_limits", label);
  if (key === "income_basis") return el("span", { class: "nowrap" }, label, " (", termButton("ami", "AMI"), ")");
  return label;
}

const staggered = new Set(); // Deals whose claim rows have already played their entrance.
function renderClaims() {
  const { review, termsByKey } = dealState;
  const { passed, total, problems } = review.checks;
  byId("count-claims").textContent = String(review.claims.length);
  byId("check-line").textContent = problems.length
    ? `${passed} of ${total} quotes passed the check. ${problems.length} flagged for human review.`
    : `Code found all ${total} quotes word for word on their cited pages.`;

  const order = Object.keys(review.topics);
  const claims = [...review.claims].sort((a, b) => order.indexOf(a.topic) - order.indexOf(b.topic) || a.date.localeCompare(b.date));
  const stagger = !staggered.has(dealState.id);
  staggered.add(dealState.id);
  byId("claim-rows").classList.toggle("enter", stagger);
  byId("claim-rows").replaceChildren(...claims.map((claim, index) => {
    const term = termsByKey.get(claim.topic);
    let wording = el("span", { class: "cell-muted" }, "Not compared");
    if (term) {
      wording = term.wording_differs
        ? tag("differs")
        : el("span", { class: "cell-muted" }, term.claim_ids.length > 1 ? "Same in every record" : "One record");
    }
    return el("tr", { style: index < 12 ? `--i:${index}` : null },
      el("th", { scope: "row", "data-label": "Term" }, termLabel(claim.topic)),
      el("td", { "data-label": "Exact quote" }, el("span", { class: "quote" }, `“${claim.quote}”`)),
      el("td", { "data-label": "Source" }, el("span", { class: "source-cell" },
        el("span", { class: "source-line" }, docType(claim.document_type), docLabel(claim) !== claim.document_type ? " (not signed)" : "", ` · ${formatDate(claim.date)}`), quoteBadge(claim), claim.from_scan ? tag("machine", "From scan") : null, viewSourceButton(claim))),
      el("td", { "data-label": "Stage" }, tag(claim.status)),
      el("td", { "data-label": "Wording" }, wording),
      el("td", { "data-label": "Review" }, decisionCell("claim", claim.id, `${review.topics[claim.topic] || claim.topic}, ${claim.document_type} page ${claim.page}`)));
  }));
}

// What changed: a word diff between each record and the one before it.
function diffWords(before, after) {
  const a = before.split(/\s+/);
  const b = after.split(/\s+/);
  const table = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { ops.push(["same", a[i]]); i += 1; j += 1; }
    else if (i < a.length && (j === b.length || table[i + 1][j] >= table[i][j + 1])) { ops.push(["removed", a[i]]); i += 1; }
    else { ops.push(["added", b[j]]); j += 1; }
  }
  return ops;
}

// The value code compares ("up to 12 homes", "10 percent of 120 homes"), so this view agrees with "Wording differs".
// Hand-reviewed demo claims have no compare key and show their reviewed value.
const comparedValue = (claim) => claim.compare || claim.value;

function changeStep(claim, previous) {
  const ops = previous ? diffWords(comparedValue(previous), comparedValue(claim)) : [];
  const removed = ops.filter(([kind]) => kind === "removed").map(([, word]) => word).join(" ");
  const added = ops.filter(([kind]) => kind === "added").map(([, word]) => word).join(" ");
  const value = previous
    ? ops.map(([kind, word], at) => [at ? " " : "", kind === "same" ? word : el(kind === "added" ? "ins" : "del", {}, word)])
    : [comparedValue(claim)];
  let labels = "First record.";
  if (previous && !removed && !added) labels = "Same value as the previous record.";
  if (removed || added) {
    labels = [
      removed ? [el("b", {}, "Removed: "), removed] : null,
      removed && added ? " · " : null,
      added ? [el("b", {}, "Added: "), added] : null,
    ];
  }
  return el("li", { class: "change-step" },
    el("p", { class: "change-meta" }, el("span", {}, sourceShort(claim)), tag(claim.status)),
    el("p", { class: "change-value" }, value),
    el("p", { class: "change-labels" }, labels),
    el("p", { class: "change-quote" }, `“${claim.quote}”`),
    viewSourceButton(claim));
}

function renderChanges() {
  renderTrail();
  const { review, claimsById } = dealState;
  const located = review.terms.filter((term) => term.located);
  const missing = review.terms.filter((term) => !term.located);
  byId("change-list").replaceChildren(
    ...located.map((term) => {
      const claims = term.claim_ids.map((cid) => claimsById.get(cid));
      return el("section", { class: "change-term", "aria-labelledby": `change-${term.key}` },
        el("h3", { id: `change-${term.key}` }, termLabel(term.key), " ",
          term.wording_differs ? tag("differs") : el("span", { class: "cell-muted" }, "No change")),
        el("ol", { class: "change-steps" }, ...claims.map((claim, index) => changeStep(claim, claims[index - 1]))));
    }),
    missing.length
      ? el("p", { class: "change-missing" }, tag("not_located"),
        `${missing.map((term) => term.label).join(", ")}: no wording found in this packet, so there is nothing to compare.`)
      : null,
  );
}

// ---------- Paper trail ----------
// Every record in date order, every term as a thread through them. A thread turns amber where the review says the
// wording changed. The picture uses the server's own "wording differs" decision, so it cannot disagree with it.
const normValue = (v) => String(v || "").toLowerCase().replace(/\s+/g, " ").trim();

function renderTrail() {
  const host = byId("paper-trail");
  if (!host || !dealState) return;
  const { review, claimsById } = dealState;
  const located = review.terms.filter((t) => t.located);
  const docIds = new Set(located.flatMap((t) => t.claim_ids.map((id) => claimsById.get(id)?.document)).filter(Boolean));
  const docs = review.documents.filter((d) => docIds.has(d.id)).sort((a, b) => (a.date || "").localeCompare(b.date || "") || a.id.localeCompare(b.id));
  if (docs.length < 2 || !located.length) { host.replaceChildren(); host.hidden = true; return; }
  host.hidden = false;
  const terms = [...located].sort((a, b) => Number(b.wording_differs) - Number(a.wording_differs));
  const stageOf = (doc) => {
    const ids = located.flatMap((t) => t.claim_ids).map((id) => claimsById.get(id)).filter((c) => c?.document === doc.id);
    return ids.reduce((best, c) => (STAGES.indexOf(c.status) > STAGES.indexOf(best) ? c.status : best), "proposed");
  };
  const head = el("tr", {}, el("th", { scope: "col", class: "trail-corner" }, el("span", { class: "visually-hidden" }, "Term")),
    ...docs.map((doc, i) => el("th", { scope: "col", class: "trail-doc", style: `--c:${i}` },
      el("span", { class: "trail-sheet", "aria-hidden": "true" }, el("span"), el("span"), el("span")),
      el("span", { class: "trail-doc-type" }, doc.type || "Record"),
      el("span", { class: "trail-doc-date" }, doc.date ? formatDate(doc.date) : "Undated"),
      tag(stageOf(doc)))));
  // One pass decides each cell; the table (wide screens) and the summary list (phones) both draw from it.
  const lines = terms.map((term) => {
    let previous = null;
    const cells = docs.map((doc) => {
      const claim = term.claim_ids.map((id) => claimsById.get(id)).find((c) => c?.document === doc.id);
      if (!claim) return { doc, kind: previous ? "through" : "gap" };
      const value = comparedValue(claim);
      const changed = Boolean(previous) && term.wording_differs && normValue(value) !== normValue(previous);
      const kind = !previous ? "first" : changed ? "changed" : "same";
      previous = value;
      return { doc, claim, value, changed, kind };
    });
    return { term, cells, found: cells.filter((c) => c.claim) };
  });
  // The term name jumps to that term's full record-by-record wording further down.
  const jump = (term) => el("button", { type: "button", class: "trail-jump", "aria-label": `${term.label}: show every quote`, onclick: () => {
    const target = byId(`change-${term.key}`);
    if (!target) return;
    target.setAttribute("tabindex", "-1");
    target.scrollIntoView({ block: "start", behavior: reducedMotion.matches ? "auto" : "smooth" });
    target.focus({ preventScroll: true });
  } }, term.label);
  const pill = (term, cell) => el("button", { type: "button", class: "trail-pill", onclick: (event) => openSource(cell.claim, event.currentTarget),
    "aria-label": `${term.label}: ${cell.value}, ${cell.doc.type || "record"} ${cell.doc.date ? formatDate(cell.doc.date) : ""}${cell.changed ? ", changed from the previous record" : ""}. Open source.` },
    cell.changed ? el("span", { class: "trail-mark", "aria-hidden": "true" }, "Δ") : null, cell.value);
  const rows = lines.map(({ term, cells }) => el("tr", { class: term.wording_differs ? "trail-row-differs" : null },
    el("th", { scope: "row", class: "trail-term" }, jump(term), term.wording_differs ? el("span", { class: "trail-flag" }, "changed") : null),
    ...cells.map((cell, i) => el("td", { class: `trail-cell trail-${cell.kind === "through" ? "gap trail-through" : cell.kind}`, style: `--c:${i}` },
      cell.claim ? pill(term, cell) : el("span", { class: "visually-hidden" }, "Not in this record")))));
  // Phones: one line per term, first wording to latest wording, with a dot for every record.
  const mini = el("ul", { class: "trail-mini" }, ...lines.map(({ term, cells, found }) => {
    const first = found[0], latest = found[found.length - 1];
    const moved = term.wording_differs && normValue(first.value) !== normValue(latest.value);
    const changes = cells.filter((c) => c.changed).length;
    return el("li", { class: term.wording_differs ? "tm-differs" : null },
      el("div", { class: "tm-head" }, jump(term), term.wording_differs ? el("span", { class: "trail-flag" }, "changed") : null,
        el("span", { class: "tm-count" }, `${found.length} of ${plural(docs.length, "record")}`)),
      el("div", { class: "tm-dots", "aria-hidden": "true" }, ...cells.map((cell) => el("span", { class: `tm-dot tm-${cell.kind}` }))),
      el("p", { class: "tm-values" },
        moved ? [el("span", { class: "tm-was" }, first.value), el("span", { class: "tm-arrow", "aria-hidden": "true" }, "→"), el("span", { class: "visually-hidden" }, " became ")] : null,
        pill(term, latest), el("span", { class: "tm-src" }, latest.doc.type || "Record", latest.doc.date ? ` · ${formatDate(latest.doc.date)}` : "",
          changes ? ` · changed in ${plural(changes, "record")}${moved ? "" : ", now back to the first wording"}` : "")));
  }));
  const animate = !reducedMotion.matches && !trailSeen.has(dealState.id);
  trailSeen.add(dealState.id);
  host.className = `trail-wrap${animate ? " trail-animate" : ""}`;
  host.replaceChildren(
    el("div", { class: "trail-head" },
      el("h3", {}, "Paper trail"),
      el("ul", { class: "trail-legend", "aria-label": "Legend" },
        el("li", { class: "lg-same" }, "Same wording"), el("li", { class: "lg-changed" }, "Wording changed"), el("li", { class: "lg-gap" }, "Not in this record")),
      el("p", { class: "trail-swipe", "aria-hidden": "true" }, "Swipe for later records →")),
    el("div", { class: "trail-scroll", tabindex: "0", role: "region", "aria-label": "Paper trail: each term across the records, in date order" },
      el("table", { class: "trail" },
        el("caption", { class: "visually-hidden" }, "Each term's wording in every record, oldest first. Select a value to open its source page."),
        el("thead", {}, head), el("tbody", {}, ...rows))),
    mini);
}
const trailSeen = new Set();

function renderQuestions() {
  const { questions } = dealState.review;
  byId("count-questions").textContent = String(questions.length);
  byId("question-note").textContent = `${plural(questions.length, "question")} from terms that are not located or differ across records. Each needs a decision before the review is complete.`;
  byId("question-list").replaceChildren(...questions.map((question) => el("li", { class: "task task-decide" },
    el("p", { class: "task-text" }, question.text),
    tag(question.tag),
    decisionCell("question", question.key, question.text.length > 120 ? `${question.text.slice(0, 117)}…` : question.text))));
  renderPossible();
}

// Sentences found on their page that the term rules did not confirm. Optional; they count toward nothing.
function renderPossible() {
  byId("possible-list")?.remove();
  const items = dealState.review.possible || [];
  if (!items.length) return;
  byId("question-list").after(el("details", { id: "possible-list", class: "possible" },
    el("summary", {}, `${plural(items.length, "more sentence")} to check (optional)`),
    el("p", { class: "panel-note" }, "The model filed these under a term and each quote is on its page, but the term rules did not confirm the sentence states that term. They are not counted in any stage, term or receipt."),
    el("ul", { class: "task-list" }, ...items.map((item) => el("li", { class: "task" },
      el("div", {},
        el("p", { class: "task-text" }, el("strong", {}, `Possible ${item.label.toLowerCase()}: `), `“${item.quote}”`),
        el("p", { class: "hint" }, `${item.document_title}, page ${item.page}`)),
      tag("machine"))))));
}

// All parts of one highlighted quote (it can span several lines of the text layer).
const layerMarks = (first) => [...(first.closest(".textLayer")?.querySelectorAll("mark.hl") || [first])];

// The stamp reads "Flagged for human review" until every open question has a decision.
// Stamp states from the server: flagged | in_progress | complete_confirmed | complete_follow_up | complete_disputed.
// Older servers send state "reviewed" with the name and date inside the text; both shapes are read.
const STAMP_TONE = { flagged: "ink", in_progress: "ink", complete_confirmed: "confirmed", complete_follow_up: "follow_up", complete_disputed: "disputed", reviewed: "confirmed" };
function stampInfo(review) {
  const stamp = review.decisions?.stamp || {};
  const state = STAMP_TONE[stamp.state] ? stamp.state : "flagged";
  const reviewer = stamp.reviewer || stamp.reviewer_name || "";
  let text = stamp.text || "Flagged for human review";
  if (stamp.state === "reviewed") text = "Reviewed"; // The old text repeated the name and date.
  const caption = reviewer && stamp.date ? `${reviewer} · ${formatDate(stamp.date)}` : "";
  return { state, tone: STAMP_TONE[state], text, caption, complete: state.startsWith("complete") || state === "reviewed" };
}

// The stamp sits in its own grid area next to the heading, so it never covers the list.
function receiptStamp(review) {
  const info = stampInfo(review);
  return el("div", { class: `stamp-block tone-${info.tone}`, "aria-hidden": "true" },
    el("span", { class: `receipt-stamp tone-${info.tone}` }, info.text),
    info.caption ? el("span", { class: "stamp-caption" }, info.caption) : null);
}

// Receipt: black on white, the same on screen, in a shared link and in print.
function renderReceipt(target, review, { titleTag = "p" } = {}) {
  const claimsById = new Map(review.claims.map((claim) => [claim.id, claim]));
  const rows = review.terms.map((term) => {
    const signed = term.signed_claim_id ? claimsById.get(term.signed_claim_id) : null;
    const earlier = term.claim_ids.map((cid) => claimsById.get(cid)).filter((claim) => claim && claim.status !== "signed");
    return el("tr", {},
      el("th", { scope: "row" }, term.label),
      el("td", { "data-label": "Signed wording" }, signed
        ? [el("span", { class: "q" }, `“${signed.quote}”`), el("span", { class: "receipt-source" }, sourceShort(signed))]
        : el("span", { class: "not-located" }, term.located ? "Not located in a signed record" : "Not located")),
      el("td", { "data-label": "Earlier wording" }, earlier.length
        ? el("ul", { class: "plain" }, ...earlier.map((claim) => el("li", {}, `${comparedValue(claim)} (${claim.document_type}, p. ${claim.page})`)))
        : "None"));
  });
  const support = review.claims.filter((claim) => claim.topic === "public_support");
  const { passed, total } = review.checks;

  target.replaceChildren(...[
    el("header", { class: "receipt-head" },
      el(titleTag, { class: "receipt-title" }, `Promise Receipt: ${review.project}, ${review.city}`),
      el("p", { class: "receipt-notice" }, review.notice)),
    el("h3", {}, "At a glance"),
    el("ul", {}, ...review.summary.sentences.map((sentence) => el("li", {}, sentence))),
    el("h3", {}, "Stages on record"),
    el("ul", { class: "receipt-stages" }, ...review.stages.map((stage) => el("li", {},
      el("b", {}, stage.label), stage.claim_ids.length ? plural(stage.claim_ids.length, "claim") : "Not located"))),
    support.length ? el("h3", {}, "Public support") : null,
    support.length ? el("ul", { class: "plain" }, ...support.map((claim) => el("li", {}, el("span", { class: "q" }, `“${claim.quote}”`), el("span", { class: "receipt-source" }, sourceShort(claim))))) : null,
    el("h3", {}, "Terms"),
    el("div", { class: "receipt-scroll", tabindex: "0", role: "region", "aria-label": "Receipt terms table" },
      el("table", {},
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Term"), el("th", { scope: "col" }, "Signed wording"), el("th", { scope: "col" }, "Earlier wording"))),
        el("tbody", {}, ...rows))),
    el("div", { class: "receipt-flags" },
      el("h3", {}, "Open questions"),
      review.questions.length ? el("ul", {}, ...review.questions.map((question) => {
        const event = review.decisions?.latest?.[`question:${question.key}`];
        return el("li", {}, question.text, event
          ? el("span", { class: `receipt-decision decided-${event.decision}` }, svg("0 0 16 16", DECISION_ICON[event.decision] || DECISION_ICON.confirmed),
            `${event.label} by ${event.reviewer_name}, ${formatDate(event.at.slice(0, 10))}${event.note ? `: “${event.note}”` : "."}`)
          : el("span", { class: "receipt-decision pending" }, "Not reviewed yet."));
      })) : el("p", {}, "None."),
      review.claims.length ? receiptStamp(review) : null),
    review.decisions?.progress ? el("p", { class: "receipt-foot" },
      `Review: ${review.decisions.progress.claims_reviewed} of ${review.decisions.progress.claims_total} claims and ${review.decisions.progress.flagged_reviewed} of ${review.decisions.progress.flagged_total} open questions have a reviewer decision. Decisions do not change any stage.`) : null,
    el("p", { class: "receipt-foot" }, `Quote check: ${passed} of ${total} quotes found on their cited pages.`),
    el("div", { class: "sign-off" }, el("p", {}, "Reviewed by: ______________________"), el("p", {}, "Date: ______________")),
    el("p", { class: "receipt-foot" }, review.decisions?.footer || "A review records people's decisions. It is not a legal finding.")
  ].filter(Boolean));
}

// Read new text: live extraction. Every result is machine-extracted and flagged for review.
async function submitExtraction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const max = dealState.review.extraction?.max_chars || 8000;
  button.disabled = true;
  byId("extract-status").textContent = "Reading the text.";
  byId("extract-results").replaceChildren();
  try {
    const res = await fetch("/api/extract", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: form.text.value }) });
    if (res.status === 422) throw new Error(`Enter between 20 and ${max} characters.`);
    if (!res.ok) throw new Error(`The server returned ${res.status}. Try again.`);
    const result = await res.json();
    byId("extract-status").replaceChildren(
      el("p", { class: "extract-notice" }, result.notice),
      el("p", {}, `${plural(result.candidates.length, "candidate quote")} found.` + (result.dropped ? ` ${result.dropped} removed because the quote did not match the text.` : "")));
    byId("extract-results").replaceChildren(...result.candidates.map((candidate) => el("li", {},
      el("span", { class: "candidate-tags" }, tag("machine"), tag("not_located", candidate.review)),
      el("p", { class: "quote" }, `“${candidate.quote}”`),
      el("p", {}, `Topic: ${dealState.review.topics[candidate.topic] || candidate.topic}. Wording: “${candidate.wording}”.`))));
  } catch (err) {
    byId("extract-status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

// ---------- Ask a deal ----------
const ASK_EXAMPLES = ["How many homes are affordable?", "What income do you need to qualify?", "How long do the limits last?", "Is any of this signed?", "Who checks that the promises are kept?"];
let askAudience = "staff";

function renderAsk() {
  const form = byId("ask-form");
  if (!form || form.dataset.ready === dealState.id) return;
  form.dataset.ready = dealState.id;
  byId("ask-status").replaceChildren();
  byId("ask-answer").replaceChildren();
  byId("ask-speak").hidden = true;
  form.querySelectorAll("[data-audience]").forEach((chip) => {
    chip.setAttribute("aria-pressed", String(chip.dataset.audience === askAudience));
    chip.onclick = () => {
      askAudience = chip.dataset.audience;
      form.querySelectorAll("[data-audience]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
    };
  });
  byId("ask-suggest").replaceChildren(...ASK_EXAMPLES.map((q) => el("button", {
    type: "button", class: "chip", onclick: () => { form.question.value = q; form.requestSubmit(); },
  }, q)));
  form.onsubmit = submitAsk;
  setupDictation(form);
  setupReadAloud();
}

async function submitAsk(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const dealId = dealState.id;
  stopSpeaking();
  button.disabled = true;
  byId("ask-status").textContent = "Looking through the checked quotes.";
  byId("ask-answer").replaceChildren();
  byId("ask-speak").hidden = true;
  try {
    let result;
    try {
      result = await rawApi(`/api/deals/${encodeURIComponent(dealId)}/ask`, { method: "POST", body: { question: form.question.value, audience: askAudience } });
    } catch (err) {
      if (err.status === 422) throw new Error("Enter a question between 3 and 300 characters.");
      throw err;
    }
    if (dealState?.id !== dealId) return;
    const notes = [el("p", { class: "extract-notice" }, result.notice)];
    if (result.removed) notes.push(el("p", {}, result.removed === 1
      ? "1 sentence was removed because its quotes did not back it."
      : `${result.removed} sentences were removed because their quotes did not back them.`));
    byId("ask-status").replaceChildren(...notes);
    byId("ask-answer").replaceChildren(...result.sentences.map((s) => el("li", { class: s.quote ? "ask-quote" : null },
      el("p", { class: s.quote ? "quote" : null }, s.text),
      el("span", { class: "candidate-tags" }, ...s.claim_ids.map((id, i) => {
        const claim = dealState.claimsById.get(id);
        if (!claim) return id === "not-located" ? el("span", { class: "tag tag-not_located" }, "Not located in any record") : null;
        return viewSourceButton(claim, s.claim_ids.length > 1 ? `Source ${i + 1}` : "Source");
      })))));
    byId("ask-speak").hidden = !("speechSynthesis" in window) || !result.sentences.length;
  } catch (err) {
    byId("ask-status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

// Voice uses the browser's own speech services. Dictation shows only where the browser supports it.
function setupDictation(form) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = byId("ask-mic");
  if (!Recognition || !mic) return;
  mic.hidden = false;
  mic.setAttribute("aria-label", "Speak your question");
  mic.title = "Uses your browser's speech service";
  mic.onclick = () => {
    const rec = new Recognition();
    rec.lang = document.documentElement.lang || "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    mic.setAttribute("aria-pressed", "true");
    mic.textContent = "Listening";
    rec.onresult = (e) => { form.question.value = e.results[0][0].transcript; form.requestSubmit(); };
    rec.onerror = () => { byId("ask-status").textContent = "Could not hear a question. Type it instead."; };
    rec.onend = () => { mic.setAttribute("aria-pressed", "false"); mic.textContent = "Speak"; };
    rec.start();
  };
}

function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  const btn = byId("ask-speak");
  if (btn) btn.textContent = "Read answer aloud";
}

function setupReadAloud() {
  const btn = byId("ask-speak");
  if (!btn || !("speechSynthesis" in window)) return;
  btn.onclick = () => {
    if (window.speechSynthesis.speaking) { stopSpeaking(); return; }
    const text = [...byId("ask-answer").querySelectorAll("li > p")].map((p) => p.textContent).join(" ");
    const utter = new SpeechSynthesisUtterance(text);
    utter.onend = stopSpeaking;
    btn.textContent = "Stop reading";
    window.speechSynthesis.speak(utter);
  };
}

// ---------- Documents and upload ----------
const PHASES = [["uploading", "Uploading"], ["reading", "Reading"], ["checking", "Checking quotes"], ["done", "Done"]];
const STATUS_ALIASES = { queued: "reading", uploaded: "reading", processing: "reading", extracting: "reading", verifying: "checking", ready: "done", complete: "done", error: "failed" };
const phaseOf = (status) => STATUS_ALIASES[status] || status || "done";

function progressSteps(phase) {
  const at = PHASES.findIndex(([key]) => key === phase);
  return el("ol", { class: "progress", "aria-label": "Progress" }, PHASES.map(([key, label], index) => {
    if (phase === "failed" && key === "done") return el("li", { class: "bad" }, el("span", { class: "p-dot" }), "Failed");
    let state = "";
    if (phase === "failed") state = index === 0 ? "ok" : "";
    else if (index < at || phase === "done") state = "ok";
    else if (index === at) state = "on";
    return el("li", { class: state, "aria-current": state === "on" ? "step" : null }, el("span", { class: "p-dot" }), label);
  }));
}

// A document's display name: its title, else its file name, else a plain label. Never blank or "null".
const docName = (doc) => (doc?.title || "").trim() || (doc?.filename || doc?.name || "").trim() || "Untitled document";

function docItem({ title, sub, phase, progress = null, error = null, retry = null }) {
  const busy = phase !== "done" && phase !== "failed";
  let status = null;
  if (phase === "done") status = el("span", { class: "badge badge-ok" }, svg("0 0 16 16", ICONS.ok), "Checked");
  if (phase === "failed") status = el("span", { class: "badge badge-warn" }, svg("0 0 16 16", ICONS.not_located), "Failed");
  return el("li", { class: "doc-item", "aria-busy": busy ? "true" : null },
    el("span", { class: "doc-ico", "aria-hidden": "true" }, "PDF"),
    el("span", { class: "doc-title" }, title),
    el("span", { class: "doc-sub" }, sub),
    status,
    busy || phase === "failed" ? progressSteps(phase) : null,
    phase === "uploading" && progress !== null ? el("span", { class: "bar", "aria-hidden": "true" }, el("span", { style: `width:${Math.round(progress * 100)}%` })) : null,
    phase === "reading" || phase === "checking" ? el("span", { class: `bar working ${phase}`, "aria-hidden": "true" }, el("span")) : null,
    error ? el("p", { class: "doc-error" }, error) : null,
    retry ? el("button", { type: "button", class: "btn btn-secondary btn-small doc-retry", onclick: retry, "aria-label": `Try reading ${title} again` },
      svg("0 0 24 24", [["path", { d: "M20 11a8 8 0 1 0-2.3 5.7" }], ["path", { d: "M20 4v7h-7" }]]), "Retry") : null);
}

function renderDocs() {
  if (!dealState) return;
  const docs = dealState.deal.documents || [];
  const local = [...uploads.values()].filter((item) => item.dealId === dealState.id && !docs.some((doc) => doc.id === item.docId));
  const items = [
    ...docs.map((doc) => {
      const pages = doc.pages ? ` · ${plural(doc.pages, "page")}` : "";
      const phase = phaseOf(doc.status);
      return docItem({ title: docName(doc), sub: [docType(doc.type || "Record"), ` · ${formatDate(doc.date)}${pages}`], phase, error: doc.error,
        retry: phase === "failed" && !isReadOnly() ? (event) => retryDocument(doc, event.currentTarget) : null });
    }),
    ...local.map((item) => docItem({ title: item.name, sub: fileSize(item.size), phase: item.error ? "failed" : "uploading", progress: item.progress, error: item.error,
      retry: item.error && item.file ? () => { uploads.delete(item.key); uploadOne(item.dealId, item.file); } : null })),
  ];
  byId("doc-list").replaceChildren(...items);
  byId("doc-list").hidden = items.length === 0;
  byId("docs-count").textContent = items.length ? plural(items.length, "file") : "No files yet";
  noClaimsNote({ canShow: false });
  // Read-only deals fold their file list; anything still reading, failed or uploading keeps it open.
  const busy = docs.some((doc) => ["queued", "reading", "checking", "failed"].includes(doc.status)) || local.length > 0;
  const ask = (dealState.review?.next_records || []).length;
  setCollapsible(byId("docs-card"), { open: !isReadOnly() || busy || !docs.length,
    summary: `${plural(docs.length, "record")} on file${ask ? ` · ${plural(ask, "record")} to ask for` : ""}` });
}

// Every file was read and none states a housing commitment: say so, so the page does not look stuck.
// Only the review render may show it: the file list can redraw before the fresh review arrives (L13).
// Upload assistant: which records to ask for next, by rule from the review (no model is asked).
function renderNextRecords() {
  byId("next-records")?.remove();
  const review = dealState?.review;
  const list = byId("doc-list");
  if (!list || !review?.claims?.length || !Array.isArray(review.next_records)) return;
  const items = review.next_records;
  const body = items.length
    ? el("ul", { class: "next-records-list" }, ...items.map((item) => el("li", { "data-key": item.key },
        el("p", { class: "next-records-name" }, el("strong", {}, item.record),
          item.terms.length ? el("span", { class: "tag tag-not_located" }, `Would show: ${item.terms.join(", ")}`) : null),
        el("p", { class: "next-records-why" }, item.why))))
    : el("p", { class: "next-records-why" }, "Every term is located, and a record shows the homes were delivered. Nothing more to ask for.");
  (byId("no-claims-note") || list).after(el("section", { id: "next-records", class: "next-records", "aria-labelledby": "next-records-title" },
    el("h3", { id: "next-records-title" }, items.length ? "Records to ask for next" : "Records on file"),
    body,
    items.length ? el("button", { type: "button", class: "btn btn-small", onclick: (event) => openLetter(event.currentTarget) },
      icon("docq"), "Draft a records request") : null));
}

// ---------- Share a county agreement ----------
// The /s/ link carries a link preview (name, homes, term, card image) and opens the agreement.
function addShareButton(id, name) {
  const actions = byId("deal-actions");
  if (!actions || actions.querySelector(".share-card-btn")) return;
  const url = `${location.origin}/s/${encodeURIComponent(id)}`;
  actions.prepend(el("button", { type: "button", class: "btn share-card-btn", onclick: async () => {
    if (navigator.share && matchMedia("(pointer: coarse)").matches) {
      try { await navigator.share({ title: `${name} · Promise Ledger`, url }); return; } catch { /* Fall back to copying. */ }
    }
    try {
      await navigator.clipboard.writeText(url);
      toast("Link copied. It shows a preview card with this agreement's numbers.");
    } catch {
      toast(`Copy this link: ${url}`);
    }
  } }, icon("share"), "Share"));
}

// ---------- One-page brief (county agreements) ----------
// What a council member or staffer needs on one sheet: the stated figures with their pages, which key terms the records
// contain, approved text still holding blanks, and the questions to ask. Built from the county board and this review.
function addBriefButton(id) {
  const actions = byId("deal-actions");
  if (!actions || actions.querySelector(".brief-btn")) return;
  actions.prepend(el("button", { type: "button", class: "btn brief-btn", onclick: () => printBrief(id) }, icon("print"), "Print brief"));
}

async function printBrief(id) {
  let board;
  try { board = await api("/api/county"); } catch (err) { toast(`The brief did not load. ${err.message}`, { kind: "error" }); return; }
  const r = board.deals.find((d) => d.id === id);
  const review = dealState?.review;
  if (!r || !review) return;
  const claims = new Map(review.claims.map((c) => [c.id, c]));
  const at = (claimId) => { const c = claims.get(claimId); return c ? ` (${docLabel(c)}, p. ${c.page})` : ""; };
  const row = (label, value, note = "") => el("tr", {}, el("th", { scope: "row" }, label), el("td", {}, value || "Not stated", note ? el("span", { class: "pb-note" }, note) : null));
  const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
  const sheet = el("section", { id: "print-brief", "aria-hidden": "true" },
    el("header", { class: "pb-head" },
      el("p", { class: "pb-kicker" }, "Promise Ledger brief · real public records · Prince George's County, MD"),
      el("h1", {}, r.name),
      el("p", { class: "pb-meta" }, [r.file && `Council file ${r.file}`, r.council_status && `${r.council_status}${r.passed ? ` ${formatDate(r.passed)}` : ""}`,
        `${r.records_read} of ${r.records} records read`, `printed ${today}`].filter(Boolean).join(" · "))),
    el("table", { class: "pb-figs" }, el("tbody", {},
      row("Affordable homes", r.homes ? String(r.homes) : "", r.homes_claim_id ? at(r.homes_claim_id) : ""),
      row("Income limits", r.income_limit || ""),
      row("Longest stated term", r.term_years ? `${r.term_years} years, to ${r.term_end_estimated ? `about ${r.term_end.slice(0, 4)} or later` : formatDate(r.term_end)}` : "",
        r.term_claim_id ? at(r.term_claim_id) : ""),
      row("Furthest stage on record", stageLabel(r.furthest_stage)),
      r.location ? row("Property", `${r.location.address}${r.location.city ? `, ${r.location.city}` : ""}`, ` (from ${r.location.record}, p. ${r.location.page})`) : null)),
    el("h2", {}, "Key terms in the records"),
    el("ul", { class: "pb-terms" }, ...OBLIGATIONS.map(([key, label, help]) => el("li", { class: r.found[key] ? "pb-yes" : "pb-no" },
      el("b", {}, r.found[key] ? "Found" : "Not found"), ` ${label}: ${help[0].toLowerCase()}${help.slice(1)}.`))),
    r.template_text?.length ? [el("h2", {}, "Approved text still holding blanks"),
      el("ul", { class: "pb-blanks" }, ...r.template_text.slice(0, 2).map((t) => el("li", {}, `“${t.quote}”`, el("span", { class: "pb-note" }, ` (${t.document || "record"}${t.page ? `, p. ${t.page}` : ""})`))))] : null,
    el("h2", {}, "Questions to ask"),
    el("ol", { class: "pb-qs" }, ...review.questions.slice(0, 6).map((q) => el("li", {}, q.text))),
    el("footer", { class: "pb-foot" },
      el("p", {}, `Every quote was found word for word on its cited page. "Not found" means no wording was found in the records read: a question to ask, not a finding.`),
      el("p", {}, `Open each quote and page: ${location.origin}/s/${id}`)));
  byId("print-brief")?.remove();
  document.body.append(sheet);
  document.body.classList.add("printing-brief");
  const done = () => { document.body.classList.remove("printing-brief"); window.removeEventListener("afterprint", done); };
  window.addEventListener("afterprint", done);
  window.print();
}

// ---------- Ask the county (chat) ----------
// One question across every county agreement. Answers come only from checked records; every sentence links to the
// agreement or the page it rests on. The server answers from code when it can (no AI cost), reuses an answer it gave
// before, and only then asks the model. Beside each answer it recommends, by code, the agreements the answer rests on
// and next questions the records can answer. Nothing is saved; the conversation lives only in this page.
const CC_TOPICS = [
  { icon: "home", title: "Homes", q: "How many affordable homes are stated in total?" },
  { icon: "calendar", title: "Terms ending", q: "Which terms run out soonest?" },
  { icon: "docq", title: "Missing wording", q: "Which agreements have no remedy wording?" },
  { icon: "file", title: "Template blanks", q: "Which approved agreements still hold template blanks?" },
];
let ccAudience = "staff";
let countyChat = null;

// Agreement names in an answer become links to the agreement.
function linkNames(text, mentions, onLink) {
  const found = (mentions || []).map((m) => ({ ...m, at: text.indexOf(m.name) })).filter((m) => m.at >= 0)
    .sort((a, b) => a.at - b.at || b.name.length - a.name.length);
  const out = [];
  let i = 0;
  for (const m of found) {
    if (m.at < i) continue;
    out.push(text.slice(i, m.at), el("a", { class: "cc-name", href: `#/deals/${encodeURIComponent(m.id)}`, onclick: onLink }, m.name));
    i = m.at + m.name.length;
  }
  out.push(text.slice(i));
  return out;
}

function ccModeBadge(res) {
  if (res.cached) return el("span", { class: "cc-badge cc-b-cache" }, icon("refresh"), "Answered before · no new cost");
  if (res.mode === "computed") return el("span", { class: "cc-badge cc-b-code" }, icon("code"), "Answered by code · no AI cost");
  if (res.mode === "live") {
    const cost = typeof res.cost_usd === "number" ? ` · $${res.cost_usd < 0.001 ? res.cost_usd.toFixed(5) : res.cost_usd.toFixed(4)}` : "";
    return el("span", { class: "cc-badge cc-b-ai" }, icon("spark"), `AI, checked by code${cost}`);
  }
  if (res.mode === "quotes") return el("span", { class: "cc-badge cc-b-quote" }, icon("file"), "Exact quotes");
  return null;
}

function setupCountyChat() {
  const launch = el("button", { type: "button", class: "cc-launch", "aria-expanded": "false", "aria-controls": "cc-panel",
    "aria-keyshortcuts": "/" }, el("span", { class: "cc-dot", "aria-hidden": "true" }), icon("ask"), el("span", { class: "cc-label" }, "Ask the county"));
  // Once the reader scrolls, the button folds to a round icon so it covers less of the page; hover or focus opens it out.
  const fold = () => launch.classList.toggle("cc-compact", window.scrollY > 160);
  window.addEventListener("scroll", fold, { passive: true });

  const thread = el("ol", { class: "cc-thread", "aria-live": "polite", "aria-label": "Conversation", tabindex: "0" });
  const input = el("textarea", { id: "cc-q", rows: "1", maxlength: "300", required: true, autocomplete: "off",
    placeholder: "Ask a question…", "aria-label": "Your question", "aria-describedby": "cc-count" });
  const count = el("span", { class: "cc-count", id: "cc-count", "aria-live": "off" }, "0/300");
  const send = el("button", { type: "submit", class: "cc-send", "aria-label": "Send question", title: "Send (Enter)" }, icon("arrow"));
  let asked = [];
  let context = null; // { id, name } when a real county agreement is open.

  const askNow = (q) => { input.value = q; resize(); form.requestSubmit(); };
  const leave = () => closeChat(false);
  const resize = () => {
    input.style.height = "";
    if (input.value) { input.style.height = "auto"; input.style.height = `${Math.max(44, Math.min(input.scrollHeight + 2, 120))}px`; }
    count.textContent = `${input.value.length}/300`;
  };
  input.addEventListener("input", resize);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
    if (event.key === "ArrowUp" && !input.value && asked.length) { event.preventDefault(); input.value = asked[asked.length - 1]; resize(); }
  });

  function welcome() {
    const cards = (context ? [
      { icon: "calendar", title: context.name, q: `How long is ${context.name}'s stated term?` },
      { icon: "home", title: context.name, q: `What income limits does ${context.name} state?` },
      { icon: "docq", title: context.name, q: `What does ${context.name} say about remedies?` },
      CC_TOPICS[1],
    ] : CC_TOPICS).map((t) => el("button", { type: "button", class: "cc-topic", onclick: () => askNow(t.q) },
      el("span", { class: "cc-topic-ico", "aria-hidden": "true" }, icon(t.icon)),
      el("span", { class: "cc-topic-text" }, el("b", {}, t.title), el("span", {}, t.q))));
    return el("li", { class: "cc-welcome" },
      el("p", { class: "cc-hello" }, context
        ? `Ask about ${context.name}, or any of the 21 county agreements.`
        : "Ask anything about the 21 Prince George's County agreements."),
      el("p", { class: "cc-sub" }, "I answer only from their checked records. Counts come straight from code; every sentence links to its source."),
      el("div", { class: "cc-topics" }, ...cards));
  }
  function reset() { asked = []; thread.replaceChildren(welcome()); input.value = ""; resize(); }

  function answerCard(q, res) {
    const src = res.sources || {};
    const chip = (id) => {
      const s = src[id];
      if (!s) return null;
      if (!s.deal_id) return el("a", { class: "cc-src", href: "#/county", onclick: () => { leave(); setTimeout(() => document.querySelector(".county-table-card")?.scrollIntoView({ block: "start" }), 300); } },
        icon("sheet"), "County table");
      const href = s.claim_id ? sourceHref(s.deal_id, s.claim_id) : `#/deals/${encodeURIComponent(s.deal_id)}`;
      return el("a", { class: "cc-src", href, onclick: leave }, icon("file"), s.deal, s.page ? `, p. ${s.page}` : "");
    };
    const body = res.sentences?.length
      ? el("ul", { class: "cc-answer" }, ...res.sentences.map((s) => el("li", { class: s.quote ? "cc-quote" : null },
        el("p", {}, ...(s.quote ? [s.text] : linkNames(s.text, res.mentions, leave))),
        el("span", { class: "cc-srcs" }, ...s.claim_ids.map(chip)))))
      : null;
    const plain = ccAudience === "staff";
    const actions = el("div", { class: "cc-actions" },
      res.sentences?.length ? el("button", { type: "button", class: "cc-act", title: "Copy the answer and its sources", onclick: async (event) => {
        const text = res.sentences.map((s) => `- ${s.text}`).join("\n") + `\n\n${res.notice || ""}`;
        try { await navigator.clipboard.writeText(`Q: ${q}\n${text}`); event.currentTarget.classList.add("done"); toast("Answer copied."); }
        catch { toast("Copy did not work in this browser.", { kind: "warn" }); }
      } }, icon("copy"), "Copy") : null,
      res.sentences?.length && res.mode !== "computed" ? el("button", { type: "button", class: "cc-act", title: plain ? "Ask again for residents, in plain words" : "Ask again for staff",
        onclick: () => { setAudience(plain ? "resident" : "staff"); askNow(q); } }, icon("refresh"), plain ? "Plain words" : "Staff version") : null);
    const related = res.related?.length ? el("div", { class: "cc-related" },
      el("p", { class: "cc-label-sm" }, res.sentences?.length ? "Agreements in this answer" : "Agreements to look at"),
      el("div", { class: "cc-cards" }, ...res.related.map((r) => el("a", { class: `cc-card${r.soon ? " soon" : ""}`, href: `#/deals/${encodeURIComponent(r.id)}`, onclick: leave },
        el("b", {}, r.name),
        el("span", { class: "cc-card-stats" },
          el("span", {}, r.homes ? `${r.homes.toLocaleString()}${r.homes_approx ? "+" : ""} homes` : "Homes not stated"),
          el("span", {}, r.term_end ? `to ${r.term_end}${r.term_estimated ? "+" : ""}` : "Term not stated"),
          el("span", {}, `${r.found}/${r.of} terms`)),
        r.blanks ? el("span", { class: "cc-flag" }, "Template blanks") : null)))) : null;
    const next = (res.follow_ups || []).filter((f) => !asked.includes(f));
    const follow = next.length ? el("div", { class: "cc-next" }, el("p", { class: "cc-label-sm" }, "Ask next"),
      ...next.map((f) => el("button", { type: "button", class: "cc-chip", onclick: () => askNow(f) }, f, icon("next")))) : null;
    return el("li", { class: "cc-msg cc-bot" },
      el("div", { class: "cc-meta" }, ccModeBadge(res), res.removed ? el("span", { class: "cc-removed", title: "Sentences the code could not back were removed before you saw them" }, `${res.removed} removed by checks`) : null),
      body, el("p", { class: "cc-note" }, res.notice), actions, related, follow);
  }

  const form = el("form", { class: "cc-form", onsubmit: async (event) => {
    event.preventDefault();
    const q = input.value.trim();
    if (q.length < 3) { input.focus(); return; }
    input.value = ""; resize();
    thread.querySelector(".cc-welcome")?.remove();
    asked.push(q);
    thread.append(el("li", { class: "cc-msg cc-me" }, el("p", {}, q)));
    const pending = el("li", { class: "cc-msg cc-bot cc-pending" }, el("span", { class: "cc-typing", role: "status", "aria-label": "Checking the records" }, el("i"), el("i"), el("i")),
      el("span", { class: "cc-pending-text" }, "Checking the records…"));
    thread.append(pending);
    thread.scrollTop = thread.scrollHeight;
    send.disabled = true;
    try {
      const res = await rawApi("/api/county/ask", { method: "POST", body: { question: q, audience: ccAudience } });
      pending.replaceWith(answerCard(q, res));
    } catch (err) {
      const retry = el("button", { type: "button", class: "cc-act", onclick: () => { retry.closest("li").remove(); askNow(q); } }, icon("refresh"), "Try again");
      pending.replaceWith(el("li", { class: "cc-msg cc-bot" }, el("p", { class: "cc-note" },
        err.status === 422 ? "Enter a question between 3 and 300 characters."
          : err.status === 429 ? "Too many questions from this network this hour. Try again later."
            : navigator.onLine === false ? "You're offline. Reconnect and try again." : `The answer did not load. ${err.message}`),
        err.status === 422 || err.status === 429 ? null : el("div", { class: "cc-actions" }, retry)));
    } finally {
      send.disabled = false;
      thread.lastElementChild?.scrollIntoView({ block: "nearest" });
      if (thread.scrollHeight > thread.clientHeight) thread.scrollTop = thread.lastElementChild.offsetTop - 8;
      input.focus();
    }
  } }, el("div", { class: "cc-input" }, input, count), send);

  const audience = el("div", { class: "cc-aud", role: "group", "aria-label": "Answer style" },
    ...[["staff", "Staff"], ["resident", "Plain words"]].map(([key, label]) => el("button", { type: "button", "data-aud": key, "aria-pressed": String(key === ccAudience),
      onclick: () => setAudience(key) }, label)));
  function setAudience(key) {
    ccAudience = key;
    audience.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.aud === key)));
  }
  const iconBtn = (name, label, onclick, extra = {}) => el("button", { type: "button", class: "cc-icon", "aria-label": label, title: label, onclick, ...extra }, icon(name));
  const expand = iconBtn("expand", "Expand", () => {
    const wide = panel.classList.toggle("cc-wide");
    expand.setAttribute("aria-label", wide ? "Shrink" : "Expand");
    expand.title = wide ? "Shrink" : "Expand";
    expand.replaceChildren(icon(wide ? "shrink" : "expand"));
  });
  const panel = el("section", { class: "cc-panel", id: "cc-panel", role: "dialog", "aria-modal": "false", "aria-labelledby": "cc-title", hidden: true },
    el("header", { class: "cc-head" },
      el("span", { class: "cc-avatar", "aria-hidden": "true" }, icon("ask")),
      el("div", { class: "cc-titles" }, el("h2", { id: "cc-title" }, "Ask the county"),
        el("p", { class: "cc-status" }, el("span", { class: "cc-dot", "aria-hidden": "true" }), "Checked by code · 21 agreements")),
      el("div", { class: "cc-tools" },
        iconBtn("plus", "New conversation", () => { reset(); input.focus(); }),
        expand,
        iconBtn("x", "Close", () => closeChat(true)))),
    el("div", { class: "cc-bar" }, el("span", { class: "cc-label-sm" }, "Answer for"), audience),
    thread, form,
    el("p", { class: "cc-foot" }, el("kbd", { class: "kbd" }, "Enter"), " send · ", el("kbd", { class: "kbd" }, "↑"), " last question · ",
      el("kbd", { class: "kbd" }, "Esc"), " close. Nothing is saved. Not legal advice."));
  let opener = launch;
  function openChat(from) {
    opener = from instanceof HTMLElement ? from : launch;
    panel.hidden = false;
    launch.setAttribute("aria-expanded", "true");
    launch.hidden = true;
    document.querySelectorAll("[data-open-chat]").forEach((b) => b.setAttribute("aria-expanded", "true"));
    input.focus();
  }
  function closeChat(focusBack) {
    panel.hidden = true;
    launch.setAttribute("aria-expanded", "false");
    launch.hidden = false;
    document.querySelectorAll("[data-open-chat]").forEach((b) => b.setAttribute("aria-expanded", "false"));
    if (focusBack) (opener?.isConnected && opener.offsetParent ? opener : launch).focus();
  }
  launch.addEventListener("click", () => openChat(launch));
  panel.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.stopPropagation(); closeChat(true); } });
  // "/" opens the chat from anywhere it is offered, unless the reader is typing.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    if (!document.documentElement.classList.contains("cc-on") || !panel.hidden) return;
    if (event.target.closest?.("input, textarea, select, [contenteditable='true']")) return;
    event.preventDefault();
    openChat(launch);
  });
  reset();
  document.body.append(launch, panel);
  return {
    open: openChat, close: closeChat,
    setContext(next) {
      const changed = (next?.id || null) !== (context?.id || null);
      context = next;
      if (changed && !asked.length) reset();
    },
  };
}

// ---------- Records request letter ----------
// Code drafts the letter from the review; "Make it read better" asks the model to edit it, and the server keeps the
// edit only if it adds no number, date or link and keeps every requested record. Nothing is sent from here.
async function openLetter(opener) {
  const dialog = byId("letter-dialog");
  const subject = byId("letter-subject"), text = byId("letter-body"), note = byId("letter-note");
  const polish = byId("letter-polish"), copy = byId("letter-copy");
  const id = dealState.id;
  const load = async (wantPolish) => {
    polish.disabled = true;
    note.textContent = wantPolish ? "Asking the model to edit the draft, then checking its edit…" : "Drafting…";
    try {
      const res = await api(`/api/deals/${encodeURIComponent(id)}/request-letter`, { method: "POST", body: { polish: wantPolish } });
      subject.value = res.subject;
      text.value = res.body;
      note.textContent = res.notice;
      note.classList.toggle("letter-ok", res.mode === "polished");
      polish.hidden = res.mode === "polished";
    } catch (err) {
      note.textContent = `The draft did not load. ${err.message}`;
    } finally {
      polish.disabled = false;
    }
  };
  polish.onclick = () => load(true);
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject.value}\n\n${text.value}`);
      toast("Letter copied. Paste it into an email to the records office.");
    } catch {
      text.select();
      toast("Select all and copy the letter.");
    }
  };
  dialog.onclose = () => opener?.focus();
  polish.hidden = false;
  dialog.showModal();
  await load(false);
  subject.focus();
}

function noClaimsNote({ canShow }) {
  const list = byId("doc-list");
  if (!list || !dealState) return;
  const docs = dealState.deal.documents || [];
  const uploading = [...uploads.values()].some((item) => item.dealId === dealState.id && !item.error);
  const show = !uploading && docs.length > 0 && docs.every((doc) => phaseOf(doc.status) === "done") && (dealState.review?.claims || []).length === 0;
  if (!show) { byId("no-claims-note")?.remove(); return; }
  if (!canShow) return;
  byId("no-claims-note")?.remove();
  const read = docs.length === 1 ? "This file was read, but it does not state" : "These files were read, but none of them states";
  list.after(el("p", { id: "no-claims-note", class: "no-claims-note", role: "status" },
    `${read} an affordable-housing commitment (homes, income limits, years or rent limits). Add the deal's staff report, letters or signed agreement to build its receipt.`));
}

function setupDropzone(dealId) {
  const zone = byId("dropzone");
  const input = byId("file-input");
  byId("choose-files").addEventListener("click", () => input.click());
  input.addEventListener("change", () => { addFiles(dealId, input.files); input.value = ""; });
  zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (event) => { event.preventDefault(); zone.classList.remove("over"); addFiles(dealId, event.dataTransfer.files); });
}

// Dropping files anywhere on a deal page also uploads them.
function setupPageDrop() {
  let depth = 0;
  const onDeal = () => current.view === "deal" && dealState;
  window.addEventListener("dragenter", (event) => { if (!onDeal() || !event.dataTransfer?.types.includes("Files")) return; depth += 1; document.body.classList.add("dragging"); });
  window.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) document.body.classList.remove("dragging"); });
  window.addEventListener("dragover", (event) => { if (onDeal()) event.preventDefault(); });
  window.addEventListener("drop", (event) => {
    depth = 0;
    document.body.classList.remove("dragging");
    if (!onDeal() || event.target.closest("#dropzone")) return;
    event.preventDefault();
    addFiles(dealState.id, event.dataTransfer.files);
  });
}

function addFiles(dealId, fileList) {
  if (isReadOnly()) { toast("Sample deals are read-only. Start a new deal to try your own PDFs.", { kind: "warn" }); return null; }
  for (const file of fileList) {
    if (file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) { toast(`${file.name} is not a PDF. Only PDF files can be read.`, { kind: "warn" }); continue; }
    if (file.size > MAX_UPLOAD) { toast(`${file.name} is ${fileSize(file.size)}. The limit is 20 MB.`, { kind: "warn" }); continue; }
    uploadOne(dealId, file);
  }
}

async function uploadOne(dealId, file) {
  const key = `${Date.now()}-${Math.random()}`;
  const item = { key, dealId, file, name: file.name, size: file.size, progress: 0, docId: null, error: null };
  uploads.set(key, item);
  renderDocs();
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name.replace(/\.pdf$/i, ""));
  try {
    const doc = await api(`/api/deals/${encodeURIComponent(dealId)}/documents`, {
      method: "POST", body: form,
      onProgress: (fraction) => { item.progress = fraction; if (dealState?.id === dealId) renderDocs(); },
    });
    item.docId = doc.id;
    if (doc.duplicate) toast("This file is already in the deal.", { kind: "info" });
    if (dealState?.id === dealId) {
      dealState.deal.documents = [...(dealState.deal.documents || []).filter((existing) => existing.id !== doc.id), doc];
      renderDocs();
      pollIfBusy();
    }
    uploads.delete(key);
  } catch (err) {
    item.progress = null;
    item.error = err.message;
    if (dealState?.id === dealId) renderDocs();
    toast(`${file.name} did not upload. ${err.message}`, { kind: "warn" });
  }
}

// Retry: ask the server to read a failed document again, then follow it like a new upload.
async function retryDocument(doc, button) {
  if (!dealState) return;
  const dealId = dealState.id;
  button.disabled = true;
  try {
    const fresh = await api(`/api/deals/${encodeURIComponent(dealId)}/documents/${encodeURIComponent(doc.id)}/retry`, { method: "POST" });
    if (dealState?.id !== dealId) return;
    dealState.deal.documents = (dealState.deal.documents || []).map((d) => (d.id === doc.id ? { ...d, ...(fresh || {}), status: fresh?.status || "queued", error: null } : d));
    renderDocs();
    toast(`Reading ${docName(doc)} again.`, { kind: "info" });
    pollIfBusy();
  } catch (err) {
    button.disabled = false;
    const why = {
      403: "Sample deals are read-only. Start a new deal to try your own PDFs.",
      404: "Retry is not available on this server yet.",
      405: "Retry is not available on this server yet.",
      409: `${docName(doc)} is still being read. Wait for it to finish.`,
      429: "That is the retry limit for this hour. Try again later.",
    }[err.status];
    toast(why || `${docName(doc)} could not be retried. ${err.message}`, { kind: "warn" });
  }
}

function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }

function pollIfBusy() {
  stopPolling();
  if (!dealState) return;
  const busy = (dealState.deal.documents || []).some((doc) => !["done", "failed"].includes(phaseOf(doc.status)));
  if (!busy) return;
  const dealId = dealState.id;
  pollTimer = setTimeout(async () => {
    if (current.view !== "deal" || dealState?.id !== dealId) return;
    try {
      const before = new Map((dealState.deal.documents || []).map((doc) => [doc.id, phaseOf(doc.status)]));
      const deal = await api(`/api/deals/${encodeURIComponent(dealId)}`);
      if (dealState?.id !== dealId) return;
      dealState.deal = deal;
      let changed = false;
      for (const doc of deal.documents) {
        const was = before.get(doc.id);
        const now = phaseOf(doc.status);
        if (was && was !== now && now === "done") { changed = true; toast(`${docName(doc)} was read and its quotes were checked.`); }
        if (was && was !== now && now === "failed") { changed = true; toast(`${docName(doc)} could not be read. ${doc.error || ""}`.trim(), { kind: "warn" }); }
      }
      renderDocs();
      if (changed) {
        const review = await api(`/api/deals/${encodeURIComponent(dealId)}/review`);
        if (dealState?.id !== dealId) return;
        setDeal(dealId, deal, review);
        renderReview({ keepTab: true });
      }
    } catch (err) { /* Try again on the next tick. */ }
    pollIfBusy();
  }, 1500);
}

// ---------- Source panel: the real PDF page with the quote highlighted ----------
let sourceOpener = null;
let sourceToken = 0;

function markText(paragraphs, quote) {
  return paragraphs.map((text, index) => {
    let at = text.indexOf(quote);
    if (at === -1) at = text.toLowerCase().indexOf(quote.toLowerCase());
    if (at === -1) return el("p", { class: index === 0 && /^MADE-UP/.test(text) ? "page-label" : null }, text);
    return el("p", {}, text.slice(0, at), el("mark", {}, text.slice(at, at + quote.length)), text.slice(at + quote.length));
  });
}

async function pageParagraphs(doc, pageNumber) {
  const local = doc.pages?.find?.((item) => item.page === pageNumber);
  if (local) return local.paragraphs;
  const data = await api(`/api/deals/${encodeURIComponent(dealState.id)}/documents/${encodeURIComponent(doc.id)}/pages/${pageNumber}`);
  return String(data.text || "").split(/\n\s*\n/).filter(Boolean);
}

function openSource(claim, opener, { modal = true } = {}) {
  const doc = dealState.documentsById.get(claim.document) || { id: claim.document, title: claim.document_type, type: claim.document_type, date: claim.date, pages: [] };
  const pageCount = Array.isArray(doc.pages) ? doc.pages.length : (doc.page_count ?? doc.pages);
  sourceOpener = opener;
  byId("source-title").textContent = docName(doc);
  const status = el("p", { class: "sp-status", role: "status" });
  const stage = el("div", { class: "pdf-stage" }, el("span", { class: "skeleton" }));
  const fallback = el("div", { class: "fallback", hidden: true });
  const pager = el("div", { class: "sp-pager" });
  byId("source-body").replaceChildren(...[
    el("blockquote", { class: "sp-quote", style: "margin:0" }, `“${claim.quote}”`),
    el("div", { class: "sp-status" }, quoteBadge(claim), tag(claim.status), claim.from_scan ? tag("machine", "From scan") : null),
    pager, stage, status, fallback,
    el("dl", { class: "facts" },
      el("dt", {}, "Document"), el("dd", {}, `${doc.type} · ${formatDate(doc.date)}`),
      el("dt", {}, "Quote check"), el("dd", {}, claim.quote_checked ? "Found word for word on this page" : "Flagged for human review"),
      el("dt", {}, "Signed by"), el("dd", {}, doc.signed_by?.length ? doc.signed_by.join(", ") : "Not a signed record")),
    claim.review_note ? el("p", { class: "note-box" }, el("strong", {}, "Reviewer note: "), claim.review_note) : null
  ].filter(Boolean));
  // The tour opens it without a backdrop so its caption stays usable on top.
  if (modal) byId("source-dialog").showModal(); else byId("source-dialog").show();
  showSourcePage(claim, doc, claim.page, pageCount, { stage, status, fallback, pager });
}

async function showSourcePage(claim, doc, pageNumber, pageCount, parts) {
  const token = ++sourceToken;
  const { stage, status, fallback, pager } = parts;
  const onQuotePage = pageNumber === claim.page;
  byId("source-meta").replaceChildren(`${doc.type} · ${formatDate(doc.date)} · `, el("span", { class: "mono" }, `Page ${pageNumber}${pageCount ? ` of ${pageCount}` : ""}`));
  const go = (n) => showSourcePage(claim, doc, n, pageCount, parts);
  pager.replaceChildren(
    el("button", { type: "button", class: "btn btn-secondary btn-small", disabled: pageNumber <= 1, "aria-label": "Previous page", onclick: () => go(pageNumber - 1) }, icon("prev"), "Previous"),
    onQuotePage ? el("span", { class: "hint nowrap" }, `Quote on p. ${claim.page}`) : el("button", { type: "button", class: "btn-link", onclick: () => go(claim.page) }, `Back to p. ${claim.page}`),
    el("button", { type: "button", class: "btn btn-secondary btn-small", disabled: pageCount ? pageNumber >= pageCount : false, "aria-label": "Next page", onclick: () => go(pageNumber + 1) }, "Next", icon("next")),
  );
  stage.hidden = false;
  stage.replaceChildren(el("span", { class: "skeleton" }));
  fallback.hidden = true;
  status.textContent = "Loading the PDF page.";

  const showFallback = async (reason) => {
    try {
      const paragraphs = await pageParagraphs(doc, pageNumber);
      if (token !== sourceToken) return;
      fallback.replaceChildren(el("p", { class: "hint", style: "margin-bottom:.5rem" }, reason), el("div", { class: "page-sheet" }, markText(paragraphs, onQuotePage ? claim.quote : "\u0000")));
      fallback.hidden = false;
    } catch (err) {
      fallback.replaceChildren(el("p", { class: "hint" }, `${reason} The page text did not load either.`));
      fallback.hidden = false;
    }
  };

  const url = fileUrl(dealState.id, doc.id);
  try {
    if (!url) throw new Error("No PDF file for this record.");
    const { renderPage } = await import("./pdfview.js");
    const width = Math.max(280, stage.clientWidth || 600);
    const result = await renderPage({ url, pageNumber, quote: onQuotePage ? claim.quote : null, container: stage, width, headers: mock ? {} : { "X-Demo-Session": demoSession() } });
    if (token !== sourceToken) return;
    if (!pageCount) pageCount = result.pages;
    if (!onQuotePage) { status.textContent = `Showing page ${pageNumber}. The quote is on page ${claim.page}.`; return; }
    if (result.mark) {
      status.replaceChildren(el("span", { class: "badge badge-ok" }, svg("0 0 16 16", ICONS.ok), "Highlighted"), "The quote is highlighted on the PDF page.",
        el("button", { type: "button", class: "btn-link", onclick: (event) => { event.currentTarget.remove(); showFallback("Page text, with the quote marked:"); } }, "Show page text"));
      result.mark.scrollIntoView({ block: "center", behavior: reducedMotion.matches ? "auto" : "smooth" });
      layerMarks(result.mark).forEach((mark) => mark.classList.add("pulse"));
    } else {
      status.replaceChildren(el("span", { class: "badge badge-warn" }, svg("0 0 16 16", ICONS.not_located), "Not matched"), "The quote could not be matched on this page image.");
      showFallback("Page text, with the quote marked:");
    }
  } catch (err) {
    if (token !== sourceToken) return;
    stage.hidden = true;
    status.textContent = "";
    showFallback("The PDF page could not be shown here. Page text, with the quote marked:");
  }
}

// A reminder's "Source" link opens the deal with that claim's page already showing.
function openSourceFromLink(claimId) {
  const claim = dealState?.claimsById.get(claimId);
  history.replaceState(null, "", `#/deals/${encodeURIComponent(dealState.id)}`);
  current = { view: "deal", id: dealState.id, tab: null };
  if (!claim) { toast("That source is no longer in this deal.", { kind: "info" }); return; }
  const opener = [...document.querySelectorAll("#claim-rows button.btn-small")].find((button) => button.dataset.claim === claimId) || byId("main");
  openSource(claim, opener);
}

function setupSourceDialog() {
  const dialog = byId("source-dialog");
  byId("source-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => {
    // The close event arrives late. If the panel was already reopened, leave the new page alone.
    if (dialog.open) return;
    sourceToken += 1;
    sourceOpener?.focus();
  });
}

// ---------- Shared read-only view ----------
async function renderShared(token) {
  document.title = "Shared receipt · Promise Ledger";
  const view = byId("view-shared");
  const article = el("article", { class: "receipt paper", "aria-labelledby": "shared-title", "aria-busy": "true" },
    [80, 60, 90, 70, 85].map((width) => el("span", { class: "skeleton sk-line", style: `width:${width}%` })));
  const title = el("h1", { id: "shared-title" }, "Shared receipt");
  view.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, title, el("p", { class: "page-sub" }, "A read-only copy of a Promise Ledger receipt. It cannot be edited from this link.")),
      el("div", { class: "page-actions" }, el("button", { type: "button", class: "btn btn-primary", onclick: () => window.print() }, icon("print"), "Print"))),
    el("p", { class: "shared-note" }, el("span", { class: "badge badge-info" }, svg("0 0 16 16", ICONS.machine), "Read-only"), "Each quote shows its document, date and page."),
    el("div", { class: "printer" }, el("div", { class: "printer-slot", "aria-hidden": "true" }), el("div", { class: "paper-clip" }, article)),
  );
  try {
    // A /r/{token} page arrives with the read-only review already inside it.
    const inline = byId("review-data")?.textContent.trim();
    const shipped = inline ? JSON.parse(inline) : null;
    const review = shipped?.read_only ? plainLabels(shipped) : await api(`/api/share/${encodeURIComponent(token)}`);
    if (current.view !== "shared") return;
    title.textContent = `${review.project}, ${review.city}`;
    document.title = `${review.project} receipt · Promise Ledger`;
    article.removeAttribute("aria-busy");
    renderReceipt(article, review, { titleTag: "h2" });
    printOut(article, { stampDelay: 300 });
  } catch (err) {
    article.removeAttribute("aria-busy");
    article.replaceChildren(el("p", {}, err.status === 404 ? "This link is not valid or has been turned off. Ask the person who shared it for a new link." : `The receipt did not load. ${err.message}`));
  }
}

// ---------- Display settings ----------
function setupToggles() {
  const root = document.documentElement;
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const theme = byId("theme-toggle");
  const isDark = () => (root.dataset.theme || (system.matches ? "dark" : "light")) === "dark";
  // The button names the theme it switches to, and its icon matches: a sun for "Light mode", a moon for "Dark mode".
  const label = theme.querySelector(".theme-label");
  const syncTheme = () => {
    const dark = isDark();
    theme.dataset.dark = String(dark);
    label.textContent = dark ? "Light mode" : "Dark mode";
  };
  // The site follows the system theme. A click overrides it; choosing the system's own theme goes back to following it.
  theme.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    const followsSystem = next === (system.matches ? "dark" : "light");
    if (followsSystem) delete root.dataset.theme;
    else root.dataset.theme = next;
    try {
      if (followsSystem) localStorage.removeItem("pl-theme-choice");
      else localStorage.setItem("pl-theme-choice", next);
    } catch (err) { /* This visit only. */ }
    syncTheme();
  });
  system.addEventListener("change", syncTheme);
  syncTheme();

  const text = byId("text-toggle");
  const syncText = () => text.setAttribute("aria-pressed", String(root.classList.contains("text-large")));
  text.addEventListener("click", () => {
    root.classList.toggle("text-large");
    try { localStorage.setItem("pl-text", root.classList.contains("text-large") ? "large" : "normal"); } catch (err) { /* This visit only. */ }
    syncText();
  });
  syncText();
}

// ---------- Navigation ----------
// The header tightens and gains a shadow once the page scrolls, a thin bar shows how far down the page you are, and an
// indicator slides to the current section. Below 1100px the links move into a menu. Every effect is skipped with
// reduced motion, and the menu closes on Escape, on a click outside it, and when the route changes.
const nav = { header: null, ind: null, menu: null, button: null };
function placeNavIndicator() {
  const { ind } = nav;
  const on = document.querySelector('.main-nav a[aria-current="page"]');
  if (!ind) return;
  if (!on || !on.offsetParent) { ind.style.opacity = "0"; return; }
  ind.style.opacity = "1";
  ind.style.width = `${on.offsetWidth}px`;
  ind.style.transform = `translateX(${on.offsetLeft}px)`;
}
function setMenu(open, { focus = true } = {}) {
  if (!nav.menu) return;
  nav.menu.hidden = !open;
  nav.button.setAttribute("aria-expanded", String(open));
  nav.button.setAttribute("aria-label", open ? "Close menu" : "Menu");
  nav.header.classList.toggle("menu-open", open);
  document.documentElement.classList.toggle("menu-open", open);
  if (open && focus) (nav.menu.querySelector('[aria-current="page"]') || nav.menu.querySelector("a"))?.focus();
  else if (!open && focus && nav.menu.contains(document.activeElement)) nav.button.focus();
}
function setupNav() {
  nav.header = document.querySelector(".site-header");
  nav.ind = document.querySelector(".nav-ind");
  nav.menu = byId("mobile-menu");
  nav.button = byId("menu-btn");
  const bar = document.querySelector(".nav-progress span");
  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const y = window.scrollY;
      nav.header.classList.toggle("scrolled", y > 8);
      const room = document.documentElement.scrollHeight - window.innerHeight;
      if (bar) bar.style.transform = `scaleX(${room > 0 ? Math.min(1, y / room) : 0})`;
    });
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", () => { placeNavIndicator(); if (window.innerWidth > 1100) setMenu(false, { focus: false }); }, { passive: true });
  document.fonts?.ready.then(placeNavIndicator);
  nav.button?.addEventListener("click", () => setMenu(nav.menu.hidden));
  nav.menu?.addEventListener("click", (event) => { if (event.target.closest("a")) setMenu(false, { focus: false }); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && nav.menu && !nav.menu.hidden) setMenu(false); });
  document.addEventListener("click", (event) => {
    if (nav.menu && !nav.menu.hidden && !nav.menu.contains(event.target) && !nav.button.contains(event.target)) setMenu(false, { focus: false });
  });
  nav.button?.setAttribute("aria-expanded", "false");
  for (const button of document.querySelectorAll("[data-open-chat]")) {
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", () => { setMenu(false, { focus: false }); countyChat?.open(button); });
  }
  onScroll();
}

// ---------- Receipt printer ----------
// The paper feeds out of its slot, then the review stamp lands once it is on screen.
// With reduced motion the receipt simply appears with its stamp in place.
function landStamp(stamp, delay = 0) {
  if (!stamp) return;
  stamp.classList.remove("landing", "landed");
  if (reducedMotion.matches) { stamp.classList.add("landed"); return; }
  const land = () => setTimeout(() => { stamp.classList.add("landed", "landing"); }, delay);
  if (!("IntersectionObserver" in window)) { land(); return; }
  const observer = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting) return;
    observer.disconnect();
    land();
  }, { threshold: 0.9 });
  observer.observe(stamp);
}

function printOut(paper, { stampDelay = 1100 } = {}) {
  if (!paper) return;
  const stamp = paper.querySelector(".receipt-stamp");
  if (!reducedMotion.matches) {
    paper.classList.remove("feeding");
    void paper.offsetWidth; // Restart the feed.
    paper.classList.add("feeding");
  }
  landStamp(stamp, reducedMotion.matches ? 0 : stampDelay);
}

// ---------- Landing motion: hero receipt assembly, scroll reveal, count-up ----------
// All of it is decoration. The content is in the page from the start, and reduced motion shows it still.
const hero = { loops: 0, timers: [], visible: true, running: false };
const HERO_LOOPS = 3;

function heroClear() { hero.timers.forEach(clearTimeout); hero.timers = []; }

function heroPlay() {
  const card = byId("hero-receipt");
  if (!card || reducedMotion.matches || hero.loops >= HERO_LOOPS || !hero.visible || current.view !== "home") { hero.running = false; return; }
  hero.running = true;
  hero.loops += 1;
  const rows = [...card.querySelectorAll(".rc-rows li")];
  card.classList.add("assembling", "checking");
  card.classList.remove("done");
  rows.forEach((row) => row.classList.remove("on"));
  const live = card.querySelector(".rc-live-text");
  if (live) live.textContent = "Checking";
  const paper = card.querySelector(".paper");
  const stamp = card.querySelector(".receipt-stamp");
  stamp?.classList.remove("landed", "landing");
  paper.classList.remove("feeding");
  void paper.offsetWidth;
  paper.classList.add("feeding");
  // Rows are looked up when each step fires, because live data can replace them mid-loop.
  const first = 900;
  rows.forEach((row, index) => hero.timers.push(setTimeout(() => card.querySelectorAll(".rc-rows li")[index]?.classList.add("on"), first + index * 480)));
  const end = first + rows.length * 480 + 250;
  hero.timers.push(setTimeout(() => {
    card.querySelectorAll(".rc-rows li").forEach((row) => row.classList.add("on"));
    card.classList.add("done");
    card.classList.remove("checking");
    if (live) live.textContent = "Checked";
    stamp?.classList.add("landed", "landing");
  }, end));
  // Hold the finished receipt, then replay. After the last loop it stays finished.
  hero.timers.push(setTimeout(() => { if (hero.loops < HERO_LOOPS) heroPlay(); else hero.running = false; }, end + 5200));
}

function heroFinish() {
  const card = byId("hero-receipt");
  if (!card) return;
  heroClear();
  hero.running = false;
  card.classList.add("done");
  card.classList.remove("checking");
  card.querySelectorAll(".rc-rows li").forEach((row) => row.classList.add("on"));
  card.querySelector(".paper")?.classList.remove("feeding");
  card.querySelector(".receipt-stamp")?.classList.add("landed");
  const live = card.querySelector(".rc-live-text");
  if (live) live.textContent = "Checked";
}

function setupHeroMotion() {
  const card = byId("hero-receipt");
  if (!card || reducedMotion.matches || !("IntersectionObserver" in window)) return;
  new IntersectionObserver(([entry]) => {
    hero.visible = entry.isIntersecting;
    if (!hero.visible && hero.running) { heroFinish(); }
    else if (hero.visible && !hero.running && hero.loops < HERO_LOOPS) heroPlay();
  }, { threshold: 0.35 }).observe(card);
  reducedMotion.addEventListener?.("change", () => { if (reducedMotion.matches) heroFinish(); });
}

function countStat(node) {
  const decimals = Number(node.dataset.decimals || 0);
  animateNumber(node, Number(node.dataset.count), 900, (v) => v.toFixed(decimals));
}

// Cards on rendered views rise in as they come into view, a few at a time. Content is never hidden without script:
// the class that hides it is added here and removed when the card is seen (or at once with reduced motion).
const RISE = ".card, .kpi, .runway, .county-search-card, .county-table-card, .tile, .summary-box, .stepper-wrap, .deal-row";
let riseObserver = null;
function riseIn(root) {
  if (!root || reducedMotion.matches || !("IntersectionObserver" in window)) return;
  riseObserver ||= new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add("rise-in");
      entry.target.classList.remove("rise-wait");
      riseObserver.unobserve(entry.target);
    }
  }, { threshold: 0, rootMargin: "0px 0px -4% 0px" }); // 0: a card taller than the screen (the phone table) still rises
  let i = 0;
  for (const node of root.querySelectorAll(RISE)) {
    if (node.closest(".rise-wait") || node.dataset.risen) continue;
    node.dataset.risen = "1";
    node.style.setProperty("--rise", String(i++ % 6));
    node.classList.add("rise-wait");
    riseObserver.observe(node);
  }
}

// Looping decoration (glows, sweeps, pulses) pauses while its section is off screen, so it costs nothing there.
function setupOffscreenPause() {
  if (!("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) e.target.classList.toggle("is-off", !e.isIntersecting);
  }, { rootMargin: "100px" });
  const watch = () => document.querySelectorAll(".hero, .real-strip, .m3, .cta-band, .effort").forEach((n) => {
    if (!n.dataset.watched) { n.dataset.watched = "1"; io.observe(n); }
  });
  watch();
  new MutationObserver(watch).observe(document.querySelector("main") || document.body, { childList: true, subtree: true });
}

function setupSpotlight() {
  // A soft light follows the pointer across cards: decoration only, mouse and pen only.
  if (reducedMotion.matches || document.documentElement.classList.contains("lite") || !window.matchMedia("(hover: hover)").matches) return;
  const SEL = ".card, .kpi, .tile, .bento-tile, .runway, .summary-box, .real-strip, .who-card";
  document.addEventListener("pointermove", (event) => {
    const card = event.target.closest?.(SEL);
    if (!card) return;
    const box = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${event.clientX - box.left}px`);
    card.style.setProperty("--my", `${event.clientY - box.top}px`);
  }, { passive: true });
}

function setupReveal() {
  const sections = [...document.querySelectorAll(".reveal")];
  const reveal = (section) => {
    if (section.classList.contains("in")) return;
    section.classList.add("in");
    section.querySelectorAll("[data-count]").forEach(countStat);
  };
  if (reducedMotion.matches || !("IntersectionObserver" in window)) { sections.forEach((section) => section.classList.add("in")); return; }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) if (entry.isIntersecting) { reveal(entry.target); observer.unobserve(entry.target); }
  }, { threshold: 0.18, rootMargin: "0px 0px -8% 0px" });
  sections.forEach((section) => observer.observe(section));
}

// ---------- Command palette (Ctrl or Cmd + K) ----------
const CMD_ICONS = {
  go: [["path", { d: "M5 12h14M13 6l6 6-6 6" }]],
  deal: [["path", { d: "M6 3h12v18l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5-2 1.5z" }], ["path", { d: "M9 8h6M9 12h6" }]],
  tab: [["rect", { x: 3, y: 5, width: 18, height: 14, rx: 2 }], ["path", { d: "M3 9h18M9 5v4" }]],
  file: UI_ICONS.file,
  theme: [["path", { d: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" }]],
  text: [["path", { d: "M4 18 9 6l5 12M5.8 14h6.4M15 18l3-7 3 7M15.8 16h4.4" }]],
  plus: UI_ICONS.plus,
  link: UI_ICONS.link,
};
const TAB_NAMES = { claims: "Claims", changes: "What changed", questions: "Open questions", receipt: "Receipt", extract: "Read new text", glossary: "Glossary" };
const cmd = { items: [], shown: [], active: 0, deals: null, opener: null };

async function commandList() {
  const list = [
    { group: "Go to", label: "Home", icon: "go", run: () => { location.hash = "#/"; } },
    { group: "Go to", label: "Deals", icon: "go", run: () => { location.hash = "#/deals"; } },
    ...Object.entries(STATIC_PAGES).map(([path, label]) => ({ group: "Go to", label, icon: "go", run: () => { location.hash = `#/${path}`; } })),
  ];
  if (!cmd.deals) { try { cmd.deals = await api("/api/deals"); } catch (err) { cmd.deals = []; } }
  for (const deal of cmd.deals) list.push({ group: "Deals", label: deal.name, hint: deal.city, icon: "deal", run: () => { location.hash = `#/deals/${encodeURIComponent(deal.id)}`; } });
  if (current.view === "deal" && dealState && !byId("details").hidden) {
    for (const [id, name] of Object.entries(TAB_NAMES)) {
      list.push({ group: `${dealState.deal.name} tabs`, label: name, icon: "tab", run: () => { activateTab(id, { updateHash: true }); byId("tablist").scrollIntoView({ block: "start" }); byId(`tab-${id}`).focus(); } });
    }
  }
  if (current.view === "deal" && dealState) {
    const buttons = [...document.querySelectorAll("#deal-actions [data-export]")];
    buttons.forEach((button) => list.push({ group: "Actions", label: `Preview ${button.textContent.trim()} export`, icon: "file", run: () => button.click() }));
    list.push({ group: "Actions", label: "Share read-only link", icon: "link", run: () => byId("share-btn")?.click() });
    list.push({ group: "Actions", label: "Take the 60-second tour", icon: "go", run: () => startTour(byId("tour-start")) });
  }
  list.push({ group: "Actions", label: "New deal", icon: "plus", run: () => document.querySelector(".view:not([hidden]) [data-new-deal], [data-new-deal]")?.click() });
  list.push({ group: "Display", label: `Switch to ${byId("theme-toggle").dataset.dark === "true" ? "light" : "dark"} mode`, icon: "theme", run: () => byId("theme-toggle").click() });
  list.push({ group: "Display", label: "Toggle larger text", icon: "text", run: () => byId("text-toggle").click() });
  return list;
}

function renderCommands() {
  const query = byId("cmdk-input").value.trim().toLowerCase();
  cmd.shown = cmd.items.filter((item) => !query || `${item.label} ${item.group} ${item.hint || ""}`.toLowerCase().includes(query));
  cmd.active = Math.min(cmd.active, Math.max(0, cmd.shown.length - 1));
  const rows = [];
  let group = null;
  cmd.shown.forEach((item, index) => {
    if (item.group !== group) { group = item.group; rows.push(el("li", { class: "cmdk-group", role: "presentation" }, group)); }
    rows.push(el("li", {
      class: "cmdk-item", role: "option", id: `cmd-${index}`, "aria-selected": String(index === cmd.active),
      onclick: () => runCommand(index), onmousemove: () => { if (cmd.active !== index) { cmd.active = index; markActive(); } },
    }, svg("0 0 24 24", CMD_ICONS[item.icon] || CMD_ICONS.go), el("span", {}, item.label), item.hint ? el("span", { class: "cmdk-hint" }, item.hint) : null));
  });
  byId("cmdk-list").replaceChildren(...rows);
  byId("cmdk-empty").hidden = cmd.shown.length > 0;
  markActive();
}

function markActive() {
  byId("cmdk-list").querySelectorAll(".cmdk-item").forEach((row) => row.setAttribute("aria-selected", String(row.id === `cmd-${cmd.active}`)));
  const input = byId("cmdk-input");
  if (cmd.shown.length) {
    input.setAttribute("aria-activedescendant", `cmd-${cmd.active}`);
    byId(`cmd-${cmd.active}`)?.scrollIntoView({ block: "nearest" });
  } else input.removeAttribute("aria-activedescendant");
}

function runCommand(index) {
  const item = cmd.shown[index];
  if (!item) return;
  cmd.opener = null; // The command decides where focus goes next.
  byId("cmdk").close();
  item.run();
}

async function openCommands() {
  const dialog = byId("cmdk");
  if (dialog.open) return;
  cmd.opener = document.activeElement;
  cmd.deals = null;
  byId("cmdk-input").value = "";
  cmd.active = 0;
  cmd.items = [];
  renderCommands();
  dialog.showModal();
  byId("cmdk-input").focus();
  cmd.items = await commandList();
  renderCommands();
}

function setupCommands() {
  const dialog = byId("cmdk");
  const input = byId("cmdk-input");
  input.spellcheck = false;
  byId("cmdk-open").addEventListener("click", openCommands);
  if (!/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) {
    byId("cmdk-open").setAttribute("aria-keyshortcuts", "Control+K");
  } else {
    byId("cmdk-open").querySelector(".kbd").textContent = "⌘K";
    byId("cmdk-open").setAttribute("aria-keyshortcuts", "Meta+K");
  }
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (dialog.open) dialog.close(); else openCommands();
    }
  });
  input.addEventListener("input", () => { cmd.active = 0; renderCommands(); });
  input.addEventListener("keydown", (event) => {
    const count = cmd.shown.length;
    if (event.key === "ArrowDown" && count) { event.preventDefault(); cmd.active = (cmd.active + 1) % count; markActive(); }
    else if (event.key === "ArrowUp" && count) { event.preventDefault(); cmd.active = (cmd.active - 1 + count) % count; markActive(); }
    else if (event.key === "Home" && count && !input.value) { event.preventDefault(); cmd.active = 0; markActive(); }
    else if (event.key === "End" && count && !input.value) { event.preventDefault(); cmd.active = count - 1; markActive(); }
    else if (event.key === "Enter") { event.preventDefault(); runCommand(cmd.active); }
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => { cmd.opener?.focus?.(); });
}

// ---------- Export preview ----------
// Excel and CSV open a preview first. It is built from /export.json, which uses the same rows as the files.
const xp = { data: null, sheet: 0, format: "xlsx", dealId: null, opener: null };

function exportCell(column, value, row = {}) {
  const text = value === null || value === undefined ? "" : String(value);
  // A term with no wording on file has nothing to compare, so it is not shown as matching.
  if (column === "Wording differs" && text !== "Yes" && /not located/i.test(row.Result || "")) return el("span", { class: "cell-muted" }, "Not compared");
  if (column === "Wording differs") return text === "Yes" ? tag("differs") : tag("ok", "Matches");
  if (column === "Quote found on page" || column === "Verified") return /^(yes|found)$/i.test(text) ? el("span", { class: "badge badge-ok" }, svg("0 0 16 16", ICONS.ok), "Found") : el("span", { class: "badge badge-warn" }, svg("0 0 16 16", ICONS.not_located), "Flagged for human review");
  if (column === "Result" && /not located/i.test(text)) return tag("not_located", text);
  if (column === "Signed record") return text === "Yes" ? tag("signed", "Yes") : el("span", { class: "cell-muted" }, text || "No");
  if ((column === "Stage" || column.startsWith("Furthest stage")) && STAGES.includes(text.toLowerCase())) return tag(text.toLowerCase(), text);
  if (column === "Quote") return el("span", { class: "quote" }, text);
  if (column === "Decided" || column === "When") return el("span", { class: "mono nowrap" }, text);
  if (column === "Note") return el("span", { class: "xp-note-cell" }, text);
  if (column === "Decision") {
    const key = Object.keys(DECISION_LABEL).find((k) => DECISION_LABEL[k] === text);
    return key ? decisionTag({ decision: key, label: text }) : el("span", { class: "cell-muted" }, text);
  }
  return text;
}

const NUMERIC = new Set(["Page", "Date"]);

function renderExportSheet() {
  const sheets = visibleSheets();
  const sheet = sheets[xp.sheet] || sheets[0];
  const file = xp.format === "csv" ? xp.data.files.csv : xp.data.files.xlsx;
  byId("xp-title").textContent = `${xp.data.title}.${xp.format}`;
  byId("xp-meta").textContent = `${file} · ${plural(sheet.rows.length, "row")} · Sheet: ${sheet.name}`;
  byId("xp-tabs").hidden = sheets.length < 2;
  byId("xp-tabs").replaceChildren(...sheets.map((item, index) => el("button", {
    type: "button", role: "tab", id: `xp-tab-${index}`, "aria-controls": "xp-scroll", "aria-selected": String(index === xp.sheet), tabindex: index === xp.sheet ? "0" : "-1",
    onclick: () => { xp.sheet = index; renderExportSheet(); byId(`xp-tab-${index}`).focus(); },
    onkeydown: (event) => {
      const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: sheets.length - 1 };
      if (!(event.key in moves)) return;
      event.preventDefault();
      xp.sheet = (moves[event.key] + sheets.length) % sheets.length;
      renderExportSheet();
      byId(`xp-tab-${xp.sheet}`).focus();
    },
  }, item.name, el("span", { class: "tab-count" }, String(item.rows.length)))));
  byId("xp-scroll").setAttribute("aria-label", `${sheet.name} sheet preview`);
  if (sheets.length > 1) byId("xp-scroll").setAttribute("aria-labelledby", `xp-tab-${xp.sheet}`); else byId("xp-scroll").removeAttribute("aria-labelledby");
  byId("xp-table").replaceChildren(
    el("caption", { class: "visually-hidden" }, `${sheet.name}: ${plural(sheet.rows.length, "row")}`),
    el("thead", {}, el("tr", {}, sheet.columns.map((column) => el("th", { scope: "col", class: NUMERIC.has(column) ? "num-col" : null }, column)))),
    el("tbody", {}, sheet.rows.length
      ? sheet.rows.map((row) => {
        const named = Object.fromEntries(sheet.columns.map((column, index) => [column, row[index]]));
        return el("tr", {}, row.map((value, index) => el("td", { class: NUMERIC.has(sheet.columns[index]) ? "num-col mono" : null }, exportCell(sheet.columns[index], value, named))));
      })
      : el("tr", {}, el("td", { colspan: sheet.columns.length, class: "cell-muted" }, "No rows yet."))),
  );
  byId("xp-scroll").scrollTo({ top: 0, left: 0 });
}

// The CSV holds the Claims sheet only, so a CSV preview shows just that sheet.
const visibleSheets = () => (xp.format === "csv" ? xp.data.sheets.filter((sheet) => sheet.name === xp.data.csv_sheet) : xp.data.sheets);

function csvText(sheet) {
  const cell = (value) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [sheet.columns, ...sheet.rows].map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

async function openExport(dealId, format, opener) {
  const dialog = byId("export-dialog");
  xp.opener = opener;
  xp.format = format;
  xp.dealId = dealId;
  xp.sheet = 0;
  opener.disabled = true;
  try {
    xp.data = await api(`/api/deals/${encodeURIComponent(dealId)}/export.json`);
  } catch (err) {
    toast(`The preview did not load. ${err.message}`, { kind: "warn" });
    return;
  } finally {
    opener.disabled = false;
  }
  const base = `/api/deals/${encodeURIComponent(dealId)}`;
  for (const ext of ["xlsx", "csv"]) {
    const link = byId(`xp-dl-${ext}`);
    link.href = `${base}/export.${ext}`;
    link.download = xp.data.files[ext];
    link.onclick = (event) => {
      event.preventDefault();
      if (mock) { mockDownload(`${base}/export.${ext}`, xp.data.files[ext].replace(/\.xlsx$/, ".csv"), ext); return; }
      downloadFile(`${base}/export.${ext}`, xp.data.files[ext]);
    };
  }
  byId("xp-dl-xlsx").classList.toggle("btn-primary", format === "xlsx");
  byId("xp-dl-xlsx").classList.toggle("btn-secondary", format !== "xlsx");
  byId("xp-dl-csv").classList.toggle("btn-primary", format === "csv");
  byId("xp-dl-csv").classList.toggle("btn-secondary", format !== "csv");
  byId("xp-icon").textContent = format.toUpperCase();
  renderExportSheet();
  dialog.showModal();
  byId(`xp-dl-${format}`).focus();
}

function setupExportDialog() {
  const dialog = byId("export-dialog");
  byId("xp-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => xp.opener?.focus());
  byId("xp-copy").addEventListener("click", async () => {
    const sheet = visibleSheets()[xp.sheet];
    try {
      await navigator.clipboard.writeText(csvText(sheet));
      toast(`Copied the ${sheet.name} sheet as CSV.`);
    } catch (err) {
      toast("The clipboard is blocked here. Use Download .csv instead.", { kind: "info" });
    }
  });
}

// ---------- Reviewer decisions: people decide ----------
// Each claim and each open question can be marked Confirmed, Needs follow-up or Disputed, with a note.
// Decisions sit beside the record. They never change a claim's stage.
const DECISION_ORDER = ["confirmed", "follow_up", "disputed"];
const DECISION_TEXT = { confirmed: "Confirm", follow_up: "Needs follow-up", disputed: "Disputed" };
const DECISION_LABEL = { confirmed: "Confirmed", follow_up: "Needs follow-up", disputed: "Disputed" };
const DECISION_ICON = {
  confirmed: [["path", { d: "M3.5 8.5l3 3 6-7" }]],
  follow_up: [["circle", { cx: 8, cy: 8, r: 6 }], ["path", { d: "M8 4.8V8l2.2 1.4" }]],
  disputed: [["path", { d: "M3.5 13.5V2.8M3.5 3h8l-1.6 2.6L11.5 8h-8" }]],
};
const MAX_NOTE = 500;
const decisionsOf = (review) => review?.decisions || { latest: {}, log: [], progress: null, stamp: null };

function reviewerName() { try { return localStorage.getItem("pl-reviewer") || ""; } catch (err) { return ""; } }
function rememberReviewer(name) { try { localStorage.setItem("pl-reviewer", name); } catch (err) { /* This visit only. */ } }

function formatWhen(iso) {
  const d = new Date(iso);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function decisionTag(event) {
  return el("span", { class: `tag tag-decision tag-${event.decision}` }, svg("0 0 16 16", DECISION_ICON[event.decision]), event.label || DECISION_LABEL[event.decision]);
}

// The review cell: the current decision (if any) and a button to record or change it.
function decisionCell(type, id, describe) {
  const event = decisionsOf(dealState?.review).latest[`${type}:${id}`];
  const button = el("button", {
    type: "button", class: `btn btn-small ${event ? "btn-ghost" : "btn-secondary"} decide-btn`, "aria-haspopup": "dialog",
    "aria-label": `${event ? "Change review" : "Review"}: ${describe}`,
    onclick: (e) => openDecision(type, id, describe, e.currentTarget),
  }, event ? "Change" : "Review");
  return el("span", { class: "decision-cell", "data-decision": `${type}:${id}` },
    event ? [decisionTag(event), el("span", { class: "decision-by" }, `${event.reviewer_name} · ${formatDate(event.at.slice(0, 10))}`),
      event.note ? el("span", { class: "decision-note" }, `“${event.note}”`) : null] : el("span", { class: "cell-muted" }, "Not reviewed"),
    button);
}

let decisionTarget = null;

function openDecision(type, id, describe, opener) {
  const dialog = byId("decision-dialog");
  const current = decisionsOf(dealState.review).latest[`${type}:${id}`];
  decisionTarget = { type, id, opener, openedAt: performance.now() };
  byId("dd-item").textContent = describe;
  byId("dd-error").textContent = "";
  for (const input of dialog.querySelectorAll('input[name="decision"]')) input.checked = current ? input.value === current.decision : false;
  byId("dd-note").value = current?.note || "";
  updateNoteCount();
  const name = reviewerName();
  byId("dd-name-row").hidden = Boolean(name);
  byId("dd-as").hidden = !name;
  byId("dd-as-name").textContent = name;
  byId("dd-name").value = name;
  dialog.showModal();
  (current ? dialog.querySelector(`input[value="${current.decision}"]`) : dialog.querySelector('input[name="decision"]')).focus();
}

function updateNoteCount() {
  const left = MAX_NOTE - byId("dd-note").value.length;
  byId("dd-count").textContent = `${left} characters left`;
}

async function saveDecision(event) {
  event.preventDefault();
  // The Enter key that opened the dialog can reach the first option and submit the form at once. Ignore that.
  if (performance.now() - (decisionTarget?.openedAt || 0) < 400) return;
  const form = event.currentTarget;
  const choice = form.querySelector('input[name="decision"]:checked');
  const name = byId("dd-name").value.trim() || reviewerName();
  if (!choice) { byId("dd-error").textContent = "Choose Confirm, Needs follow-up or Disputed."; form.querySelector('input[name="decision"]').focus(); return; }
  if (!name) { byId("dd-name-row").hidden = false; byId("dd-error").textContent = "Enter your name so the record shows who decided."; byId("dd-name").focus(); return; }
  const save = form.querySelector('[type="submit"]');
  save.disabled = true;
  const wasComplete = decisionsOf(dealState.review).progress?.complete;
  try {
    const data = await api(`/api/deals/${encodeURIComponent(dealState.id)}/decisions`, {
      method: "POST",
      body: { target_type: decisionTarget.type, target_id: decisionTarget.id, decision: choice.value, note: byId("dd-note").value.trim() },
      reviewer: name,
    });
    rememberReviewer(name);
    const { event: saved, ...view } = data;
    dealState.review.decisions = view;
    byId("decision-dialog").close();
    refreshDecisions({ justCompleted: !wasComplete && view.progress.complete, changed: `${saved.target_type}:${saved.target_id}` });
    toast(`${saved.label}. Saved with your name and the time.`);
  } catch (err) {
    byId("dd-error").textContent = err.message;
  } finally {
    save.disabled = false;
  }
}

function setupDecisionDialog() {
  const dialog = byId("decision-dialog");
  byId("decision-form").addEventListener("submit", saveDecision);
  byId("dd-cancel").addEventListener("click", () => dialog.close());
  byId("dd-note").addEventListener("input", updateNoteCount);
  byId("dd-change-name").addEventListener("click", () => { byId("dd-name-row").hidden = false; byId("dd-as").hidden = true; byId("dd-name").focus(); });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => {
    const opener = decisionTarget?.opener;
    // The opener may have been redrawn; focus its replacement.
    const again = decisionTarget && document.querySelector(`[data-decision="${decisionTarget.type}:${CSS.escape(decisionTarget.id)}"] .decide-btn`);
    (again || opener)?.focus();
  });
}

// A card that folds to its heading and a one-line summary. Each deal starts open or folded by `open`; after that the
// visitor's own choice holds until they open another deal. Nothing is removed: the content is one press away.
function setCollapsible(section, { open, summary }) {
  if (!section || !dealState) return;
  const head = section.querySelector(":scope > .card-head");
  const body = section.querySelector(":scope > .card-body");
  if (!head || !body) return;
  if (section.dataset.forDeal !== dealState.id) {
    section.dataset.forDeal = dealState.id;
    section.dataset.open = String(Boolean(open));
  }
  body.id ||= `${section.id}-body`;
  let line = head.querySelector(".fold-summary");
  if (!line) { line = el("p", { class: "fold-summary" }); head.append(line); }
  let button = head.querySelector(".fold-toggle");
  if (!button) {
    button = el("button", { type: "button", class: "btn btn-ghost btn-small fold-toggle", "aria-controls": body.id,
      onclick: () => { section.dataset.open = String(section.dataset.open !== "true"); section.foldApply?.(); } });
    head.append(button);
  }
  const apply = () => {
    const isOpen = section.dataset.open === "true";
    body.hidden = !isOpen;
    section.classList.toggle("folded", !isOpen);
    button.setAttribute("aria-expanded", String(isOpen));
    button.replaceChildren(isOpen ? "Hide" : "Show", el("span", { class: "visually-hidden" }, ` ${head.querySelector("h2")?.textContent || "details"}`));
    line.textContent = isOpen ? "" : summary;
    line.hidden = isOpen || !summary;
  };
  section.foldApply = apply; // The button always runs the latest render's summary.
  apply();
}

// Progress meter and review log.
function renderReviewPanel() {
  const panel = byId("review-panel");
  if (!panel || !dealState) return;
  const d = decisionsOf(dealState.review);
  const p = d.progress || { claims_reviewed: 0, claims_total: dealState.review.claims.length, flagged_reviewed: 0, flagged_total: dealState.review.questions.length, complete: false };
  const bar = (done, total, label) => el("div", { class: "meter" },
    el("p", { class: "meter-label" }, el("span", { class: "meter-num" }, `${done} of ${total}`), ` ${label}`),
    el("div", { class: "meter-track", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(total), "aria-valuenow": String(done), "aria-label": label },
      el("span", { class: "meter-fill", style: `--f:${total ? done / total : 0}` })));
  const claimsById = dealState.claimsById;
  const questions = new Map(dealState.review.questions.map((q) => [q.key, q]));
  const what = (e) => {
    if (e.target_type === "claim" && claimsById.get(e.target_id)) {
      const c = claimsById.get(e.target_id);
      return `${dealState.review.topics[c.topic] || c.topic} claim, ${c.document_type} p. ${c.page}`;
    }
    const q = questions.get(e.target_id);
    return q ? `open question: ${q.text.split(":")[0]}` : e.target_id;
  };
  const shown = panel.dataset.all === "true" ? d.log : d.log.slice(0, 5);
  const name = reviewerName();
  panel.replaceChildren(...[
    el("div", { class: "card-head" },
      el("h2", { id: "review-title" }, "Your review"),
      el("p", { class: "hint" }, name ? ["Reviewing as ", el("strong", {}, name)] : "People decide. Each decision is saved with a name and time.")),
    el("div", { class: "card-body review-body" },
      el("div", { class: "meters" },
        bar(p.claims_reviewed, p.claims_total, "claims reviewed"),
        bar(p.flagged_reviewed, p.flagged_total, "open questions decided"),
        el("p", { class: `review-state ${p.complete ? `done tone-${stampInfo(dealState.review).tone}` : ""}` }, p.complete
          ? [svg("0 0 16 16", ICONS.ok), [stampInfo(dealState.review).text, stampInfo(dealState.review).caption].filter(Boolean).join(" · ")]
          : `The receipt stays “Flagged for human review” until every open question has a decision.`)),
      el("div", { class: "review-log" },
        el("h3", {}, "Review log"),
        d.log.length
          ? el("ol", { class: "timeline" }, shown.map((e) => el("li", {},
            el("span", { class: "avatar", "aria-hidden": "true" }, (e.reviewer_name.trim()[0] || "?").toUpperCase()),
            el("div", {},
              el("p", {}, el("strong", {}, e.reviewer_name), " marked ", what(e), " as ", decisionTag(e)),
              e.note ? el("p", { class: "decision-note" }, `“${e.note}”`) : null,
              el("p", { class: "decision-by" }, el("time", { datetime: e.at }, formatWhen(e.at)))))))
          : el("p", { class: "cell-muted" }, "No decisions yet. Use Review on a claim or an open question."),
        d.log.length > 5 ? el("button", { type: "button", class: "btn-link", onclick: () => { panel.dataset.all = panel.dataset.all === "true" ? "false" : "true"; renderReviewPanel(); } },
          panel.dataset.all === "true" ? "Show fewer" : `Show all ${d.log.length}`) : null)),
    d.sandboxed ? el("div", { class: "card-foot sandbox-note" },
      el("p", {}, svg("0 0 16 16", [["rect", { x: 3, y: 7, width: 10, height: 7, rx: 1.5 }], ["path", { d: "M5.5 7V5a2.5 2.5 0 0 1 5 0v2" }]]),
        "This is a sample deal. Your review is kept for this browser only, and no one else sees it."),
      d.log.length ? resetControl() : null) : null
  ].filter(Boolean));
  // Folded until the visitor starts reviewing: the summary line still shows where the review stands.
  setCollapsible(panel, { open: d.log.length > 0 || !isReadOnly(),
    summary: `${p.claims_reviewed} of ${p.claims_total} claims reviewed · ${p.flagged_reviewed} of ${p.flagged_total} open questions decided` });
}

// "Reset my review" on sample deals, with an inline confirm.
function resetControl() {
  const wrap = el("span", { class: "reset-control" });
  const ask = () => wrap.replaceChildren(
    el("span", { class: "hint" }, "Clear your decisions on this sample?"),
    el("button", { type: "button", class: "btn btn-secondary btn-small", id: "reset-yes", onclick: doReset }, "Reset"),
    el("button", { type: "button", class: "btn btn-ghost btn-small", onclick: () => { idle(); byId("reset-review")?.focus(); } }, "Keep"));
  const idle = () => wrap.replaceChildren(el("button", { type: "button", class: "btn btn-ghost btn-small", id: "reset-review", onclick: () => { ask(); byId("reset-yes").focus(); } }, "Reset my review"));
  async function doReset() {
    try {
      dealState.review.decisions = await api(`/api/deals/${encodeURIComponent(dealState.id)}/decisions`, { method: "DELETE" });
      refreshDecisions();
      toast("Your review of this sample was reset.");
      byId("review-title")?.focus?.();
    } catch (err) {
      toast(`The review was not reset. ${err.message}`, { kind: "warn" });
    }
  }
  idle();
  return wrap;
}

// Redraw everything that shows decisions, after a save.
function refreshDecisions({ justCompleted = false, changed = null } = {}) {
  renderReviewPanel();
  renderClaims();
  renderQuestions();
  renderReceipt(byId("receipt-body"), dealState.review);
  if (changed) {
    const cell = document.querySelector(`[data-decision="${CSS.escape(changed)}"]`);
    cell?.classList.add("just-decided");
  }
  if (justCompleted) {
    toast("Every open question has a decision.");
    const stamp = byId("receipt-body").querySelector(".receipt-stamp");
    if (stamp) landStamp(stamp, 200);
  } else {
    byId("receipt-body").querySelector(".receipt-stamp")?.classList.add("landed");
  }
}

// ---------- Guided tour: six steps with a spotlight ----------
// For the live demo and for anyone exploring alone. Keyboard: Enter or the arrow keys move, Escape ends.
// The spotlight and caption are top-layer popovers, so they sit above the source panel when it is open.
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(find, timeout = 3500) {
  const start = performance.now();
  while (performance.now() - start < timeout) {
    const node = find();
    if (node) return node;
    await sleep(80);
  }
  return null;
}

const TOUR = [
  {
    title: "Upload",
    text: "Drag in the deal's PDFs. AI reads each page, and code checks every quote it finds.",
    run: async () => { byId("source-dialog").open && byId("source-dialog").close(); return byId(isReadOnly() ? "readonly-note" : "dropzone"); },
  },
  {
    title: "Claims",
    text: "Every promise appears with its exact quote, document, date and page, and a stage of its own.",
    run: async () => { activateTab("claims"); return byId("claim-rows")?.querySelector("tr"); },
  },
  {
    title: "View source",
    text: "View source opens the real PDF page with the quote highlighted, so anyone can check it.",
    run: async () => {
      activateTab("claims");
      const button = byId("claim-rows")?.querySelector(".source-cell .btn");
      const claim = button && dealState.claimsById.get(button.closest("tr")?.querySelector("[data-decision]")?.dataset.decision.split(":")[1]);
      if (!button || !claim) return null;
      if (!byId("source-dialog").open) openSource(claim, button, { modal: false });
      byId("tour-next").focus(); // Opening the panel moves focus; keep it on the caption.
      const mark = await waitFor(() => document.querySelector("#source-body mark.hl, #source-body .page-sheet mark"));
      return mark || document.querySelector("#source-body .pdf-stage") || byId("source-body");
    },
  },
  {
    title: "What changed",
    text: "Wording that drifts between records is marked: words removed are struck through, words added are underlined.",
    run: async () => {
      if (byId("source-dialog").open) byId("source-dialog").close();
      activateTab("changes");
      return byId("change-list")?.querySelector(".change-term");
    },
  },
  {
    title: "People decide",
    text: "Each flag needs a person: confirm it, ask for follow-up or mark it disputed. Every decision keeps a name and time.",
    run: async () => { activateTab("questions"); return byId("question-list")?.querySelector(".task"); },
  },
  {
    title: "Receipt and share",
    text: "The receipt gathers it all. When every flag has a decision, it is stamped as reviewed. Print it or share a read-only link.",
    run: async () => { activateTab("receipt"); return byId("receipt-body")?.closest(".printer") || byId("receipt-body"); },
  },
];

const tour = { step: -1, target: null, opener: null, layer: null, spot: null, card: null, busy: false };
const usePopover = typeof HTMLElement !== "undefined" && "popover" in HTMLElement.prototype;

function tourLayer() {
  if (tour.layer) return;
  tour.spot = el("div", { class: "tour-spot", "aria-hidden": "true" });
  tour.layer = el("div", { class: "tour-layer", popover: usePopover ? "manual" : null, onclick: (event) => { if (event.target === tour.layer) endTour(); } }, tour.spot);
  tour.card = el("div", { class: "tour-card", role: "dialog", "aria-modal": "false", "aria-labelledby": "tour-title", "aria-describedby": "tour-text", popover: usePopover ? "manual" : null, tabindex: "-1" },
    el("p", { class: "tour-count", id: "tour-count" }),
    el("h2", { id: "tour-title" }),
    el("p", { id: "tour-text", "aria-live": "polite" }),
    el("div", { class: "tour-dots", "aria-hidden": "true" }, TOUR.map(() => el("span"))),
    el("div", { class: "tour-actions" },
      el("button", { type: "button", class: "btn btn-ghost btn-small", id: "tour-skip", onclick: () => endTour() }, "Skip tour"),
      el("button", { type: "button", class: "btn btn-secondary btn-small", id: "tour-back", onclick: () => goTour(tour.step - 1) }, "Back"),
      el("button", { type: "button", class: "btn btn-primary btn-small", id: "tour-next", onclick: () => goTour(tour.step + 1) }, "Next")));
  document.addEventListener("keydown", (event) => {
    if (tour.step < 0) return;
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); endTour(); }
    else if (event.key === "ArrowRight") { event.preventDefault(); goTour(tour.step + 1); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); goTour(tour.step - 1); }
    else if (event.key === "Tab") {
      // Keep focus in the caption while the tour runs, wherever it was.
      const items = [...tour.card.querySelectorAll("button:not([disabled])")];
      const at = items.indexOf(document.activeElement);
      event.preventDefault();
      items[at < 0 ? items.length - 1 : (at + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus();
    }
  }, true);
  document.body.append(tour.layer, tour.card);
}

// Show the layer and caption on top of anything already in the top layer (such as the source panel).
function raiseTour() {
  if (!usePopover) { tour.layer.hidden = false; tour.card.hidden = false; return; }
  for (const node of [tour.layer, tour.card]) {
    if (node.matches(":popover-open")) node.hidePopover();
    node.showPopover();
  }
}

function placeTour() {
  if (!tour.target || tour.step < 0) return;
  const pad = 8;
  const r = tour.target.getBoundingClientRect();
  const spot = { top: Math.max(4, r.top - pad), left: Math.max(4, r.left - pad), width: Math.min(innerWidth - 8, r.width + pad * 2), height: Math.min(innerHeight - 8, r.height + pad * 2) };
  Object.assign(tour.spot.style, { top: `${spot.top}px`, left: `${spot.left}px`, width: `${spot.width}px`, height: `${spot.height}px` });
  const card = tour.card.getBoundingClientRect();
  if (innerWidth < 640) { Object.assign(tour.card.style, { left: "", top: "", right: "", bottom: "" }); tour.card.classList.add("sheet"); return; }
  tour.card.classList.remove("sheet");
  const below = spot.top + spot.height + 12;
  const top = below + card.height < innerHeight - 8 ? below : Math.max(8, spot.top - card.height - 12);
  const left = Math.min(Math.max(8, spot.left), innerWidth - card.width - 8);
  Object.assign(tour.card.style, { top: `${top}px`, left: `${left}px`, right: "auto", bottom: "auto" });
}

async function goTour(step) {
  if (tour.busy || step < 0) return;
  if (step >= TOUR.length) { endTour(); return; }
  tour.busy = true;
  tour.step = step;
  const item = TOUR[step];
  byId("tour-count").textContent = `Step ${step + 1} of ${TOUR.length}`;
  byId("tour-title").textContent = item.title;
  byId("tour-text").textContent = item.text;
  tour.card.querySelectorAll(".tour-dots span").forEach((dot, i) => dot.classList.toggle("on", i <= step));
  byId("tour-back").disabled = step === 0;
  byId("tour-next").textContent = step === TOUR.length - 1 ? "Finish" : "Next";
  let target = null;
  try { target = await item.run(); } catch (err) { target = null; }
  tour.target = target || byId("deal-title");
  tour.target.scrollIntoView({ block: "center", behavior: reducedMotion.matches ? "auto" : "smooth" });
  await sleep(reducedMotion.matches ? 0 : 320);
  raiseTour();
  placeTour();
  byId("tour-next").focus();
  tour.busy = false;
}

async function startTour(opener = null) {
  if (current.view !== "deal" || !dealState || byId("details").hidden) return;
  tourLayer();
  tour.opener = opener || document.activeElement;
  document.documentElement.classList.add("touring");
  window.addEventListener("resize", placeTour);
  window.addEventListener("scroll", placeTour, { passive: true });
  await goTour(0);
}

function endTour() {
  if (tour.step < 0) return;
  tour.step = -1;
  tour.target = null;
  window.removeEventListener("resize", placeTour);
  window.removeEventListener("scroll", placeTour);
  document.documentElement.classList.remove("touring");
  for (const node of [tour.layer, tour.card]) {
    if (usePopover) { if (node.matches(":popover-open")) node.hidePopover(); } else node.hidden = true;
  }
  if (byId("source-dialog").open) byId("source-dialog").close();
  activateTab("claims");
  const back = tour.opener?.isConnected && tour.opener.matches?.("button, a") ? tour.opener : byId("tour-start");
  back?.focus();
}

// The tour starts from the button on a sample deal, from #/deals/{id}/tour, or from the command menu.
function tourButton() {
  return el("button", { type: "button", class: "btn btn-ghost tour-start", id: "tour-start", onclick: (event) => startTour(event.currentTarget) },
    svg("0 0 24 24", [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M10 8.5v7l5.5-3.5z" }]]), "Take the 60-second tour");
}

// ---------- Start ----------
// Web fonts load after the first paint. Metric-matched fallbacks in style.css keep text from moving when they arrive.
const FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap";
function loadFonts() { document.head.append(el("link", { rel: "stylesheet", href: FONTS })); }
if (document.readyState === "complete") setTimeout(loadFonts, 0); else window.addEventListener("load", () => setTimeout(loadFonts, 0), { once: true });
// Tabs on static pages ([data-tabs]): one panel at a time, arrow keys move between tabs.
function setupPageTabs() {
  for (const list of document.querySelectorAll("[data-tabs]")) {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    const select = (tab, focus) => {
      for (const other of tabs) {
        const on = other === tab;
        other.setAttribute("aria-selected", String(on));
        other.tabIndex = on ? 0 : -1;
        byId(other.getAttribute("aria-controls")).hidden = !on;
      }
      if (focus) tab.focus();
      tab.scrollIntoView({ block: "nearest", inline: "nearest" });
    };
    list.addEventListener("click", (event) => {
      const tab = event.target.closest('[role="tab"]');
      if (tab) select(tab, false);
    });
    list.addEventListener("keydown", (event) => {
      const at = tabs.indexOf(document.activeElement);
      if (at < 0) return;
      const step = { ArrowRight: 1, ArrowLeft: -1, Home: -at, End: tabs.length - 1 - at }[event.key];
      if (step === undefined) return;
      event.preventDefault();
      select(tabs[(at + step + tabs.length) % tabs.length], true);
    });
    // Each tab states its own aria-selected from the start (the page ships only the first one as selected).
    for (const tab of tabs) tab.setAttribute("aria-selected", String(tab.getAttribute("aria-selected") === "true"));
  }
}

setupToggles();
setupNav();
setupGlossaryPopovers();
setupNewDeal();
setupSourceDialog();
setupPageDrop();
setupCommands();
setupExportDialog();
setupViewer();
setupDecisionDialog();
setupReveal();
setupSpotlight();
setupOffscreenPause();
countyChat = setupCountyChat();
setupHeroMotion();
setupPageTabs();
ready = detectMode();
window.addEventListener("hashchange", () => safeRoute());
setupConnectivity();
safeRoute({ initial: true });
ready.then(async () => {
  if (current.view === "shared") return; // A shared link needs nothing beyond its receipt.
  try {
    const deals = await api("/api/deals");
    rememberSample(deals);
    const sample = deals.find((deal) => deal.id === sampleId);
    if (sample) fillHeroReceipt(await api(`/api/deals/${encodeURIComponent(sample.id)}/review`));
  } catch (err) { /* The home page keeps its shipped preview. */ }
});
