# Promise Ledger

Source-linked receipts for public housing deals.

When a housing project asks for public support, its affordability terms get spread across staff reports, letters, slides and minutes. Promise Ledger turns those records into one review page: how many homes, for whom, for how long, and where the evidence is.

**Status:** early prototype for GDG AI for Good 2026: Housing. The demo uses a made-up packet. Nothing here makes legal findings.

## Team
Liyue Housing Association: Mukul and Karthik.

## Run locally
```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add GEMINI_API_KEY
uvicorn app.main:app --reload --port 8080
```

## Docs
- [Plan](docs/PLAN.md)
- [Contributor rules](AGENTS.md)

## License
Code: Apache-2.0. Docs and evaluation data: CC-BY 4.0.
