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
.venv\Scriptsctivate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080.

Optional live extraction: copy `.env.example` to `.env` and set `GEMINI_API_KEY`. `GEMINI_MODEL` picks the model. Without a key, or if a live call fails, the page shows saved sample output and says so.

## Test
```bash
python -m unittest discover -s tests -t .   # all tests
python -m app.ledger                        # check every quote against its cited page
python evals/run_evals.py                   # live model cases, needs GEMINI_API_KEY
```

## What the demo shows
The packet in `data/demo/` is made up: the fictional city of Lantern Bay and the fictional Harbor Walk project. It has a staff summary, draft letter, developer slides, minutes and a later letter.

- **Claims:** exact quotes with document type, date, page, topic and status. Select one to see its source page with the quote highlighted.
- **What was approved?:** proposed, supported, signed and delivered, kept separate.
- **Terms checklist:** units, income basis, rent limits, term, responsible party, reporting and remedies, with "Not located" where absent.
- **Promise Receipt:** a one-page printable summary with a line for the human reviewer.
- **Read new text:** bounded extraction from a small pasted text.

## How the work is split
AI reads, code checks, humans decide.

- The model finds candidate quotes in up to 4,000 characters of pasted text. It never sets a status.
- Code checks that quotes match their source word for word, that dates match, and that the arithmetic adds up. A quote that does not match is dropped.
- A person sets every status. Claims in `data/demo/claims.json` were reviewed by hand.
- Pasted text is not stored or logged. Obvious personal details are removed before the model call.

## Docs
- [Plan](docs/PLAN.md)
- [Contributor rules](AGENTS.md)

## License
Code: Apache-2.0. Docs and evaluation data: CC-BY 4.0.
