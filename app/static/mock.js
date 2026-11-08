// In-browser stand-in for the deals API, used only while /api/deals is not live (or with ?mock=1).
// It follows the same contract as the server. Everything lives in memory and resets on reload.
// All data here is made up.

const DAY = 86400000;
const today = () => new Date(new Date().toDateString());
const iso = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const daysUntil = (isoDate) => Math.round((new Date(`${isoDate}T00:00:00`) - today()) / DAY);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const clone = (value) => JSON.parse(JSON.stringify(value));
const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "deal";

export class MockError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const STAGES = [
  ["proposed", "Proposed", "Described as an idea, a plan or an understanding."],
  ["supported", "Supported", "Recommended by staff or backed by a vote. Support is not a signed term."],
  ["signed", "Signed", "Stated in a record with at least one completed signature. Check who signed. A letter signed by one party is not an agreement signed by both."],
  ["delivered", "Delivered", "A certificate or occupancy record states the homes were built, leased or certified. It reports what the record says; it is not an inspection."],
];

function emptyReview(seed, name, city) {
  return {
    notice: `Made-up demo data. ${name} and ${city} are fictional.`,
    city, project: name, developer: null, documents: [], topics: seed.topics, claims: [], terms: [],
    stages: STAGES.map(([status, label, note]) => ({ status, label, note, result: "Not located", claim_ids: [] })),
    summary: {
      homes_described: null, homes_total: null, homes_claim_id: null, furthest_status: null, furthest_label: "None yet",
      stages_total: 4, terms_total: 0, terms_differ: 0, terms_not_located: 0, sentences: ["No documents read yet."],
    },
    questions: [], checks: { total: 0, passed: 0, problems: [] }, extraction: seed.extraction,
  };
}

// A second, smaller made-up deal. It matches the Mill Street sample PDFs: 9 of 60 homes until December 31, 2026.
function millStreet(seed) {
  const notice = "SAMPLE DOCUMENT · fictional · for demonstration";
  const docs = [
    {
      id: "reg-agreement", type: "Regulatory agreement", title: "Regulatory agreement (excerpt): Mill Street Lofts", date: "2011-06-14",
      signed: true, signed_by: ["City of Lantern Bay", "Mill Street Housing Associates LP"],
      pages: [
        { page: 1, paragraphs: [
          notice,
          "This Regulatory Agreement is made as of June 14, 2011, between the City of Lantern Bay (the City) and Mill Street Housing Associates LP (the Owner).",
          "4.1 The Owner shall reserve 9 of the 60 homes in the Project as Affordable Homes.",
          "4.2 Each Affordable Home shall be leased to a household with income at or below 50 percent of Area Median Income.",
        ] },
        { page: 2, paragraphs: [
          notice,
          "4.3 Monthly rent for each Affordable Home shall not exceed 30 percent of 50 percent of Area Median Income, adjusted for household size.",
          "5.1 The Affordability Period begins on January 1, 2012 and ends on December 31, 2026.",
          "6.1 The Owner is responsible for compliance with this Agreement, and this Agreement binds every later owner of the Project.",
          "7.1 The Owner shall deliver an annual compliance certificate to the City by March 31 of each year.",
        ] },
        { page: 3, paragraphs: [
          notice,
          "10.1 If a default is not cured within 30 days after written notice from the City, the Owner shall repay the property taxes exempted during the period of default.",
          "Signed for the City of Lantern Bay and for Mill Street Housing Associates LP, June 14, 2011.",
        ] },
      ],
    },
    {
      id: "cert-2024", type: "Compliance certificate", title: "2024 compliance certificate", date: "2025-03-18",
      signed: true, signed_by: ["Mill Street Housing Associates LP"],
      pages: [{ page: 1, paragraphs: [
        notice,
        "As of December 31, 2024, 9 of the 9 required Affordable Homes were leased to income-qualified households.",
      ] }],
    },
  ];
  const c = (id, doc, page, topic, status, value, quote, note) => {
    const d = docs.find((item) => item.id === doc);
    return { id, quote, document: doc, document_type: d.type, date: d.date, page, topic, status, wording: "shall", value, review_note: note, quote_checked: true };
  };
  const both = "Signed by the Owner and the City.";
  const claims = [
    c("m1", "reg-agreement", 1, "units", "signed", "9 of 60 homes", "4.1 The Owner shall reserve 9 of the 60 homes in the Project as Affordable Homes.", both),
    c("m2", "reg-agreement", 1, "income_basis", "signed", "50% of AMI", "4.2 Each Affordable Home shall be leased to a household with income at or below 50 percent of Area Median Income.", both),
    c("m3", "reg-agreement", 2, "rent_limits", "signed", "Rent at most 30% of 50% of AMI", "4.3 Monthly rent for each Affordable Home shall not exceed 30 percent of 50 percent of Area Median Income, adjusted for household size.", both),
    c("m4", "reg-agreement", 2, "term", "signed", "Jan 1, 2012 to Dec 31, 2026", "5.1 The Affordability Period begins on January 1, 2012 and ends on December 31, 2026.", "The term ends December 31, 2026."),
    c("m5", "reg-agreement", 2, "responsible_party", "signed", "The Owner and every later owner", "6.1 The Owner is responsible for compliance with this Agreement, and this Agreement binds every later owner of the Project.", both),
    c("m6", "reg-agreement", 2, "reporting", "signed", "Yearly certificate by March 31", "7.1 The Owner shall deliver an annual compliance certificate to the City by March 31 of each year.", "The 2025 certificate was not located in this file."),
    c("m7", "reg-agreement", 3, "remedies", "signed", "Repay exempted taxes if not cured in 30 days", "10.1 If a default is not cured within 30 days after written notice from the City, the Owner shall repay the property taxes exempted during the period of default.", both),
    c("m8", "cert-2024", 1, "units", "delivered", "9 homes leased on Dec 31, 2024", "As of December 31, 2024, 9 of the 9 required Affordable Homes were leased to income-qualified households.", "The owner's own certificate. It is not an inspection."),
  ];
  claims[0].homes = { count: 9, of: 60 };
  const term = (key, ids, signedId) => ({ key, label: seed.topics[key], located: true, wording_differs: false, claim_ids: ids, signed_claim_id: signedId });
  return {
    notice: "Made-up demo data. Lantern Bay, Mill Street Lofts, Mill Street Housing Associates LP and every date, number and quote here are fictional.",
    city: "Lantern Bay", project: "Mill Street Lofts", developer: "Mill Street Housing Associates LP", documents: docs, topics: seed.topics, claims,
    terms: [
      term("units", ["m1", "m8"], "m1"), term("income_basis", ["m2"], "m2"), term("rent_limits", ["m3"], "m3"), term("term", ["m4"], "m4"),
      term("responsible_party", ["m5"], "m5"), term("reporting", ["m6"], "m6"), term("remedies", ["m7"], "m7"),
    ],
    stages: STAGES.map(([status, label, note]) => {
      const ids = claims.filter((claim) => claim.status === status).map((claim) => claim.id);
      return { status, label, note, result: ids.length ? "Located" : "Not located", claim_ids: ids };
    }),
    summary: {
      homes_described: 9, homes_total: 60, homes_claim_id: "m1", furthest_status: "delivered", furthest_label: "Delivered",
      stages_total: 4, terms_total: 7, terms_differ: 0, terms_not_located: 0, signed_by_developer_only: false, city_signed: true,
      sentences: [
        "9 of 60 homes described as affordable.",
        "Signed by the Owner and the City; the Owner's 2024 certificate reports 9 homes leased.",
        "0 terms differ across records · 0 terms not located.",
      ],
    },
    questions: [
      { key: "reporting:not_located", tag: "not_located", text: "Reporting: the 2025 compliance certificate was not located in this file. Ask the Owner for it." },
      { key: "term:no_extension", tag: "not_located", text: "Term: the affordability term ends December 31, 2026, and no extension was located in this file. Ask staff whether an agreement covers the homes after that date." },
    ],
    checks: { total: 8, passed: 8, problems: [] },
    extraction: seed.extraction,
  };
}

// A small, valid PDF built from page text, so the viewer can show a real page with a real text layer.
const WIN_ANSI = { "‘": 0o221, "’": 0o222, "“": 0o223, "”": 0o224, "–": 0o226, "—": 0o227, "·": 0o267, " ": 0o40 };
function pdfString(text) {
  return text.replace(/[\\()]/g, (m) => `\\${m}`).replace(/[^\x20-\x7e]/g, (ch) => {
    const code = WIN_ANSI[ch] ?? (ch.charCodeAt(0) < 256 ? ch.charCodeAt(0) : 63);
    return `\\${code.toString(8).padStart(3, "0")}`;
  });
}
function wrap(text, width) {
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    if (line && (line.length + 1 + word.length) > width) { lines.push(line); line = word; } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines;
}
export function buildPdf(doc) {
  const objects = [];
  const add = (body) => { objects.push(body); return objects.length; };
  add("<< /Type /Catalog /Pages 2 0 R >>");
  add("PAGES");
  add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
  add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");
  const kids = [];
  for (const page of doc.pages) {
    const ops = ["BT", "/F2 13 Tf", "72 728 Td", "16 TL", `(${pdfString(doc.title)}) Tj`, "/F1 9 Tf", "T*", `(${pdfString(`${doc.type} · ${doc.date} · Page ${page.page} of ${doc.pages.length}`)}) Tj`, "/F1 11 Tf", "T* T*"];
    for (const paragraph of page.paragraphs) {
      for (const line of wrap(paragraph, 84)) ops.push(`(${pdfString(line)}) Tj T*`);
      ops.push("T*");
    }
    ops.push("ET");
    const stream = ops.join("\n");
    const content = add(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
    kids.push(add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${content} 0 R >>`));
  }
  objects[1] = `<< /Type /Pages /Kids [${kids.map((n) => `${n} 0 R`).join(" ")}] /Count ${kids.length} >>`;
  let out = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((body, index) => { offsets.push(out.length); out += `${index + 1} 0 obj\n${body}\nendobj\n`; });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((n) => `${String(n).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new Blob([out], { type: "application/pdf" });
}

// The same sheets the server exports (deals.export_sheets), so the offline preview and CSV match it.
const guard = (value) => (typeof value === "string" && /^[=+\-@\t\r]/.test(value) ? `'${value}` : value);
const stamp = (at) => at.replace("T", " ").replace("+00:00", " UTC");
function exportSheets(review, view) {
  const latest = view?.latest || {};
  const decided = (key) => { const e = latest[key]; return e ? [e.label, e.reviewer_name, stamp(e.at), e.note] : ["Not reviewed", "", "", ""]; };
  const differs = new Set(review.terms.filter((t) => t.wording_differs).map((t) => t.key));
  const label = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
  const titles = Object.fromEntries(review.documents.map((d) => [d.id, d.title]));
  const claims = Object.fromEntries(review.claims.map((c) => [c.id, c]));
  const questions = Object.fromEntries(review.questions.map((q) => [q.key, q]));
  const flags = { differs: "Wording differs", not_located: "Not located" };
  const item = (e) => {
    const c = e.target_type === "claim" ? claims[e.target_id] : null;
    if (c) return `Claim: ${review.topics[c.topic] || c.topic}, ${c.document_type} p. ${c.page}`;
    const q = questions[e.target_id];
    return q ? `Open question: ${q.text.slice(0, 80)}` : e.target_id;
  };
  const sheets = [
    { name: "Claims", columns: ["Term", "Quote", "Document", "Date", "Page", "Stage", "Wording differs", "Quote found on page", "Decision", "Reviewer", "Decided", "Note"],
      rows: review.claims.map((c) => [review.topics[c.topic] || c.topic, c.quote, titles[c.document] || c.document_type, c.date, c.page, label(c.status),
        differs.has(c.topic) ? "Yes" : "No", c.quote_checked ? "Found" : "Flagged for human review", ...decided(`claim:${c.id}`)]) },
    { name: "Terms", columns: ["Term", "Result", "Furthest stage (any term)", "Wording differs", "Values", "Signed record"],
      rows: review.terms.map((t) => [t.label, t.located ? "Located" : "Not located", "", t.wording_differs ? "Yes" : "No", "", t.signed_claim_id ? "Yes" : "No"]) },
    { name: "Open questions", columns: ["Open question", "Flag", "Decision", "Reviewer", "Decided", "Note"],
      rows: review.questions.map((q) => [q.text, flags[q.tag] || q.tag || "", ...decided(`question:${q.key}`)]) },
    { name: "Review log", columns: ["When", "Reviewer", "Item", "Decision", "Note"],
      rows: (view?.log || []).map((e) => [stamp(e.at), e.reviewer_name, item(e), e.label, e.note]) },
  ];
  return sheets.map((sheet) => ({ ...sheet, rows: sheet.rows.map((row) => row.map(guard)) }));
}

function csvFor(review, view) {
  const cell = (value) => { const text = String(value ?? ""); return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text; };
  const claims = exportSheets(review, view)[0];
  return `${[claims.columns, ...claims.rows].map((row) => row.map(cell).join(",")).join("\r\n")}\r\n`;
}

const STEP_MS = { reading: 1600, checking: 1400 };

export function createMock(seed) {
  const deals = new Map();
  const files = new Map();
  const put = (id, name, city, review, extra = {}) => {
    const documents = review.documents.map((doc) => ({ id: doc.id, title: doc.title, type: doc.type, date: doc.date, pages: doc.pages.length, status: "done" }));
    deals.set(id, { id, name, city, review, documents, reminders: [], created: Date.now(), ...extra });
  };
  put("harbor-walk", seed.project, seed.city, clone(seed), { sample: true });
  put("mill-street", "Mill Street Lofts", "Lantern Bay", millStreet(seed), { sample: true });
  put("ferry-point", "Ferry Point Homes", "Lantern Bay", emptyReview(seed, "Ferry Point Homes", "Lantern Bay"));

  // Like the server, a sample deal is read as of its file's date, and days count from that date (+ until due, − past).
  const asOf = "2026-04-15";
  const daysFrom = (due) => Math.round((new Date(`${due}T00:00:00`) - new Date(`${asOf}T00:00:00`)) / DAY);
  const reminder = (kind, due, text) => ({ kind, due, date: due, days: daysFrom(due), as_of: asOf, overdue: due < asOf, text });
  deals.get("mill-street").reminders = [
    reminder("term_end", "2026-12-31", "Affordability term ends Dec 31, 2026, as stated in the regulatory agreement dated Jun 14, 2011."),
    reminder("missing_record", "2026-03-31", "Yearly certificate due Mar 31, 2026: not located in this file."),
  ];
  deals.get("harbor-walk").reminders = [
    { kind: "missing_record", due: null, text: "Harbor Walk: City-signed agreement not located" },
  ];

  // Mirrors the server's decision_view: latest per item, newest-first log, progress and the stamp.
  const decisionView = (deal) => {
    const log = [...(deal.decisions || [])].sort((a, b) => a.id.localeCompare(b.id));
    const latest = {};
    for (const e of log) latest[`${e.target_type}:${e.target_id}`] = e;
    const r = deal.review;
    const claimsDone = r.claims.filter((c) => latest[`claim:${c.id}`]).length;
    const flagged = r.questions.map((q) => q.key);
    const flaggedDone = flagged.filter((k) => latest[`question:${k}`]).length;
    const complete = flagged.length > 0 && flaggedDone === flagged.length;
    // The stamp follows the open questions, or the claims when there are none (server: review_stamp).
    const keys = flagged.length ? flagged.map((k) => `question:${k}`) : r.claims.map((c) => `claim:${c.id}`);
    const decided = keys.map((k) => latest[k]).filter(Boolean);
    let stamp = { state: "flagged", text: "Flagged for human review", reviewer: null, date: null, decided: decided.length, total: keys.length };
    if (decided.length) {
      const last = [...decided].sort((a, b) => a.id.localeCompare(b.id)).pop();
      stamp = { ...stamp, reviewer: last.reviewer_name, date: last.at.slice(0, 10) };
      const count = (d) => decided.filter((e) => e.decision === d).length;
      const disputed = count("disputed");
      const followUp = count("follow_up");
      const needs = followUp ? ` · ${followUp} need${followUp === 1 ? "s" : ""} follow-up` : "";
      if (decided.length < keys.length) stamp = { ...stamp, state: "in_progress", text: `Review in progress · ${decided.length} of ${keys.length} decided` };
      else if (disputed) stamp = { ...stamp, state: "complete_disputed", text: `Review complete · ${disputed} disputed${needs}` };
      else if (followUp) stamp = { ...stamp, state: "complete_follow_up", text: `Review complete${needs}` };
      else stamp = { ...stamp, state: "complete_confirmed", text: "Review complete · all confirmed" };
    }
    return { latest, log: log.reverse(), stamp, footer: "A review records people's decisions. It is not a legal finding.", sandboxed: Boolean(deal.sample), progress: { claims_reviewed: claimsDone, claims_total: r.claims.length, flagged_reviewed: flaggedDone, flagged_total: flagged.length, reviewed: claimsDone + flaggedDone, total: r.claims.length + flagged.length, complete } };
  };

  const find = (id) => { const deal = deals.get(id); if (!deal) throw new MockError(404, "Deal not found"); return deal; };
  const advance = (doc) => {
    if (doc.status === "done" || doc.status === "failed" || !doc._t) return;
    const age = Date.now() - doc._t;
    if (doc._bad) { if (age > 900) { doc.status = "failed"; doc.error = doc._bad; } else doc.status = "reading"; return; }
    if (age > STEP_MS.reading + STEP_MS.checking) doc.status = "done";
    else if (age > STEP_MS.reading) doc.status = "checking";
    else doc.status = "reading";
  };
  const publicDoc = (doc) => { advance(doc); const { _t, _bad, _name, _size, ...rest } = doc; return rest; };
  const summary = (deal) => {
    const s = deal.review.summary;
    const next = [...deal.reminders].sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"))[0] || null;
    return {
      id: deal.id, name: deal.name, city: deal.city, documents: deal.documents.length,
      furthest_status: s.furthest_status, terms_differ: s.terms_differ, terms_not_located: s.terms_not_located,
      next_reminder: next ? { text: next.text, due: next.due } : null,
    };
  };

  async function handle(method, path, body, options = {}) {
    const { onProgress } = options;
    await wait(120 + Math.random() * 160);
    const url = new URL(path, location.origin);
    const parts = url.pathname.replace(/^\/api\//, "").split("/").filter(Boolean);
    const [root, id, sub, docId, leaf, page] = parts;

    if (root === "deals" && !id && method === "GET") return [...deals.values()].sort((a, b) => a.created - b.created).map(summary);
    if (root === "deals" && !id && method === "POST") {
      const name = String(body?.name || "").trim();
      const city = String(body?.city || "").trim();
      if (!name || !city) throw new MockError(422, "Enter a project name and a city.");
      let newId = slug(name);
      while (deals.has(newId)) newId += "-2";
      put(newId, name, city, emptyReview(seed, name, city));
      return summary(deals.get(newId));
    }
    if (root === "reminders") {
      return [...deals.values()].flatMap((deal) => deal.reminders.map((item) => ({ deal_id: deal.id, deal_name: deal.name, ...item })))
        .sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
    }
    if (root === "share" && id) {
      let dealId = "";
      try { dealId = atob(id.replace(/^demo-/, "")); } catch (err) { /* bad token */ }
      if (!deals.has(dealId)) throw new MockError(404, "This link is not valid or has been turned off.");
      return clone(deals.get(dealId).review);
    }
    if (root !== "deals") throw new MockError(404, "Not found");

    const deal = find(id);
    if (!sub && method === "GET") return { id: deal.id, name: deal.name, city: deal.city, documents: deal.documents.map(publicDoc) };
    if (sub === "review") return { ...clone(deal.review), decisions: decisionView(deal) };
    if (sub === "decisions" && method === "GET") return decisionView(deal);
    if (sub === "decisions" && method === "DELETE") { deal.decisions = []; return decisionView(deal); }
    if (sub === "decisions" && method === "POST") {
      const labels = { confirmed: "Confirmed", follow_up: "Needs follow-up", disputed: "Disputed" };
      const reviewer = String(options.reviewer || "").trim();
      if (!labels[body?.decision]) throw new MockError(422, "Choose Confirm, Needs follow-up or Disputed.");
      if (!reviewer) throw new MockError(422, "Enter a reviewer name.");
      if (String(body.note || "").length > 500) throw new MockError(422, "Keep the note under 500 characters.");
      const event = { id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`, target_type: body.target_type, target_id: body.target_id,
        decision: body.decision, label: labels[body.decision], note: String(body.note || "").trim(), reviewer_id: `demo:${options.session}`, reviewer_name: reviewer, at: new Date().toISOString().replace(/\.\d+Z$/, "+00:00") };
      (deal.decisions ||= []).push(event);
      return { event, ...decisionView(deal) };
    }
    if (sub === "share" && method === "POST") {
      const token = `demo-${btoa(deal.id).replace(/=+$/, "")}`;
      return { token, url: `${location.origin}/#/r/${token}` };
    }
    if (sub === "export.csv" || sub === "export.xlsx") return new Blob([csvFor(deal.review, decisionView(deal))], { type: "text/csv" });
    if (sub === "export.json") {
      // Same shape as the server's preview: Claims, Terms, Open questions, Review log and About.
      const r = deal.review;
      return {
        title: `${r.project} · Promise receipt`, project: r.project, city: r.city, csv_sheet: "Claims",
        files: { xlsx: `${deal.id}-promise-ledger.xlsx`, csv: `${deal.id}-promise-ledger.csv` },
        sheets: [...exportSheets(r, decisionView(deal)),
          { name: "About", columns: ["Note"], rows: [[guard(`${r.project}, ${r.city}`)], [r.notice], [`Exported ${new Date().toISOString().replace(/\.\d+Z$/, "+00:00")}`]] }],
      };
    }
    if (sub === "documents" && docId && leaf === "retry" && method === "POST") {
      const doc = deal.documents.find((d) => d.id === docId);
      if (!doc) throw new MockError(404, "Document not found");
      if (deal.sample) throw new MockError(403, "Sample deals are read-only. Start a new deal to try your own PDFs.");
      if (doc.status !== "failed") throw new MockError(409, "Only a document that could not be read can be retried.");
      Object.assign(doc, { status: "queued", error: null, _t: Date.now() });
      return publicDoc(doc);
    }
    if (sub === "documents" && method === "POST") {
      if (deal.sample) throw new MockError(403, "Sample deals are read-only. Start a new deal to try your own PDFs.");
      const file = body.get("file");
      // The same file twice returns the first copy, marked duplicate, so claims never double.
      const same = deal.documents.find((d) => d._name === file.name && d._size === file.size);
      if (same) return { ...publicDoc(same), duplicate: true };
      for (let step = 1; step <= 6; step += 1) { await wait(110); onProgress?.(step / 6); }
      const head = new Uint8Array(await file.slice(0, 5).arrayBuffer());
      const isPdf = String.fromCharCode(...head) === "%PDF-";
      const doc = {
        id: `doc-${Date.now().toString(36)}`, title: body.get("title") || file.name.replace(/\.pdf$/i, ""),
        type: body.get("type") || "Uploaded record", date: body.get("date") || iso(today()), pages: null,
        status: "reading", _t: Date.now(), _name: file.name, _size: file.size, _bad: isPdf ? null : "This file is not a readable PDF.",
      };
      deal.documents.push(doc);
      files.set(`${deal.id}/${doc.id}`, file);
      return publicDoc(doc);
    }
    if (sub === "documents" && docId && leaf === "pages") {
      const source = deal.review.documents.find((doc) => doc.id === docId);
      const found = source?.pages.find((item) => item.page === Number(page));
      if (!found) throw new MockError(404, "Page not found");
      return { page: found.page, text: found.paragraphs.join("\n\n") };
    }
    throw new MockError(404, "Not found");
  }

  // The file endpoint returns a PDF. Here it is a blob URL: the uploaded file, or one built from page text.
  const urls = new Map();
  function fileUrl(dealId, docId) {
    const key = `${dealId}/${docId}`;
    if (urls.has(key)) return urls.get(key);
    let blob = files.get(key);
    if (!blob) {
      const doc = deals.get(dealId)?.review.documents.find((item) => item.id === docId);
      if (!doc) return null;
      blob = buildPdf(doc);
    }
    const url = URL.createObjectURL(blob);
    urls.set(key, url);
    return url;
  }

  return { handle, fileUrl };
}
