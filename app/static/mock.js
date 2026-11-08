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
  ["signed", "Signed", "Written in a signed record."],
  ["delivered", "Delivered", "A record shows homes were built, leased or checked."],
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

// A second, smaller made-up deal so the list and reminders have something to compare.
function millStreet(seed) {
  const docs = [
    {
      id: "reg-agreement", type: "Regulatory agreement", title: "Regulatory agreement: Mill Street Lofts", date: "2011-06-01",
      signed: true, signed_by: ["Mill Street Housing LLC", "City of Lantern Bay"],
      pages: [
        { page: 1, paragraphs: [
          "MADE-UP DEMO RECORD. Lantern Bay is a fictional city.",
          "This agreement is made between the City of Lantern Bay and Mill Street Housing LLC, the Owner of Mill Street Lofts.",
          "The Owner shall keep 36 of the 180 homes affordable.",
          "Each affordable home shall be rented to a household earning at or below 50 percent of area median income.",
        ] },
        { page: 2, paragraphs: [
          "MADE-UP DEMO RECORD. Lantern Bay is a fictional city.",
          "These restrictions shall remain in effect for 15 years from January 1, 2012.",
          "The Owner shall send the City a compliance certificate each year by March 31.",
        ] },
      ],
    },
    {
      id: "cert-2024", type: "Compliance certificate", title: "2024 compliance certificate", date: "2024-03-20",
      signed: true, signed_by: ["Mill Street Housing LLC"],
      pages: [{ page: 1, paragraphs: [
        "MADE-UP DEMO RECORD. Lantern Bay is a fictional city.",
        "The Owner certifies that 36 affordable homes were leased to eligible households during 2023.",
      ] }],
    },
  ];
  const c = (id, doc, page, topic, status, value, quote, note) => {
    const d = docs.find((item) => item.id === doc);
    return { id, quote, document: doc, document_type: d.type, date: d.date, page, topic, status, wording: "shall", value, review_note: note, quote_checked: true };
  };
  const claims = [
    c("m1", "reg-agreement", 1, "units", "signed", "36 of 180 homes", "The Owner shall keep 36 of the 180 homes affordable.", "Signed by the Owner and the City."),
    c("m2", "reg-agreement", 1, "income_basis", "signed", "50 percent of area median income", "Each affordable home shall be rented to a household earning at or below 50 percent of area median income.", "Signed by the Owner and the City."),
    c("m3", "reg-agreement", 2, "term", "signed", "15 years from January 1, 2012", "These restrictions shall remain in effect for 15 years from January 1, 2012.", "The term ends January 1, 2027."),
    c("m4", "reg-agreement", 2, "reporting", "signed", "Yearly certificate by March 31", "The Owner shall send the City a compliance certificate each year by March 31.", "The 2025 certificate was not located in this packet."),
    c("m5", "cert-2024", 1, "units", "delivered", "36 homes leased in 2023", "The Owner certifies that 36 affordable homes were leased to eligible households during 2023.", "Owner certification. Not an inspection."),
  ];
  claims[0].homes = { count: 36, of: 180 };
  const term = (key, ids, signedId, located = true) => ({ key, label: seed.topics[key], located, wording_differs: false, claim_ids: ids, signed_claim_id: signedId });
  return {
    notice: "Made-up demo data. Lantern Bay, Mill Street Lofts, Mill Street Housing LLC and every date, number and quote here are fictional.",
    city: "Lantern Bay", project: "Mill Street Lofts", developer: "Mill Street Housing LLC", documents: docs, topics: seed.topics, claims,
    terms: [
      term("units", ["m1", "m5"], "m1"), term("income_basis", ["m2"], "m2"), term("rent_limits", [], null, false), term("term", ["m3"], "m3"),
      term("responsible_party", [], null, false), term("reporting", ["m4"], "m4"), term("remedies", [], null, false),
    ],
    stages: STAGES.map(([status, label, note]) => {
      const ids = claims.filter((claim) => claim.status === status).map((claim) => claim.id);
      return { status, label, note, result: ids.length ? "Located" : "Not located", claim_ids: ids };
    }),
    summary: {
      homes_described: 36, homes_total: 180, homes_claim_id: "m1", furthest_status: "delivered", furthest_label: "Delivered",
      stages_total: 4, terms_total: 7, terms_differ: 0, terms_not_located: 3, signed_by_developer_only: false, city_signed: true,
      sentences: [
        "36 of 180 homes described as affordable.",
        "Signed by the Owner and the City; a 2024 certificate reports 36 homes leased.",
        "0 terms differ across records · 3 terms not located.",
      ],
    },
    questions: [
      { key: "reporting", tag: "not_located", text: "Reporting: the 2025 compliance certificate was not located. Ask the Owner for it." },
      { key: "rent_limits", tag: "not_located", text: "Rent limits: not located. Ask staff for the agreement section on rent limits." },
      { key: "responsible_party", tag: "not_located", text: "Responsible party: not located. Ask staff who is responsible after a sale." },
      { key: "remedies", tag: "not_located", text: "Remedies: not located. Ask staff for the agreement section on remedies." },
    ],
    checks: { total: 5, passed: 5, problems: [] },
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

function csvFor(review) {
  const cell = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const rows = [["Term", "Stage", "Value", "Exact quote", "Document", "Date", "Page", "Quote check"]];
  for (const claim of review.claims) {
    rows.push([review.topics[claim.topic], claim.status, claim.value, claim.quote, claim.document_type, claim.date, claim.page, claim.quote_checked ? "Found word for word" : "Flagged for human review"]);
  }
  return `${review.notice}\n${rows.map((row) => row.map(cell).join(",")).join("\n")}\n`;
}

const STEP_MS = { reading: 1600, checking: 1400 };

export function createMock(seed) {
  const deals = new Map();
  const files = new Map();
  const put = (id, name, city, review, extra = {}) => {
    const documents = review.documents.map((doc) => ({ id: doc.id, title: doc.title, type: doc.type, date: doc.date, pages: doc.pages.length, status: "done" }));
    deals.set(id, { id, name, city, review, documents, reminders: [], created: Date.now(), ...extra });
  };
  put("harbor-walk", seed.project, seed.city, clone(seed));
  put("mill-street", "Mill Street Lofts", "Lantern Bay", millStreet(seed));
  put("ferry-point", "Ferry Point Homes", "Lantern Bay", emptyReview(seed, "Ferry Point Homes", "Lantern Bay"));

  const termEnd = "2027-01-01";
  deals.get("mill-street").reminders = [
    { kind: "term_end", due: termEnd, text: `Mill Street Lofts: affordability ends in ${daysUntil(termEnd)} days` },
    { kind: "missing_record", due: "2025-03-31", text: "Mill Street Lofts: 2025 compliance certificate not received" },
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
    let stamp = { state: "flagged", text: "Flagged for human review" };
    if (complete) {
      const last = flagged.map((k) => latest[`question:${k}`]).sort((a, b) => a.id.localeCompare(b.id)).pop();
      stamp = { state: "reviewed", reviewer_name: last.reviewer_name, date: last.at.slice(0, 10), text: `Reviewed · ${last.reviewer_name} · ${last.at.slice(0, 10)}` };
    }
    return { latest, log: log.reverse(), stamp, sandboxed: true, progress: { claims_reviewed: claimsDone, claims_total: r.claims.length, flagged_reviewed: flaggedDone, flagged_total: flagged.length, reviewed: claimsDone + flaggedDone, total: r.claims.length + flagged.length, complete } };
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
  const publicDoc = (doc) => { advance(doc); const { _t, _bad, ...rest } = doc; return rest; };
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
    if (sub === "export.csv" || sub === "export.xlsx") return new Blob([csvFor(deal.review)], { type: "text/csv" });
    if (sub === "export.json") {
      // Same shape as the server's preview: Claims and Terms sheets plus an About note.
      const r = deal.review;
      const differs = new Set(r.terms.filter((t) => t.wording_differs).map((t) => t.key));
      const stage = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
      const titles = Object.fromEntries(r.documents.map((d) => [d.id, d.title]));
      return {
        title: `${r.project} · Promise receipt`, project: r.project, city: r.city, csv_sheet: "Claims",
        files: { xlsx: `${deal.id}-promise-ledger.xlsx`, csv: `${deal.id}-promise-ledger.csv` },
        sheets: [
          { name: "Claims", columns: ["Term", "Quote", "Document", "Date", "Page", "Stage", "Wording differs", "Verified"],
            rows: r.claims.map((c) => [r.topics[c.topic] || c.topic, c.quote, titles[c.document] || c.document_type, c.date, c.page, stage(c.status), differs.has(c.topic) ? "Yes" : "No", c.quote_checked ? "Yes" : "No"]) },
          { name: "Terms", columns: ["Term", "Result", "Furthest stage", "Wording differs", "Values", "Signed record"],
            rows: r.terms.map((t) => [t.label, t.located ? "Located" : "Not located", "", t.wording_differs ? "Yes" : "No", "", t.signed_claim_id ? "Yes" : "No"]) },
          { name: "About", columns: ["Note"], rows: [[`${r.project}, ${r.city}`], [r.notice]] },
        ],
      };
    }
    if (sub === "documents" && method === "POST") {
      const file = body.get("file");
      for (let step = 1; step <= 6; step += 1) { await wait(110); onProgress?.(step / 6); }
      const head = new Uint8Array(await file.slice(0, 5).arrayBuffer());
      const isPdf = String.fromCharCode(...head) === "%PDF-";
      const doc = {
        id: `doc-${Date.now().toString(36)}`, title: body.get("title") || file.name.replace(/\.pdf$/i, ""),
        type: body.get("type") || "Uploaded record", date: body.get("date") || iso(today()), pages: null,
        status: "reading", _t: Date.now(), _bad: isPdf ? null : "This file is not a readable PDF.",
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
