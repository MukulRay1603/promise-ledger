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
const sourceShort = (claim) => `${claim.document_type} · ${formatDate(claim.date)} · p. ${claim.page}`;
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
  print: [["path", { d: "M7 9V3h10v6M7 18H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" }], ["rect", { x: 7, y: 14, width: 10, height: 7 }]],
  calendar: [["rect", { x: 3, y: 5, width: 18, height: 16, rx: 2 }], ["path", { d: "M3 10h18M8 3v4M16 3v4" }]],
  docq: [["path", { d: "M6 3h8l4 4v14H6z" }], ["path", { d: "M10.3 11a1.8 1.8 0 1 1 2.4 1.7c-.5.2-.7.6-.7 1.1M12 17v.1" }]],
  bell: [["path", { d: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" }], ["path", { d: "M10 20a2 2 0 0 0 4 0" }]],
  check: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M8 12.5l2.5 2.5 5-5.5" }]],
  warn: [["path", { d: "M12 3 2 20h20z" }], ["path", { d: "M12 10v4M12 17v.1" }]],
  info: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M12 11v5M12 8v.1" }]],
  prev: [["path", { d: "M15 6l-6 6 6 6" }]],
  next: [["path", { d: "M9 6l6 6-6 6" }]],
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
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : null });
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
const STATIC_PAGES = { roadmap: "Roadmap", about: "About" };
let sampleId = "harbor-walk";

function parseRoute() {
  const pathMatch = location.pathname.match(/^\/r\/([\w.-]+)/);
  if (pathMatch) return { view: "shared", token: pathMatch[1] };
  const hash = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (!hash || hash === "/") return { view: "home" };
  if (TAB_IDS.includes(hash)) return { view: "deal", id: sampleId, tab: hash }; // Links from the earlier one-page version.
  if (!hash.startsWith("/")) return { view: "home" };
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "deals" && parts.length === 1) return { view: "deals" };
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
  for (const link of document.querySelectorAll("[data-nav]")) {
    const on = link.dataset.nav === view || (view === "deal" && link.dataset.nav === "deals");
    if (on) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
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
  showView(next.view);
  if (!initial) {
    window.scrollTo(0, 0);
    byId("main").focus({ preventScroll: true });
  }
  if (next.view === "home") { document.title = "Promise Ledger"; setupVideos(); if (!hero.running && hero.loops < HERO_LOOPS) heroPlay(); return; }
  if (STATIC_PAGES[next.view]) { document.title = `${STATIC_PAGES[next.view]} · Promise Ledger`; return; }
  if (next.view === "deals") return renderDeals();
  if (next.view === "deal") return renderDeal(next.id, next.tab, next.source, next.tour);
  if (next.view === "shared") return renderShared(next.token);
  document.title = "Page not found · Promise Ledger";
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
          <input id="ask-text" name="question" type="text" required minlength="3" maxlength="300" autocomplete="off" aria-describedby="ask-hint">
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
    view.replaceChildren(el("div", { class: "empty" },
      el("h1", { id: "deal-title" }, err.status === 404 ? "Deal not found" : "The deal did not load"),
      el("p", {}, err.status === 404 ? "There is no deal at this address." : `${err.message} Reload the page to try again.`),
      el("a", { class: "btn btn-primary", href: "#/deals" }, "Go to deals")));
    return;
  }
  if (current.view !== "deal" || current.id !== id) return;
  setDeal(id, deal, review);
  document.title = `${deal.name} · Promise Ledger`;
  byId("crumb-name").textContent = deal.name;
  byId("deal-title").textContent = deal.name;
  byId("deal-sub").textContent = deal.city;
  renderActions(id, deal);
  renderDocs();
  renderReview({ tab: sourceClaim ? null : tab });
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

function countUp(node, value) {
  node.textContent = String(value);
  if (typeof value !== "number" || reducedMotion.matches || value === 0) return;
  const start = performance.now();
  const duration = 650;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    node.textContent = String(Math.round(value * (1 - (1 - t) ** 3)));
    if (t < 1) requestAnimationFrame(step);
  };
  node.textContent = "0";
  requestAnimationFrame(step);
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
        el("span", { class: "source-line" }, docType(claim.document_type), ` · ${formatDate(claim.date)}`), quoteBadge(claim), claim.from_scan ? tag("machine", "From scan") : null, viewSourceButton(claim))),
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
    body));
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
  const target = Number(node.dataset.count);
  const decimals = Number(node.dataset.decimals || 0);
  const show = (value) => { node.textContent = value.toFixed(decimals); };
  if (reducedMotion.matches || !target) { show(target); return; }
  const start = performance.now();
  const duration = 900;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    show(target * (1 - (1 - t) ** 3));
    if (t < 1) requestAnimationFrame(step);
  };
  show(0);
  requestAnimationFrame(step);
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
setupGlossaryPopovers();
setupNewDeal();
setupSourceDialog();
setupPageDrop();
setupCommands();
setupExportDialog();
setupViewer();
setupDecisionDialog();
setupReveal();
setupHeroMotion();
setupPageTabs();
ready = detectMode();
window.addEventListener("hashchange", () => route());
route({ initial: true });
ready.then(async () => {
  if (current.view === "shared") return; // A shared link needs nothing beyond its receipt.
  try {
    const deals = await api("/api/deals");
    rememberSample(deals);
    const sample = deals.find((deal) => deal.id === sampleId);
    if (sample) fillHeroReceipt(await api(`/api/deals/${encodeURIComponent(sample.id)}/review`));
  } catch (err) { /* The home page keeps its shipped preview. */ }
});
