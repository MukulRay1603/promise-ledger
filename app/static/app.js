const byId = (id) => document.getElementById(id);
const STAGES = ["proposed", "supported", "signed", "delivered"];

let review = null;
let claimsById = new Map();
let documentsById = new Map();
let selectedId = null;

// Builds an element. All record text goes in through text nodes, never as HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

function formatDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric",
  });
}

const sourceLabel = (claim) => `${claim.document_type}, ${formatDate(claim.date)}, page ${claim.page}`;
const stageLabel = (status) => status[0].toUpperCase() + status.slice(1);

function statusChip(status) {
  const reached = STAGES.indexOf(status) + 1;
  const steps = el("span", { class: "steps", "aria-hidden": "true" });
  STAGES.forEach((_, index) => {
    steps.append(el("span", { class: index < reached ? "step on" : "step" }));
  });
  return el("span", { class: `status status-${status}` }, steps, stageLabel(status));
}

function sourceButton(claim, label) {
  return el("button", {
    type: "button",
    class: "link-button",
    "aria-label": `Open source: ${sourceLabel(claim)}`,
    onclick: () => selectClaim(claim.id, { moveFocus: true }),
  }, label);
}

function renderWording() {
  const items = review.claims.filter((claim) => claim.topic === "units");
  byId("wording").replaceChildren(...items.map((claim) => el("li", {},
    el("button", {
      type: "button",
      class: "wording-step",
      "aria-label": `"${claim.wording}", ${sourceLabel(claim)}, status ${claim.status}. Open source.`,
      onclick: () => selectClaim(claim.id, { moveFocus: true }),
    },
    el("time", { datetime: claim.date }, formatDate(claim.date)),
    el("span", { class: "verb" }, `“${claim.wording}”`),
    el("span", { class: "wording-value" }, claim.value),
    el("span", { class: "wording-doc" }, claim.document_type),
    statusChip(claim.status)),
  )));
}

function renderClaims() {
  const { passed, total, problems } = review.checks;
  byId("check-line").textContent = problems.length
    ? `${passed} of ${total} quotes passed the check. ${problems.length} flagged for human review.`
    : `Code found all ${total} quotes word for word on their cited pages.`;

  byId("claim-rows").replaceChildren(...review.claims.map((claim) => el("tr", { role: "row", id: `row-${claim.id}` },
    el("td", { role: "cell", "data-label": "Exact quote" },
      el("button", {
        type: "button",
        class: "quote-button",
        id: `quote-${claim.id}`,
        onclick: () => selectClaim(claim.id, { moveFocus: window.innerWidth < 1100 }),
      }, `“${claim.quote}”`)),
    el("td", { role: "cell", "data-label": "Source" },
      el("span", { class: "cell-line" }, claim.document_type),
      el("span", { class: "cell-line" }, formatDate(claim.date)),
      el("span", { class: "cell-line" }, `Page ${claim.page}`)),
    el("td", { role: "cell", "data-label": "Topic" }, review.topics[claim.topic]),
    el("td", { role: "cell", "data-label": "Status" }, statusChip(claim.status)),
  )));
}

function renderSource(claim) {
  const documentRecord = documentsById.get(claim.document);
  const page = documentRecord.pages.find((item) => item.page === claim.page);

  const paragraphs = page.paragraphs.map((text) => {
    const start = text.indexOf(claim.quote);
    if (start === -1) return el("p", {}, text);
    return el("p", {},
      text.slice(0, start),
      el("mark", {}, claim.quote),
      text.slice(start + claim.quote.length));
  });

  byId("source-body").replaceChildren(
    el("dl", { class: "source-meta" },
      el("dt", {}, "Document"), el("dd", {}, `${documentRecord.type}: ${documentRecord.title}`),
      el("dt", {}, "Date"), el("dd", {}, formatDate(documentRecord.date)),
      el("dt", {}, "Page"), el("dd", {}, `${claim.page} of ${documentRecord.pages.length}`),
      el("dt", {}, "Status"), el("dd", {}, statusChip(claim.status)),
      el("dt", {}, "Quote check"),
      el("dd", {}, claim.quote_checked ? "Found on this page" : "Flagged for human review"),
    ),
    el("div", { class: "sheet" }, ...paragraphs, el("p", { class: "folio" }, `Page ${claim.page}`)),
    el("p", { class: "review-note" }, el("strong", {}, "Reviewer note: "), claim.review_note),
    el("button", {
      type: "button",
      class: "link-button",
      onclick: () => byId(`quote-${claim.id}`).focus(),
    }, "Back to this claim in the table"),
  );
}

function selectClaim(id, { moveFocus = false } = {}) {
  if (selectedId) {
    byId(`row-${selectedId}`).classList.remove("selected");
    byId(`quote-${selectedId}`).removeAttribute("aria-current");
  }
  selectedId = id;
  byId(`row-${id}`).classList.add("selected");
  byId(`quote-${id}`).setAttribute("aria-current", "true");
  renderSource(claimsById.get(id));
  if (moveFocus) byId("source-heading").focus();
}

function renderStages() {
  byId("stages").replaceChildren(...review.stages.map((stage) => {
    const located = stage.claim_ids.length > 0;
    return el("li", { class: located ? "stage" : "stage stage-empty" },
      el("h3", {}, stage.label),
      el("p", { class: "stage-count" }, located
        ? `${stage.claim_ids.length} ${stage.claim_ids.length === 1 ? "claim" : "claims"}`
        : "Not located"),
      el("p", { class: "stage-note" }, stage.note),
      located
        ? el("ul", {}, ...stage.claim_ids.map((id) => {
          const claim = claimsById.get(id);
          return el("li", {},
            el("span", { class: "stage-value" }, claim.value),
            sourceButton(claim, `${claim.document_type}, page ${claim.page}`));
        }))
        : null,
    );
  }));
}

function renderTerms() {
  byId("term-rows").replaceChildren(...review.terms.map((term) => el("tr", { role: "row" },
    el("th", { role: "rowheader", scope: "row", "data-label": "Term" }, term.label),
    el("td", { role: "cell", "data-label": "Result" },
      el("span", { class: term.located ? "result" : "result not-located" }, term.result)),
    el("td", { role: "cell", "data-label": "What the records say" },
      term.located
        ? el("ul", { class: "plain" }, ...term.values.map((value) => el("li", {}, value)))
        : "No wording found in this packet",
      term.wording_differs ? el("span", { class: "flag" }, "Wording differs") : null),
    el("td", { role: "cell", "data-label": "Furthest stage" },
      term.furthest_status ? statusChip(term.furthest_status) : "None"),
    el("td", { role: "cell", "data-label": "Sources" },
      term.located
        ? el("ul", { class: "plain" }, ...term.claim_ids.map((id) => {
          const claim = claimsById.get(id);
          return el("li", {}, sourceButton(claim, `${claim.document_type}, p. ${claim.page}`));
        }))
        : "None"),
  )));
}

function renderReceipt() {
  const rows = review.terms.map((term) => {
    const signed = term.signed_claim_id ? claimsById.get(term.signed_claim_id) : null;
    const earlier = term.claim_ids
      .map((id) => claimsById.get(id))
      .filter((claim) => claim.status !== "signed");
    return el("tr", {},
      el("th", { scope: "row" }, term.label),
      el("td", {}, signed
        ? el("span", {}, `“${signed.quote}”`, el("span", { class: "receipt-source" }, sourceLabel(signed)))
        : el("span", { class: "result not-located" }, term.located ? "Not located in a signed record" : "Not located")),
      el("td", {}, earlier.length
        ? el("ul", { class: "plain" }, ...earlier.map((claim) => el("li", {},
          `${claim.value} (${claim.document_type}, p. ${claim.page})`)))
        : "None"),
    );
  });

  const flags = review.terms.flatMap((term) => {
    if (!term.located) return [`${term.label}: not located.`];
    if (!term.signed_claim_id) return [`${term.label}: not located in a signed record.`];
    return term.wording_differs ? [`${term.label}: wording differs across records.`] : [];
  });

  const support = review.claims.filter((claim) => claim.topic === "public_support");
  const { passed, total } = review.checks;

  byId("receipt-body").replaceChildren(
    el("header", { class: "receipt-head" },
      el("p", { class: "receipt-title" }, `${review.project}, ${review.city}`),
      el("p", {}, review.notice)),
    el("h3", {}, "Stages on record"),
    el("ul", { class: "receipt-stages" }, ...review.stages.map((stage) => el("li", {},
      el("span", { class: "receipt-stage-name" }, stage.label),
      el("span", {}, stage.claim_ids.length ? String(stage.claim_ids.length) : "Not located")))),
    ...review.stages
      .filter((stage) => ["signed", "delivered"].includes(stage.status))
      .map((stage) => el("p", { class: "receipt-stage-note" }, `${stage.label}: ${stage.note}`)),
    el("h3", {}, "Public support"),
    el("ul", { class: "plain receipt-support" }, ...support.map((claim) => el("li", {},
      `“${claim.quote}”`, el("span", { class: "receipt-source" }, sourceLabel(claim))))),
    el("h3", {}, "Terms"),
    el("div", { class: "receipt-scroll", tabindex: "0", role: "region", "aria-label": "Receipt terms table" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", { scope: "col" }, "Term"),
          el("th", { scope: "col" }, "Signed wording"),
          el("th", { scope: "col" }, "Earlier wording"))),
        el("tbody", {}, ...rows))),
    el("h3", {}, "Flagged for human review"),
    el("ul", {}, ...flags.map((flag) => el("li", {}, flag))),
    el("p", {}, `Quote check: ${passed} of ${total} quotes found on their cited pages.`),
    el("div", { class: "sign-off" },
      el("p", {}, "Reviewed by: ______________________"),
      el("p", {}, "Date: ______________")),
    el("p", { class: "receipt-foot" }, "This receipt is a review aid. It makes no legal findings."),
  );
}

function renderCandidates(result) {
  byId("extract-status").replaceChildren(
    el("p", { class: result.mode === "live" ? "extract-notice" : "extract-notice saved" }, result.notice),
    el("p", {}, `${result.candidates.length} candidate ${result.candidates.length === 1 ? "quote" : "quotes"} found.`
      + (result.dropped ? ` ${result.dropped} removed because the quote did not match the text.` : "")),
  );
  byId("extract-results").replaceChildren(...result.candidates.map((candidate) => el("li", {},
    el("p", { class: "candidate-quote" }, `“${candidate.quote}”`),
    el("p", {}, `Topic: ${review.topics[candidate.topic]}. Wording: “${candidate.wording}”.`),
    el("p", { class: "flag" }, candidate.review),
  )));
}

async function submitExtraction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  byId("extract-status").textContent = "Reading the text.";
  byId("extract-results").replaceChildren();
  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: form.text.value }),
    });
    if (res.status === 422) {
      throw new Error(`Enter between 20 and ${review.extraction.max_chars} characters.`);
    }
    if (!res.ok) throw new Error(`The server returned ${res.status}. Try again.`);
    renderCandidates(await res.json());
  } catch (err) {
    byId("extract-status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

async function start() {
  try {
    const res = await fetch("/api/review");
    if (!res.ok) throw new Error(`The server returned ${res.status}`);
    review = await res.json();
  } catch (err) {
    byId("load-status").textContent = `The review did not load. ${err.message}. Reload the page to try again.`;
    return;
  }
  claimsById = new Map(review.claims.map((claim) => [claim.id, claim]));
  documentsById = new Map(review.documents.map((item) => [item.id, item]));

  byId("demo-banner").textContent = review.notice;
  byId("page-title").textContent = `${review.project} review`;
  byId("extract-text").value = review.extraction.sample_text;
  byId("extract-text").maxLength = review.extraction.max_chars;

  renderWording();
  renderClaims();
  renderStages();
  renderTerms();
  renderReceipt();
  selectClaim(review.claims[0].id);
  byId("load-status").remove();
}

byId("extract-form").addEventListener("submit", submitExtraction);
byId("print-receipt").addEventListener("click", () => window.print());
start();
