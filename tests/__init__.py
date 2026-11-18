import os

# The public-demo guard (rate limits, expiry) is off for the suite; tests/test_guard.py turns it on.
os.environ.setdefault("DEMO_MODE", "0")
# With DEMO_MODE off, scanned pages are not sent to the model unless this is set. The scan tests use a stub model;
# tests/test_injection_privacy.py checks the default itself.
os.environ.setdefault("SCANS_TO_MODEL", "1")
# PDFs are parsed in-process in tests; tests/test_hardening.py checks the child-process sandbox.
os.environ.setdefault("PDF_SANDBOX", "0")
