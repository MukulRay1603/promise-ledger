"""Public demo guard: per-IP rate limits on uploads and new deals, and expiry of visitor deals.

DEMO_MODE=1 (default) turns both on. A staff deployment sets DEMO_MODE=0.

- Rate limits (uploads, new deals, and reviewer decisions) share one in-memory sliding window per instance. With at most 2 Cloud Run instances a visitor
  gets at most twice the limit, which is fine for a soft limit.
- Deals and uploads made while DEMO_MODE is on are marked demo=True. The sweep deletes demo deals older
  than DEMO_TTL_HOURS, and demo uploads on the sample deals, and never the sample deals themselves.
  Non-sample deals from before the flag existed (no "demo" key) are swept too, as a one-time migration.
- Client IP is the last X-Forwarded-For hop: Cloud Run appends it, so a client cannot spoof it. This holds only
  when the service sits directly behind Cloud Run's front end; behind another proxy or load balancer, the client
  moves one hop left. IPv6 clients are counted per /64 network, since one host usually owns the whole /64.
- SecurityHeaders adds CSP, nosniff, Referrer-Policy and frame blocking to every response, and Cache-Control to
  static files. Uploads with a Content-Length over the limit are refused before the body is read.
"""
from __future__ import annotations

import ipaddress
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


def rate_key(ip: str) -> str:
    """The key an address is counted under: the address itself, or its /64 network for IPv6 (S5)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


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


# Reviewer decisions: 60 a minute per demo session (or IP), and 300 a minute per network, so a client cannot
# get more by making up new session ids (S5). Always on, demo or not.
decision_limit = RateLimit(limit=60, window_seconds=60)
decision_ip_limit = RateLimit(limit=300, window_seconds=60)


def allow_decision(request, session: str | None) -> bool:
    key = rate_key(client_ip(request))
    return decision_ip_limit.allow(key) and decision_limit.allow(f"{key}|{session}" if session else key)

WINDOW_SECONDS = 3600

# (name, method, path pattern, env var, default per hour, what the message calls it)
RULES = [
    ("upload", "POST", re.compile(r"^/api/deals/[^/]+/documents/?$"), "RATE_LIMIT_UPLOADS_PER_HOUR", 5, "uploads"),
    ("deal", "POST", re.compile(r"^/api/deals/?$"), "RATE_LIMIT_DEALS_PER_HOUR", 3, "new deals"),
    ("share", "POST", re.compile(r"^/api/deals/[^/]+/share/?$"), "RATE_LIMIT_SHARES_PER_HOUR", 20, "share links"),
    ("extract", "POST", re.compile(r"^/api/extract/?$"), "RATE_LIMIT_EXTRACTS_PER_HOUR", 30, "text readings"),
    ("ask", "POST", re.compile(r"^/api/deals/[^/]+/ask/?$"), "RATE_LIMIT_ASKS_PER_HOUR", 30, "questions"),
    ("retry", "POST", re.compile(r"^/api/deals/[^/]+/documents/[^/]+/retry/?$"), "RATE_LIMIT_RETRIES_PER_HOUR", 10,
     "retries"),
    ("export", "GET", re.compile(r"^/api/deals/[^/]+/export\.(xlsx|csv|json)$"), "RATE_LIMIT_EXPORTS_PER_HOUR", 120,
     "exports"),
]
limits = {name: RateLimit(default, WINDOW_SECONDS) for name, _m, _p, _e, default, _l in RULES}


def reset_limits() -> None:
    for limit in (*limits.values(), decision_limit, decision_ip_limit):
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

def _stamp(value) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _created(record: dict) -> datetime | None:
    return _stamp(record.get("created_at"))


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
    removed = {"deals": [], "documents": [], "decisions": 0}
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
                # Each browser's review of a sample deal is kept as long as an upload (P2).
                for event in store.list_decisions(deal["id"]):
                    at = _stamp(event.get("at"))
                    if at and at < cutoff:
                        store.delete_decision(deal["id"], event["id"])
                        removed["decisions"] += 1
            elif is_expired_visitor_deal(deal) and created and created < cutoff:
                store.delete_deal(deal["id"])
                removed["deals"].append(deal["id"])
    finally:
        store.release_lock(SWEEP_LOCK, owner)
    if removed["deals"] or removed["documents"] or removed["decisions"]:
        print(f"Demo sweep removed {len(removed['deals'])} deals, {len(removed['documents'])} uploads "
              f"and {removed['decisions']} sample-deal decisions.")
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
    """Rate-limits uploads, new deals, shares, text readings and exports; starts the hourly sweep; marks X-Demo-Mode."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled():
            return await self.app(scope, receive, send)
        maybe_sweep()
        from starlette.requests import HTTPConnection

        blocked = check(scope["method"], scope["path"], rate_key(client_ip(HTTPConnection(scope))))
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


UPLOAD_PATH = re.compile(r"^/api/deals/[^/]+/documents/?$")
MAX_UPLOAD_BODY = 20 * 1024 * 1024 + 256 * 1024  # The PDF limit plus room for the multipart form fields.


def _origin(url: str) -> str:
    m = re.match(r"^(https?://[^/]+)", (url or "").strip())
    return m.group(1) if m else ""


def content_security_policy() -> str:
    """Scripts only from this site. Videos and their posters may come from the MEDIA_BASE_URL host (S7)."""
    media = " ".join(dict.fromkeys(filter(None, ["https://storage.googleapis.com", _origin(os.getenv("MEDIA_BASE_URL", ""))])))
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        # Inline style attributes are used for widths and positions set from script; no inline scripts are.
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        f"img-src 'self' data: blob: {media}",
        f"media-src 'self' {media}",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        # The overview video plays in YouTube's privacy-enhanced player, loaded only when pressed.
        "frame-src https://www.youtube-nocookie.com",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ])


def cache_control(path: str) -> str | None:
    """Static files: versioned vendor files are immutable; videos keep a day; app code always revalidates (P8)."""
    if not path.startswith("/static/"):
        return None
    if path.startswith("/static/vendor/"):
        return "public, max-age=31536000, immutable"
    if path.startswith("/static/media/") and not path.endswith(".json"):
        return "public, max-age=86400"
    return "no-cache"  # The ETag still lets the browser reuse an unchanged file with a 304.


MAX_JSON_BODY = 64 * 1024  # Every JSON request is small; the largest is pasted text of 4,000 characters.


class BodyTooLarge(Exception):
    pass


def _capped(receive, limit: int):
    seen = 0

    async def wrapped():
        nonlocal seen
        message = await receive()
        seen += len(message.get("body", b""))
        if seen > limit:
            raise BodyTooLarge()
        return message
    return wrapped


class SecurityHeaders:
    """Headers on every response, and an early 413 for uploads whose Content-Length is over the limit (S11)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["method"] in ("POST", "PUT", "PATCH", "DELETE") and scope["path"].startswith("/api/"):
            from fastapi.responses import JSONResponse

            headers = dict(scope.get("headers") or [])
            length = headers.get(b"content-length", b"")
            upload = UPLOAD_PATH.match(scope["path"])
            limit = MAX_UPLOAD_BODY if upload else MAX_JSON_BODY
            if length.isdigit() and int(length) > limit:
                detail = "The file is larger than 20 MB." if upload else "The request is too large."
                return await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
            if not upload and not length.isdigit() and b"chunked" in headers.get(b"transfer-encoding", b""):
                # No length to check up front: count the bytes as they arrive and stop past the limit.
                receive = _capped(receive, limit)
        csp = content_security_policy()
        cache = cache_control(scope["path"])

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _v in headers}
                extra = [(b"content-security-policy", csp.encode()), (b"x-content-type-options", b"nosniff"),
                         (b"referrer-policy", b"strict-origin-when-cross-origin"), (b"x-frame-options", b"DENY"),
                         (b"permissions-policy", b"camera=(), microphone=(self), geolocation=()"),
                         (b"strict-transport-security", b"max-age=31536000; includeSubDomains")]
                if cache:
                    extra.append((b"cache-control", cache.encode()))
                message["headers"] = headers + [(k, v) for k, v in extra if k not in present]
            await send(message)

        return await self.app(scope, receive, send_with_headers)


def install(app) -> None:
    app.add_middleware(GuardMiddleware)
    app.add_middleware(SecurityHeaders)  # Added last, so it runs first.
