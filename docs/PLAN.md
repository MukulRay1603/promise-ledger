# Roadmap

Promise Ledger turns the records of a housing deal into one checked receipt: AI reads, code checks, people decide.

## Done (Nov 2026)
- Live on Cloud Run with three made-up sample deals as real PDFs, plus the hand-reviewed Harbor Walk packet.
- PDF upload: pypdf text, Gemini structured reading, every quote checked against its page, stages set by code rules.
- Per-deal review: claims, what changed, open questions, receipt, reminders, Excel/CSV export, read-only share links.
- Reviewer decisions (confirm, follow up, dispute) beside the record; sample deals keep each browser's review apart.
- Public demo guard: rate limits, session-owned visitor deals, uploads deleted after 24 hours, security headers.
- Evals on the sample deals with gold answers (`python evals/run_pdf_evals.py`).

## Next
- **Nov 9:** Coding Jam submission (live URL, repo, short pitch).
- **Before Dec 2:** tighter stage rules (signatures, votes, certificates), number parsing, steadier sample refresh,
  retry for failed uploads, and the reminder countdown measured from each deal's own date.
- **Dec 2:** demo and judging at the Chesapeake Innovation Summit.

## Later
- Real sign-in for staff, replacing the browser session (`app/identity.py` is the seam).
- More deal types and a few more labeled cases for the evals.
- A staff deployment with `DEMO_MODE=0`: shared deals, no expiry.
- One real staff user trying a real task, and a full accessibility pass with assistive tech.
