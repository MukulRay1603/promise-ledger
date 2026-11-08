// Renders one real PDF page with pdf.js and highlights an exact quote on its text layer.
// Loaded only when someone opens a source, so the main page stays light.
// Served from this site (app/static/vendor), so the CSP can keep scripts and workers to 'self'.
const PDFJS_VERSION = "4.10.38";
const BASE = `/static/vendor/pdfjs-${PDFJS_VERSION}/`;

let libPromise = null;
const documents = new Map();

function loadLib() {
  if (!libPromise) {
    libPromise = import(`${BASE}pdf.min.mjs`).then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = `${BASE}pdf.worker.min.mjs`;
      return lib;
    });
    libPromise.catch(() => { libPromise = null; });
  }
  return libPromise;
}

function openDocument(lib, url, headers = {}) {
  if (!documents.has(url)) {
    const task = lib.getDocument({ url, httpHeaders: headers, isEvalSupported: false }).promise;
    task.catch(() => documents.delete(url));
    documents.set(url, task);
  }
  return documents.get(url);
}

// Text normalizing shared by the page text and the quote, so curly quotes, dashes and spacing do not block a match.
const FOLD = { "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "­": "", " ": " " };
const fold = (ch) => (ch in FOLD ? FOLD[ch] : ch).toLowerCase();

function buildIndex(spans, keep) {
  let text = "";
  const map = [];
  let lastSpace = true;
  spans.forEach((span, spanIndex) => {
    const raw = span.firstChild.nodeValue;
    if (keep === "spaced" && !lastSpace) { text += " "; map.push(null); lastSpace = true; }
    for (let i = 0; i < raw.length; i += 1) {
      const ch = fold(raw[i]);
      if (!ch) continue;
      if (keep === "spaced") {
        if (/\s/.test(ch)) { if (lastSpace) continue; text += " "; map.push(null); lastSpace = true; continue; }
        lastSpace = false;
      } else if (!/[\p{L}\p{N}]/u.test(ch)) continue;
      text += ch;
      map.push([spanIndex, i]);
    }
  });
  return { text, map };
}

function normalizeQuote(quote, keep) {
  const folded = [...quote].map(fold).join("");
  return keep === "spaced" ? folded.replace(/\s+/g, " ").trim() : folded.replace(/[^\p{L}\p{N}]/gu, "");
}

// Wraps the matched characters of each span in <mark class="hl">. Returns the first mark, or null.
export function highlight(layer, quote) {
  const spans = [...layer.querySelectorAll("span")].filter((span) => span.childNodes.length === 1 && span.firstChild.nodeType === 3);
  for (const keep of ["spaced", "alnum"]) {
    const { text, map } = buildIndex(spans, keep);
    const needle = normalizeQuote(quote, keep);
    if (!needle) return null;
    const at = text.indexOf(needle);
    if (at === -1) continue;
    const ranges = new Map();
    for (let k = at; k < at + needle.length; k += 1) {
      const hit = map[k];
      if (!hit) continue;
      const range = ranges.get(hit[0]);
      if (range) range[1] = hit[1]; else ranges.set(hit[0], [hit[1], hit[1]]);
    }
    let first = null;
    for (const [spanIndex, [start, end]] of ranges) {
      const span = spans[spanIndex];
      const raw = span.firstChild.nodeValue;
      const mark = document.createElement("mark");
      mark.className = "hl";
      mark.textContent = raw.slice(start, end + 1);
      span.replaceChildren(raw.slice(0, start), mark, raw.slice(end + 1));
      first ??= mark;
    }
    return first;
  }
  return null;
}

// Draws page `pageNumber` of the PDF at `url` into `container`, `width` CSS pixels wide.
export async function renderPage({ url, pageNumber, quote, container, width, headers = {} }) {
  const lib = await loadLib();
  const pdf = await openDocument(lib, url, headers);
  const page = await pdf.getPage(Math.min(Math.max(1, pageNumber), pdf.numPages));
  const scale = width / page.getViewport({ scale: 1 }).width;
  const viewport = page.getViewport({ scale });
  const ratio = Math.min(window.devicePixelRatio || 1, 2);

  const wrapper = document.createElement("div");
  wrapper.className = "pdf-page";
  wrapper.style.width = `${viewport.width}px`;
  wrapper.style.height = `${viewport.height}px`;
  wrapper.style.setProperty("--scale-factor", String(scale));

  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  canvas.setAttribute("aria-hidden", "true");

  const layer = document.createElement("div");
  layer.className = "textLayer";
  wrapper.append(canvas, layer);

  await page.render({
    canvasContext: canvas.getContext("2d"),
    viewport,
    transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
  }).promise;
  const textLayer = new lib.TextLayer({ textContentSource: await page.getTextContent(), container: layer, viewport });
  await textLayer.render();

  container.replaceChildren(wrapper);
  const mark = quote ? highlight(layer, quote) : null;
  return { mark, pages: pdf.numPages, page: page.pageNumber };
}
