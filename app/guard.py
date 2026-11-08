"""Public demo guard: per-IP rate limits on uploads and new deals, and expiry of visitor deals.

DEMO_MODE=1 (default) turns both on. A staff deployment sets DEMO_MODE=0.

- Rate limits (uploads, new deals, and reviewer decisions) share one in-memory sliding window per instance. With at most 2 Cloud Run instances a visitor
  gets at most twice the limit, which is fine for a soft limit.
- Deals and uploads made while DEMO_MODE is on are marked demo=True. The sweep deletes demo deals older
  than DEMO_TTL_HOURS, and demo uploads on the sample deals, and never the sample deals themselves.
  Non-sample deals from before the flag existed (no "demo" key) are swept too, as a one-time migration.
- Client IP is the last X-Forwarded-For hop: Cloud Run appends it, so a client cannot spoof it.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from app.storage import Storage, get_store

SWEEP_LOCK = "demo-sweep"
SWEEP_LOCK_TTL = 600  # Seconds before a lock left by a crashed instance is ignored.
SWEEP_EVERY = 3600  # Seconds between sweeps on one instance.


def enabled() -> bool:
    return os.getenv("DEMO_MODE", "1").strip().lower() not in ("0", "false", "off", "no")


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "")))
    except ValueError:
        return default


def ttl_hours() -> int:
    return _int_env("DEMO_TTL_HOURS", 24) or 24


# ---------------------------------------------------------------------------
# Rate limits: the one sliding-window limiter and client-IP helper in the app

def client_ip(request) -> str:
    """The visitor's IP: the LAST X-Forwarded-For hop, else the socket peer.

    Cloud Run's front end appends the address it saw to whatever X-Forwarded-For the client sent, so earlier
    hops are client-controlled and only the last one can be trusted. Takes a Request or HTTPConnection.
    """
    hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
    if hops:
        return hops[-1]
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


class RateLimit:
    """A small sliding-window limit per key, in memory. Enough to stop a public demo being flooded.

    Counts are per instance; with at most 2 Cloud Run instances a visitor gets at most twice the limit.
    """

    MAX_KEYS = 10000

    def __init__(self, limit: int, window_seconds: float):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def wait(self, key: str, now: float | None = None) -> float:
        """Record a hit and return 0, or return the seconds until the next hit is allowed (nothing recorded)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1.0, hits[0] + self.window - now) if hits else self.window
            hits.append(now)
            if len(self._hits) > self.MAX_KEYS:  # Forget idle keys so memory stays small.
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window][:5000]:
                    self._hits.pop(stale, None)
            return 0.0

    def allow(self, key: str, now: float | None = None) -> bool:
        return not self.wait(key, now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Reviewer decisions: 60 a minute per demo session (or IP). Always on, demo or not.
decision_limit = RateLimit(limit=60, window_seconds=60)

WINDOW_SECONDS = 3600

# (name, method, path pattern, env var, default per hour, what the message calls it)
RULES = [
    ("upload", "POST", re.compile(r"^/api/deals/[^/]+/documents/?$"), "RATE_LIMIT_UPLOADS_PER_HOUR", 5, "uploads"),
    ("deal", "POST", re.compile(r"^/api/deals/?$"), "RATE_LIMIT_DEALS_PER_HOUR", 3, "new deals"),
]
limits = {name: RateLimit(default, WINDOW_SECONDS) for name, _m, _p, _e, default, _l in RULES}


def reset_limits() -> None:
    for limit in limits.values():
        limit.reset()


def check(method: str, path: str, ip: str, now: float | None = None) -> dict | None:
    """None when allowed; otherwise the 429 body and the Retry-After seconds."""
    for name, rule_method, pattern, env, default, label in RULES:
        if method != rule_method or not pattern.match(path):
            continue
        limit = limits[name]
        limit.limit = _int_env(env, default)  # Read each time, so a changed env applies without a restart.
        wait = limit.wait(ip, now)
        if not wait:
            return None
        retry = math.ceil(wait)
        minutes = max(1, math.ceil(retry / 60))
        return {"retry_after": retry, "body": {
            "detail": (f"The public demo allows {limit.limit} {label} an hour from one network. "
                       f"Please try again in {minutes} minute{'s' if minutes != 1 else ''}."),
            "limit": limit.limit, "retry_after": retry}}
    return None


# ---------------------------------------------------------------------------
# Expiry of visitor deals

def _created(record: dict) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(record.get("created_at") or ""))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _protected_ids() -> set[str]:
    from app import deals  # deals imports this module.

    ids = {deals.DEMO_DEAL_ID}
    if deals.SAMPLES_DIR.exists():
        for path in deals.SAMPLES_DIR.glob("*/manifest.json"):
            ids.add(deals.sample_slug(deals._manifest(path) or {}, path.parent))
    return ids


def is_protected(deal: dict, protected: set[str]) -> bool:
    """Sample deals and the Harbor Walk demo are never deleted."""
    from app import deals

    return deals.is_sample(deal) or deal.get("id") in protected


def is_expired_visitor_deal(deal: dict) -> bool:
    """A demo deal, or (one-time migration) a deal from before demo flags existed: no "demo" key at all.

    Deals made since this change always carry demo true or false, so a staff deal (demo false) is never swept.
    """
    return deal.get("demo") is True or "demo" not in deal


def sweep(store: Storage | None = None, now: datetime | None = None, owner: str | None = None) -> dict:
    """Delete demo deals and demo uploads on sample deals older than DEMO_TTL_HOURS. Returns what was removed."""
    removed = {"deals": [], "documents": []}
    if not enabled():
        return removed
    store = store or get_store()
    owner = owner or uuid.uuid4().hex
    if not store.acquire_lock(SWEEP_LOCK, owner, SWEEP_LOCK_TTL):
        return removed  # Another instance is sweeping.
    try:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=ttl_hours())
        protected = _protected_ids()
        for deal in store.list_deals():
            created = _created(deal)
            if is_protected(deal, protected):
                for doc in store.list_documents(deal["id"]):
                    doc_created = _created(doc)
                    if doc.get("demo") is True and doc_created and doc_created < cutoff:
                        store.delete_document(deal["id"], doc["id"])
                        removed["documents"].append(f"{deal['id']}/{doc['id']}")
            elif is_expired_visitor_deal(deal) and created and created < cutoff:
                store.delete_deal(deal["id"])
                removed["deals"].append(deal["id"])
    finally:
        store.release_lock(SWEEP_LOCK, owner)
    if removed["deals"] or removed["documents"]:
        print(f"Demo sweep removed {len(removed['deals'])} deals and {len(removed['documents'])} uploads.")
    return removed


_last_sweep = 0.0  # Monotonic time of this instance's last sweep; 0 means the first request sweeps.
_sweep_lock = threading.Lock()


def maybe_sweep(background: bool = True) -> bool:
    """Start a sweep if this instance has not run one in the last hour. Returns True if one was started."""
    global _last_sweep
    with _sweep_lock:
        if _last_sweep and time.monotonic() - _last_sweep < SWEEP_EVERY:
            return False
        _last_sweep = time.monotonic()

    def run():
        try:
            sweep()
        except Exception as err:  # A storage problem must not break requests.
            print(f"Demo sweep skipped: {type(err).__name__}: {err}")

    if background:
        threading.Thread(target=run, name="demo-sweep", daemon=True).start()
    else:
        run()
    return True


# ---------------------------------------------------------------------------
# ASGI middleware

class GuardMiddleware:
    """Rate-limits the two write routes, starts the hourly sweep, and marks responses with X-Demo-Mode."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled():
            return await self.app(scope, receive, send)
        maybe_sweep()
        from starlette.requests import HTTPConnection

        blocked = check(scope["method"], scope["path"], client_ip(HTTPConnection(scope)))
        if blocked:
            from fastapi.responses import JSONResponse

            response = JSONResponse(blocked["body"], status_code=429,
                                    headers={"Retry-After": str(blocked["retry_after"]), "X-Demo-Mode": "1"})
            return await response(scope, receive, send)

        async def send_marked(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-demo-mode", b"1")]
            await send(message)

        return await self.app(scope, receive, send_marked)


def install(app) -> None:
    app.add_middleware(GuardMiddleware)
