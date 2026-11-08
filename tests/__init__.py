import os

# The public-demo guard (rate limits, expiry) is off for the suite; tests/test_guard.py turns it on.
os.environ.setdefault("DEMO_MODE", "0")
# PDFs are parsed in-process in tests; tests/test_hardening.py checks the child-process sandbox.
os.environ.setdefault("PDF_SANDBOX", "0")
