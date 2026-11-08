# Promise Ledger

Source-linked receipts for public housing deals.

When a housing project asks for public support, its affordability terms get spread across staff reports, letters, slides and minutes. Promise Ledger turns those records into one review page: how many homes, for whom, for how long, and where the evidence is.

**Status:** early prototype for GDG AI for Good 2026: Housing. The demo uses a made-up packet. Nothing here makes legal findings.

## Team
Liyue Housing Association: Mukul and Karthik.

## Run locally
Works with no API key. Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080. Health check: http://localhost:8080/api/health (use `/api/health` on Cloud Run, which reserves paths ending in "z" such as `/healthz`).

Optional live extraction: copy `.env.example` to `.env` and set `GEMINI_API_KEY`. `GEMINI_MODEL` picks the model (default `gemini-3.5-flash`). If it is busy or times out, one retry goes to `GEMINI_FALLBACK_MODEL` (default `gemini-flash-lite-latest`). Without a key, or if a live call fails, the page shows saved sample output and says so.

## Test
```bash
python -m unittest discover -s tests -t .   # all tests
python -m app.ledger                        # check every quote against its cited page
python evals/run_evals.py                   # live model cases, needs GEMINI_API_KEY
```

## What the demo shows
The packet in `data/demo/` is made up: the fictional city of Lantern Bay and the fictional Harbor Walk project. It has a staff summary, draft letter, developer slides, minutes and a later letter.

Pages (hash routes):
- **Home `#/`:** what Promise Ledger is, a sample receipt, and the "Learn in 60 seconds" explainers.
- **Deals `#/deals`:** every deal with its documents, furthest stage, flags and next reminder, plus a reminders panel and a New deal dialog.
- **Deal `#/deals/{id}`:** at a glance, key figures, stages, documents with drag-and-drop PDF upload, and tabs for Claims, What changed, Open questions, Receipt, Read new text and Glossary. "View source" opens the real PDF page with the quote highlighted. If the quote cannot be matched on the page, the page text is shown with the quote marked. Export to Excel or CSV, or share a read-only link.
- **Shared receipt `#/r/{token}`:** a read-only receipt that prints cleanly.

Notes for the interface (`app/static/`):
- No framework. `pdfview.js` loads pdf.js (pinned, from jsDelivr) only when a source is opened.
- Until the deals API answers, the page uses `mock.js`, an in-browser copy of the API with made-up deals. Add `?mock=1` to the address to force it.
- Explainer videos are `NN-slug.mp4`, `.vtt` and `.jpg`. Set `MEDIA_BASE_URL` to a public folder (for example a Cloud Storage bucket, with CORS for GET so captions load). If it is empty, the page uses `app/static/media/`. `/api/media` reports which videos are present, and missing ones keep their placeholder.

## Sample deals (PDF)
`data/samples/` has three fictional deals as real PDF records, for the live demo and for tests of PDF reading. Every page carries the footer "SAMPLE DOCUMENT · fictional · for demonstration". Names are generic roles only, and the compliance certificate has counts and dates only.

| Deal | Homes | Records | What it shows |
|---|---|---|---|
| `harbor-walk` | 120 | staff summary (2 p), draft letter (1), developer slides (3), minutes (2), developer letter (1) | The demo story above, with the same quotes and pages. Income basis and term differ; rent limits and remedies not located; signed by the developer only. |
| `beacon-point` | 80 | staff report (3), council resolution (2), PILOT and regulatory agreement signed by City and owner (4) | A complete deal: 16 homes at 60% AMI, HUD-based rent limits, 30 years, owner and later owners, yearly report, payback of abated taxes after default notice. All terms match. |
| `mill-street` | 60 | 2011 regulatory agreement excerpt (3), 2024 compliance certificate (1), 2026 staff memo (2) | After signing: 9 homes at 50% AMI until 2026-12-31, and the 2025 certificate marked not received. |

Each folder has `manifest.json` (file, type, date, title, pages, signed_by) and `expected_claims.json` (gold answers: every promise with term, exact quote, file, page and stage, plus `not_located` and `differs`; Mill Street also has `observations` and `follow_up`).

```bash
pip install reportlab pypdf
python tools/make_samples.py                  # rebuild data/samples/ (deterministic)
python -m unittest tests.test_samples         # every gold quote is on its stated page
```

Quote checks read each page with pypdf and treat line breaks as spaces (about half the quotes wrap across a line). Nothing else is normalized: the PDFs use standard fonts with no hyphenation or ligatures.

## Deals and PDF uploads
Staff create a deal, upload its PDFs, and get a checked review for that deal. On an empty store the app seeds the sample deals above (or the Harbor Walk demo when `data/samples/` is missing).

Each PDF goes through `app/pipeline.py`:
1. The file is stored. Limits: 20 MB, 60 pages, no password.
2. pypdf extracts text per page. Pages with no text layer are flagged as scanned and listed as open questions.
3. The model gets the redacted page text, tagged `<page n="1">…`, and returns candidate quotes with term, page, document type and named signers.
4. Code checks every quote against the page text (whitespace, quote marks and dashes normalized). A quote found on another page gets its page corrected; a quote found nowhere is dropped. Counts are kept per document.
5. Code rules set the stage, never the model alone: staff reports, slides and unsigned letters are *proposed* (a staff recommendation is *supported*); minutes and resolutions with a recorded vote or approval are *supported*; an agreement or letter is *signed* only when code finds a completed signature line under the party's name and the record is not marked draft; certificates with occupancy or certification wording are *delivered*.
6. The deal review is rebuilt from the verified claims. It has the same shape as `/api/review`.

Code also sets aside candidates that do not state the term they are filed under. Each term needs its own words, for example a home count with "affordable" or "reserved" for units, or "default", "cure" or "repay" for remedies. Code also drops headers, footers and sentences that describe the record itself, sentences saying a term is missing, and the same sentence filed under a second term. Each document's `counts` shows how many were set aside and why. "Wording differs" compares values that code reads from the quote: the home count and whether it is a flat number, a cap ("up to 12") or a share ("10 percent of 120"), years or end date, percent, report due date and cure days.

Each sample manifest has an `as_of` date (its latest record), and that deal's reminders are computed as of that date, so they read the same on any day.

Readings are cached in `data/readings/` by file hash and prompt version, so seeding and evals do not call the model again. Reminders (`/api/reminders`) come from signed term and reporting clauses and the certificates on file.

API: `GET/POST /api/deals`, `GET /api/deals/{id}`, `POST /api/deals/{id}/documents` (multipart, 202, poll the deal), `GET /api/deals/{id}/review`, `GET …/documents/{doc}/file`, `GET …/documents/{doc}/pages/{n}`, `GET /api/deals/{id}/export.xlsx` and `export.csv`, `POST /api/deals/{id}/share` → `/r/{token}`, and `GET /api/reminders`.

Storage: `STORAGE=local` (default; JSON and files under `data/runtime/`) or `STORAGE=gcp` (Firestore Native for records, Cloud Storage bucket `GCS_BUCKET` for PDFs; optional `FIRESTORE_DATABASE`). Uploads are read on a background thread, so on Cloud Run deploy with `--no-cpu-throttling`. Also set `PUBLIC_BASE_URL` to give share links the public host.

```bash
python evals/run_pdf_evals.py              # score the pipeline on data/samples/ (cached; at most 30 live calls)
```

## How the work is split
AI reads, code checks, humans decide.

- The model finds candidate quotes in pasted text or uploaded PDFs. It never sets a status.
- Code checks that quotes match their source word for word, that dates match, and that the arithmetic adds up. A quote that does not match is dropped.
- Stages for uploaded records come from code rules on the document type and checked signatures. Every claim stays flagged for human review. Claims in `data/demo/claims.json` were reviewed by hand.
- Pasted text is not stored or logged. Obvious personal details are removed before the model call.

## Docs
- [Plan](docs/PLAN.md)
- [Contributor rules](AGENTS.md)

## License
Code: Apache-2.0. Docs and evaluation data: CC-BY 4.0.
