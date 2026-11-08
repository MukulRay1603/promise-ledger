import os

# The public-demo guard (rate limits, expiry) is off for the suite; tests/test_guard.py turns it on.
os.environ.setdefault("DEMO_MODE", "0")
