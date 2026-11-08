// Promise Ledger v1 interface. Hash routes: #/ home, #/deals, #/deals/{id}[/{tab}], #/r/{token} (also /r/{token}).
// Every figure comes from the API, which counts it from the records. Record text goes in through text nodes only.
const byId = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const STAGES = ["proposed", "supported", "signed", "delivered"];
const TAB_IDS = ["claims", "changes", "questions", "receipt", "extract", "glossary"];
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
  ? el("span", { class: "badge badge-ok" }, svg("0 0 16 16", ICONS.ok), "Quote verified · ", el("span", { class: "mono" }, `p. ${claim.page}`))
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
      if (res.ok && (res.headers.get("content-type") || "").includes("json")) return "live";
    } catch (err) { /* Not reachable. Use the mock. */ }
  }
  const [{ createMock }, seed] = await Promise.all([import("./mock.js"), loadSeed()]);
  mock = createMock(seed);
  return "mock";
}

async function api(path, { method = "GET", body = null, onProgress = null } = {}) {
  await ready;
  if (mock) {
    try { return await mock.handle(method, path, body, { onProgress }); } catch (err) { throw new ApiError(err.status || 500, err.message); }
  }
  if (body instanceof FormData) return uploadWithProgress(path, body, onProgress);
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
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
  ami: { title: "AMI (area median income)", text: "The middle household income for an area, published each year by the U.S. Department of Housing and Urban Development (HUD). Affordable homes are often limited to households earning at or below a share of AMI, such as 60 or 80 percent." },
  abatement: { title: "Tax abatement / PILOT", text: "A tax abatement lowers or delays property taxes for a set time. A PILOT (payment in lieu of taxes) replaces regular property taxes with an agreed payment. Cities often ask for affordable homes in return." },
  term: { title: "Affordability term", text: "How long the homes must stay affordable, usually counted in years from a start date such as the first move-in." },
  remedies: { title: "Remedies", text: "What happens if a commitment is not met, such as repayment, penalties or ending the tax break. Remedies are usually written into the signed agreement." },
  stages: { title: "Stages", text: "Proposed: described as a plan or idea. Supported: recommended by staff or backed by a vote. Signed: written in a signed record. Delivered: a record shows the homes were built, leased or checked. Each claim sits only at the stage its own record shows." },
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

function withTerm(text, phrase, key) {
  const at = text.indexOf(phrase);
  if (at === -1) return [text];
  return [text.slice(0, at), termButton(key, phrase), text.slice(at + phrase.length)];
}

// ---------- Router ----------
let current = { view: null };
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
  if (next.view === "home") { document.title = "Promise Ledger"; return; }
  if (next.view === "deals") return renderDeals();
  if (next.view === "deal") return renderDeal(next.id, next.tab);
  if (next.view === "shared") return renderShared(next.token);
  document.title = "Page not found · Promise Ledger";
}

// ---------- Home ----------
async function setupVideos() {
  let list = [];
  try {
    const res = await fetch("/static/media/videos.json");
    if (res.ok) list = (await res.json()).videos || [];
  } catch (err) { return; }
  for (const video of list) {
    if (!video.ready) continue;
    const card = document.querySelector(`[data-video="${video.slug}"]`);
    if (!card) continue;
    const frame = card.querySelector(".video-frame");
    const n = video.slug.slice(0, 2);
    const base = `/static/media/${video.slug}`;
    const play = el("button", { type: "button", class: "video-play", "aria-describedby": `vt-${n}`, "aria-label": `Play video ${n}, with captions` },
      el("span", { class: "play-dot" }, svg("0 0 24 24", [["path", { d: "M8 5v14l11-7z" }]])));
    play.addEventListener("click", () => {
      const player = el("video", { controls: true, playsinline: true, preload: "auto", poster: `${base}.jpg`, "aria-labelledby": `vt-${n}` },
        el("source", { src: `${base}.mp4`, type: "video/mp4" }),
        el("track", { kind: "captions", srclang: "en", label: "English", src: `${base}.vtt`, default: true }));
      frame.replaceChildren(player);
      player.focus();
      player.play().catch(() => { /* The browser may wait for another press. Controls are there. */ });
    });
    frame.replaceChildren(el("img", { src: `${base}.jpg`, alt: "", loading: "lazy", decoding: "async", width: 1280, height: 720 }), play);
  }
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
  byId("hero-receipt-rows").replaceChildren(...rows);
  byId("hero-receipt-title").textContent = `${review.project} · ${review.city}`;
  byId("hero-receipt-checks").textContent = `${review.checks.passed} of ${review.checks.total}`;
}

// ---------- Deals ----------
const REMINDER_ICON = { term_end: "calendar", missing_record: "docq" };

function reminderDue(item) {
  if (!item.due) return "No due date";
  const days = daysFromToday(item.due);
  if (days > 1) return `Due ${formatDate(item.due)} · in ${days} days`;
  if (days === 1) return `Due tomorrow, ${formatDate(item.due)}`;
  if (days === 0) return "Due today";
  return `Was due ${formatDate(item.due)}`;
}

function flagCell(deal) {
  const items = [];
  if (deal.terms_differ) items.push(tag("differs", `${deal.terms_differ} differ`));
  if (deal.terms_not_located) items.push(tag("not_located", `${deal.terms_not_located} not located`));
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
      el("div", {}, el("h1", { id: "deals-title" }, "Deals"), el("p", { class: "page-sub" }, "Every deal under review, how far its records go, and what is due next.")),
      el("div", { class: "page-actions" }, el("button", { type: "button", class: "btn btn-primary", "data-new-deal": true }, icon("plus"), "New deal"))),
    el("div", { class: "deals-layout" },
      el("section", { class: "card", "aria-labelledby": "deals-table-cap" },
        el("table", { class: "deals-table stack", "aria-describedby": "deals-mode" },
          el("caption", { class: "visually-hidden", id: "deals-table-cap" }, "All deals"),
          el("thead", {}, el("tr", {}, ["Deal", "Documents", "Furthest stage", "Flags", "Next reminder"].map((text) => el("th", { scope: "col" }, text)))),
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

  tbody.replaceChildren(...(deals.length ? deals.map((deal) => {
    const docs = typeof deal.documents === "number" ? deal.documents : (deal.documents || []).length;
    return el("tr", {},
      el("th", { scope: "row", "data-label": "Deal" },
        el("a", { class: "deal-name", href: `#/deals/${encodeURIComponent(deal.id)}` }, deal.name),
        el("span", { class: "deal-city" }, deal.city)),
      el("td", { "data-label": "Documents" }, el("span", { class: "num" }, String(docs))),
      el("td", { "data-label": "Furthest stage" }, deal.furthest_status ? tag(deal.furthest_status) : tag("none")),
      el("td", { "data-label": "Flags" }, flagCell({ ...deal, documents: docs })),
      el("td", { "data-label": "Next reminder", class: "reminder-cell" }, deal.next_reminder
        ? [el("span", {}, deal.next_reminder.text), el("span", { class: "deal-city" }, reminderDue(deal.next_reminder))]
        : el("span", { class: "cell-muted" }, "None")));
  }) : [el("tr", {}, el("td", { colspan: 5 }, "No deals yet. Use New deal to add one."))]));

  reminderList.removeAttribute("aria-busy");
  reminderCount.textContent = plural(reminders.length, "item");
  reminderList.replaceChildren(...(reminders.length ? reminders.map((item) => el("li", { class: "reminder" },
    el("span", { class: `reminder-ico${item.kind === "term_end" ? "" : " soft"}` }, icon(REMINDER_ICON[item.kind] || "bell")),
    el("p", { class: "reminder-text" }, item.text),
    el("p", { class: "reminder-sub" }, reminderDue(item), " · ", el("a", { href: `#/deals/${encodeURIComponent(item.deal_id)}` }, item.deal_name || "Open deal"))))
    : [el("li", { class: "reminder" }, el("p", { class: "reminder-text" }, "Nothing due."))]));
}

function rememberSample(deals) {
  const sample = deals.find((deal) => /harbor walk/i.test(deal.name)) || deals.find((deal) => deal.documents);
  if (sample) { sampleId = sample.id; byId("open-sample").href = `#/deals/${encodeURIComponent(sample.id)}`; }
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
    <div class="stepper-wrap"><h2 class="stepper-heading" id="stepper-heading">Deal <span id="stage-term">stages</span></h2><ol class="stepper" id="stepper" aria-labelledby="stepper-heading"></ol></div>
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
      </div>
    </div>
  </section>
  <section class="tabs-wrap" id="details" aria-label="Review details">
    <div class="tablist" role="tablist" aria-label="Review details" id="tablist">
      <button type="button" role="tab" id="tab-claims" aria-controls="claims">Claims<span class="tab-count" id="count-claims"></span></button>
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
        <thead><tr><th scope="col">Term</th><th scope="col">Exact quote</th><th scope="col">Source</th><th scope="col">Stage</th><th scope="col">Wording</th></tr></thead>
        <tbody id="claim-rows"></tbody>
      </table>
    </div>
    <div class="panel" role="tabpanel" id="changes" aria-labelledby="tab-changes" tabindex="0" hidden>
      <div class="panel-head"><h2>What changed</h2><p class="panel-note">For each term, every record in date order. Words dropped since the previous record are struck through and labeled "Removed". New words are underlined and labeled "Added".</p></div>
      <div id="change-list" class="change-list"></div>
    </div>
    <div class="panel" role="tabpanel" id="questions" aria-labelledby="tab-questions" tabindex="0" hidden>
      <div class="panel-head"><h2>Open questions</h2><p class="panel-note" id="question-note"></p></div>
      <ul class="task-list" id="question-list"></ul>
    </div>
    <div class="panel" role="tabpanel" id="receipt" aria-labelledby="tab-receipt" tabindex="0" hidden>
      <div class="panel-head"><h2 id="receipt-heading">Promise Receipt</h2><button type="button" class="btn btn-secondary" id="print-receipt"></button></div>
      <article class="receipt" id="receipt-body" aria-labelledby="receipt-heading"></article>
    </div>
    <div class="panel" role="tabpanel" id="extract" aria-labelledby="tab-extract" tabindex="0" hidden>
      <div class="panel-head"><h2>Read new text</h2><p class="panel-note">The model finds candidate quotes. Code keeps only quotes that match your text word for word. A person sets every status.</p></div>
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

async function renderDeal(id, tab) {
  dealState = null;
  const view = byId("view-deal");
  view.innerHTML = DEAL_TEMPLATE; // Static markup only. Data is added below as text nodes.
  byId("glance-list").replaceChildren(...[1, 2, 3].map(() => el("li", {}, el("span", { class: "skeleton sk-line", style: "width:80%" }))));
  byId("kpis").replaceChildren(...[1, 2, 3, 4].map(() => el("li", { class: "kpi" }, el("span", { class: "skeleton sk-line", style: "width:60%" }), el("span", { class: "skeleton", style: "height:2.2rem;width:3rem" }))));
  byId("details").hidden = true;
  renderActions(id, { name: id }); // Drawn now so the header does not move when the data arrives.
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
  renderReview({ tab });
  pollIfBusy();
}

function setDeal(id, deal, review) {
  dealState = {
    id, deal, review,
    claimsById: new Map(review.claims.map((claim) => [claim.id, claim])),
    documentsById: new Map(review.documents.map((doc) => [doc.id, doc])),
    termsByKey: new Map(review.terms.map((term) => [term.key, term])),
  };
}

function renderActions(id, deal) {
  const base = `/api/deals/${encodeURIComponent(id)}`;
  const exportLink = (ext, label, name) => el("a", {
    class: "btn btn-secondary", href: `${base}/export.${ext}`, download: `${name}.${ext}`,
    onclick: (event) => { if (mock) { event.preventDefault(); mockDownload(`${base}/export.${ext}`, `${name}.${ext === "xlsx" ? "csv" : ext}`, ext); } },
  }, icon(ext === "xlsx" ? "sheet" : "file"), label);
  const name = deal.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  byId("deal-actions").replaceChildren(
    exportLink("xlsx", "Excel", `${name}-receipt`),
    exportLink("csv", "CSV", `${name}-receipt`),
    el("button", { type: "button", class: "btn btn-primary", id: "share-btn", onclick: (event) => shareLink(id, event.currentTarget) }, icon("link"), "Share read-only link"),
  );
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
  if (empty) return;

  byId("stage-term").replaceChildren(termButton("stages", "stages"));
  renderSummary();
  // Draw the open tab now and the rest when the browser is idle, so the first paint is not held up.
  const selected = keepTab ? document.querySelector('[role="tab"][aria-selected="true"]')?.id.replace("tab-", "") : null;
  const open = selected || tab || "claims";
  const panels = {
    claims: renderClaims, changes: renderChanges, questions: renderQuestions,
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
    "aria-label": `${label}: ${claim.document_type}, ${formatDate(claim.date)}, page ${claim.page}`,
    onclick: (event) => openSource(claim, event.currentTarget),
  }, label);
}

function countUp(node, value) {
  node.textContent = String(value);
  if (typeof value !== "number" || reducedMotion.matches || value === 0) return;
  const start = performance.now();
  const duration = 240;
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
  byId("glance-foot").replaceChildren(
    lead ? el("span", {}, `Home count from: ${sourceShort(lead)}`) : null,
    lead ? viewSourceButton(lead) : null,
    el("span", {}, `Quotes checked: ${review.checks.passed} of ${review.checks.total} found word for word on their cited pages.`),
  );

  const stageIndex = STAGES.indexOf(s.furthest_status) + 1;
  const kpis = [
    ["Homes described as affordable", s.homes_described ?? "None", s.homes_total ? `of ${s.homes_total} homes` : "homes", false],
    ["Furthest stage", s.furthest_label, stageIndex ? `stage ${stageIndex} of ${s.stages_total}` : "nothing located", false],
    ["Terms that differ", s.terms_differ, `of ${s.terms_total} terms`, s.terms_differ > 0],
    ["Terms not located", s.terms_not_located, `of ${s.terms_total} terms`, s.terms_not_located > 0],
  ];
  const animate = !counted.has(id);
  counted.add(id);
  byId("kpis").replaceChildren(...kpis.map(([label, value, unit, warn]) => {
    const valueNode = el("span", { class: "kpi-value" }, String(value));
    if (animate) countUp(valueNode, value);
    return el("li", { class: `kpi${warn ? " kpi-warn" : ""}` }, el("span", { class: "kpi-label" }, label), valueNode, el("span", { class: "kpi-unit" }, unit));
  }));

  byId("stepper").replaceChildren(...review.stages.map((stage, index) => {
    const located = stage.claim_ids.length > 0;
    const iconNode = located
      ? svg("0 0 28 28", [["circle", { cx: 14, cy: 14, r: 13, class: "ico-located" }], ["path", { d: "M8.5 14.5l3.5 3.5 7.5-8", class: "ico-located-check" }]])
      : svg("0 0 28 28", [["circle", { cx: 14, cy: 14, r: 12, class: "ico-missing" }]]);
    const nextLocated = review.stages[index + 1]?.claim_ids.length > 0;
    return el("li", { class: `step${located && nextLocated ? " done" : ""}`, "aria-current": stage.status === s.furthest_status ? "step" : null },
      el("span", { class: "step-dot" }, iconNode),
      el("span", { class: "step-text" },
        el("span", { class: "step-name" }, stage.label),
        el("span", { class: "step-detail" }, located ? `Located · ${plural(stage.claim_ids.length, "claim")}` : "Not located")));
  }));
}

// Tabs: ARIA tabs with arrow keys, Home and End. The hash names the open tab.
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
  if (updateHash && dealState) {
    const hash = `#/deals/${encodeURIComponent(dealState.id)}/${id}`;
    if (location.hash !== hash) { history.replaceState(null, "", hash); current.tab = id; }
  }
}

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
  if (key === "income_basis") return el("span", { class: "nowrap" }, label, " (", termButton("ami", "AMI"), ")");
  return label;
}

function renderClaims() {
  const { review, termsByKey } = dealState;
  const { passed, total, problems } = review.checks;
  byId("count-claims").textContent = String(review.claims.length);
  byId("check-line").textContent = problems.length
    ? `${passed} of ${total} quotes passed the check. ${problems.length} flagged for human review.`
    : `Code found all ${total} quotes word for word on their cited pages.`;

  const order = Object.keys(review.topics);
  const claims = [...review.claims].sort((a, b) => order.indexOf(a.topic) - order.indexOf(b.topic) || a.date.localeCompare(b.date));
  byId("claim-rows").replaceChildren(...claims.map((claim) => {
    const term = termsByKey.get(claim.topic);
    let wording = el("span", { class: "cell-muted" }, "Not compared");
    if (term) {
      wording = term.wording_differs
        ? tag("differs")
        : el("span", { class: "cell-muted" }, term.claim_ids.length > 1 ? "Same in every record" : "One record");
    }
    return el("tr", {},
      el("th", { scope: "row", "data-label": "Term" }, termLabel(claim.topic)),
      el("td", { "data-label": "Exact quote" }, el("span", { class: "quote" }, `“${claim.quote}”`)),
      el("td", { "data-label": "Source" }, el("span", { class: "source-cell" },
        el("span", { class: "source-line" }, `${claim.document_type} · ${formatDate(claim.date)}`), quoteBadge(claim), viewSourceButton(claim))),
      el("td", { "data-label": "Stage" }, tag(claim.status)),
      el("td", { "data-label": "Wording" }, wording));
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

function changeStep(claim, previous) {
  const ops = previous ? diffWords(previous.value, claim.value) : [];
  const removed = ops.filter(([kind]) => kind === "removed").map(([, word]) => word).join(" ");
  const added = ops.filter(([kind]) => kind === "added").map(([, word]) => word).join(" ");
  const value = previous
    ? ops.map(([kind, word], at) => [at ? " " : "", kind === "same" ? word : el(kind === "added" ? "ins" : "del", {}, word)])
    : [claim.value];
  let labels = "First record.";
  if (previous && !removed && !added) labels = "Same wording as the previous record.";
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

function renderQuestions() {
  const { questions } = dealState.review;
  byId("count-questions").textContent = String(questions.length);
  byId("question-note").textContent = `${plural(questions.length, "question")} from terms that are not located or differ across records. Ticks are not saved.`;
  byId("question-list").replaceChildren(...questions.map((question, index) => el("li", { class: "task" },
    el("input", { type: "checkbox", id: `q-${index}` }),
    el("label", { for: `q-${index}` }, question.text),
    tag(question.tag))));
}

// Receipt: black on white, the same on screen, in a shared link and in print.
function renderReceipt(target, review, { titleTag = "p" } = {}) {
  const claimsById = new Map(review.claims.map((claim) => [claim.id, claim]));
  const rows = review.terms.map((term) => {
    const signed = term.signed_claim_id ? claimsById.get(term.signed_claim_id) : null;
    const earlier = term.claim_ids.map((cid) => claimsById.get(cid)).filter((claim) => claim && claim.status !== "signed");
    return el("tr", {},
      el("th", { scope: "row" }, term.label),
      el("td", {}, signed
        ? [el("span", { class: "q" }, `“${signed.quote}”`), el("span", { class: "receipt-source" }, sourceShort(signed))]
        : el("span", { class: "not-located" }, term.located ? "Not located in a signed record" : "Not located")),
      el("td", {}, earlier.length
        ? el("ul", { class: "plain" }, ...earlier.map((claim) => el("li", {}, `${claim.value} (${claim.document_type}, p. ${claim.page})`)))
        : "None"));
  });
  const support = review.claims.filter((claim) => claim.topic === "public_support");
  const { passed, total } = review.checks;

  target.replaceChildren(
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
    el("h3", {}, "Open questions, flagged for human review"),
    review.questions.length ? el("ul", {}, ...review.questions.map((question) => el("li", {}, question.text))) : el("p", {}, "None."),
    el("p", { class: "receipt-foot" }, `Quote check: ${passed} of ${total} quotes found on their cited pages.`),
    el("div", { class: "sign-off" }, el("p", {}, "Reviewed by: ______________________"), el("p", {}, "Date: ______________")),
    el("p", { class: "receipt-foot" }, "This receipt is a review aid. It makes no legal findings."),
  );
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

function docItem({ title, sub, phase, progress = null, error = null }) {
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
    error ? el("p", { class: "doc-error" }, error) : null);
}

function renderDocs() {
  if (!dealState) return;
  const docs = dealState.deal.documents || [];
  const local = [...uploads.values()].filter((item) => item.dealId === dealState.id && !docs.some((doc) => doc.id === item.docId));
  const items = [
    ...docs.map((doc) => {
      const pages = doc.pages ? ` · ${plural(doc.pages, "page")}` : "";
      return docItem({ title: doc.title, sub: `${doc.type || "Record"} · ${formatDate(doc.date)}${pages}`, phase: phaseOf(doc.status), error: doc.error });
    }),
    ...local.map((item) => docItem({ title: item.name, sub: fileSize(item.size), phase: item.error ? "failed" : "uploading", progress: item.progress, error: item.error })),
  ];
  byId("doc-list").replaceChildren(...items);
  byId("doc-list").hidden = items.length === 0;
  byId("docs-count").textContent = items.length ? plural(items.length, "file") : "No files yet";
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
  for (const file of fileList) {
    if (file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) { toast(`${file.name} is not a PDF. Only PDF files can be read.`, { kind: "warn" }); continue; }
    if (file.size > MAX_UPLOAD) { toast(`${file.name} is ${fileSize(file.size)}. The limit is 20 MB.`, { kind: "warn" }); continue; }
    uploadOne(dealId, file);
  }
}

async function uploadOne(dealId, file) {
  const key = `${Date.now()}-${Math.random()}`;
  const item = { dealId, name: file.name, size: file.size, progress: 0, docId: null, error: null };
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
    if (dealState?.id === dealId) {
      dealState.deal.documents = [...(dealState.deal.documents || []).filter((existing) => existing.id !== doc.id), doc];
      renderDocs();
      pollIfBusy();
    }
    uploads.delete(key);
  } catch (err) {
    item.error = err.message;
    if (dealState?.id === dealId) renderDocs();
    toast(`${file.name} did not upload. ${err.message}`, { kind: "warn" });
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
        if (was && was !== now && now === "done") { changed = true; toast(`${doc.title} was read and its quotes were checked.`); }
        if (was && was !== now && now === "failed") toast(`${doc.title} could not be read. ${doc.error || ""}`.trim(), { kind: "warn" });
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

function openSource(claim, opener) {
  const doc = dealState.documentsById.get(claim.document) || { id: claim.document, title: claim.document_type, type: claim.document_type, date: claim.date, pages: [] };
  const pageCount = Array.isArray(doc.pages) ? doc.pages.length : (doc.page_count ?? doc.pages);
  sourceOpener = opener;
  byId("source-title").textContent = doc.title;
  const status = el("p", { class: "sp-status", role: "status" });
  const stage = el("div", { class: "pdf-stage" }, el("span", { class: "skeleton" }));
  const fallback = el("div", { class: "fallback", hidden: true });
  const pager = el("div", { class: "sp-pager" });
  byId("source-body").replaceChildren(
    el("blockquote", { class: "sp-quote", style: "margin:0" }, `“${claim.quote}”`),
    el("div", { class: "sp-status" }, quoteBadge(claim), tag(claim.status)),
    pager, stage, status, fallback,
    el("dl", { class: "facts" },
      el("dt", {}, "Document"), el("dd", {}, `${doc.type} · ${formatDate(doc.date)}`),
      el("dt", {}, "Quote check"), el("dd", {}, claim.quote_checked ? "Found word for word on this page" : "Flagged for human review"),
      el("dt", {}, "Signed by"), el("dd", {}, doc.signed_by?.length ? doc.signed_by.join(", ") : "Not a signed record")),
    claim.review_note ? el("p", { class: "note-box" }, el("strong", {}, "Reviewer note: "), claim.review_note) : null,
  );
  byId("source-dialog").showModal();
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
    const result = await renderPage({ url, pageNumber, quote: onQuotePage ? claim.quote : null, container: stage, width });
    if (token !== sourceToken) return;
    if (!pageCount) pageCount = result.pages;
    if (!onQuotePage) { status.textContent = `Showing page ${pageNumber}. The quote is on page ${claim.page}.`; return; }
    if (result.mark) {
      status.replaceChildren(el("span", { class: "badge badge-ok" }, svg("0 0 16 16", ICONS.ok), "Highlighted"), "The quote is highlighted on the PDF page.",
        el("button", { type: "button", class: "btn-link", onclick: (event) => { event.currentTarget.remove(); showFallback("Page text, with the quote marked:"); } }, "Show page text"));
      result.mark.scrollIntoView({ block: "center", behavior: reducedMotion.matches ? "auto" : "smooth" });
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
  const article = el("article", { class: "receipt", "aria-labelledby": "shared-title", "aria-busy": "true" },
    [80, 60, 90, 70, 85].map((width) => el("span", { class: "skeleton sk-line", style: `width:${width}%` })));
  const title = el("h1", { id: "shared-title" }, "Shared receipt");
  view.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, title, el("p", { class: "page-sub" }, "A read-only copy of a Promise Ledger receipt. It cannot be edited from this link.")),
      el("div", { class: "page-actions" }, el("button", { type: "button", class: "btn btn-primary", onclick: () => window.print() }, icon("print"), "Print"))),
    el("p", { class: "shared-note" }, el("span", { class: "badge badge-info" }, svg("0 0 16 16", ICONS.machine), "Read-only"), "Each quote shows its document, date and page."),
    article,
  );
  try {
    // A /r/{token} page arrives with the read-only review already inside it.
    const inline = byId("review-data")?.textContent.trim();
    const shipped = inline ? JSON.parse(inline) : null;
    const review = shipped?.read_only ? shipped : await api(`/api/share/${encodeURIComponent(token)}`);
    if (current.view !== "shared") return;
    title.textContent = `${review.project}, ${review.city}`;
    document.title = `${review.project} receipt · Promise Ledger`;
    article.removeAttribute("aria-busy");
    renderReceipt(article, review, { titleTag: "h2" });
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
  const syncTheme = () => theme.setAttribute("aria-pressed", String(isDark()));
  theme.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("pl-theme", root.dataset.theme); } catch (err) { /* This visit only. */ }
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

// ---------- Start ----------
// Web fonts load after the first paint. Metric-matched fallbacks in style.css keep text from moving when they arrive.
const FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap";
function loadFonts() { document.head.append(el("link", { rel: "stylesheet", href: FONTS })); }
if (document.readyState === "complete") setTimeout(loadFonts, 0); else window.addEventListener("load", () => setTimeout(loadFonts, 0), { once: true });
setupToggles();
setupGlossaryPopovers();
setupNewDeal();
setupSourceDialog();
setupPageDrop();
ready = detectMode();
window.addEventListener("hashchange", () => route());
route({ initial: true });
setupVideos();
ready.then(async () => {
  if (current.view === "shared") return; // A shared link needs nothing beyond its receipt.
  try {
    const deals = await api("/api/deals");
    rememberSample(deals);
    const sample = deals.find((deal) => deal.id === sampleId);
    if (sample) fillHeroReceipt(await api(`/api/deals/${encodeURIComponent(sample.id)}/review`));
  } catch (err) { /* The home page keeps its shipped preview. */ }
});
