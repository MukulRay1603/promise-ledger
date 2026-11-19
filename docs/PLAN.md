# Roadmap

Promise Ledger turns the records of a housing deal into one checked receipt: AI reads, code checks, people decide.

## Done for the Nov 9 submission
- Live on Cloud Run with three made-up sample deals as real PDFs, plus the hand-reviewed Harbor Walk packet.
- PDF upload: pypdf text, Gemini structured reading, every quote checked against its page, stages set by code rules.
- Per-deal review: claims, what changed, open questions, receipt, reminders, Excel/CSV export, read-only share links.
- Reviewer decisions (confirm, follow up, dispute) beside the record; sample deals keep each browser's review apart.
- Public demo guard: rate limits, session-owned visitor deals, uploads deleted after 24 hours, security headers.

## Done for the Dec 2 final (branch `dec2`)
- Real records: every Prince George's County PILOT agreement since 2023 (21 deals, 156 council records) from the
  Council's Legistar API, read once and shown on a County page with search by meaning.
- Higher recall on real and held-out records; scanned pages transcribed; Ask a deal from checked quotes.
- Records-request letters, calendar export with term heads-ups, flags for unfilled template text.
- All 8 planted attacks held; private names and addresses in labelled fields redacted; scans kept from the model in
  staff deployments.
- Evidence: held-out, adversarial and real-record evals; axe-core accessibility results; self-host guide.

## Before Dec 2
- Deploy `dec2` (with a warm instance so the first visit is fast).
- People test it: a timed task by hand and with the tool, and their feedback.
- A new short video.

## Later
- Real sign-in for staff, replacing the browser session (`app/identity.py` is the seam).
- A second county, Spanish, and a full screen-reader pass with the people who use one.
