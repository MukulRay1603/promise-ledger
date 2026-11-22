"""Self-healing: a watchdog that finds the problems we know can happen and repairs what it safely can.

Every HEAL_INTERVAL_SECONDS (default 300; 0 turns it off) it checks:
- Documents stuck in reading (an instance died mid-read): queued again, at most HEAL_MAX_RETRIES times each; after that
  the document is marked failed with a plain message, so it never loops and a person can press Retry.
- The real county agreements went missing from storage (a wiped or new database): seeded again from data/county.
- The search index did not load: loaded again; until then search answers by keywords.
- Storage answers at all, and how long it takes.
It also reports what the other safety nets are doing: the model breaker (main model resting after it was busy), storage
retries, and cached answers. /api/health?deep=1 shows the latest report. Nothing here calls the model or spends money.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

HEAL_INTERVAL_SECONDS = int(os.getenv("HEAL_INTERVAL_SECONDS") or 300)
HEAL_MAX_RETRIES = int(os.getenv("HEAL_MAX_RETRIES") or 3)

_status: dict = {"runs": 0, "last_run": None, "checks": {}, "repairs": []}
_lock = threading.Lock()
_thread: threading.Thread | None = None
_reloaded_at: dict[str, float] = {}  # agreement -> when the watchdog last reloaded it
_last_record_scan = -1e9


def _note(repair: str) -> None:
    _status["repairs"] = ([{"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "what": repair}]
                          + _status["repairs"])[:20]


def heal_stuck_documents(store, all_deals: list[dict] | None = None) -> dict:
    """Only visitor and staff deals can stall: sample and county deals are seeded from saved readings, and the seed
    itself re-checks them. Skipping them keeps a pass to a few storage reads, well inside Firestore's free tier."""
    from app import deals
    requeued = failed = 0
    for deal in (all_deals if all_deals is not None else store.list_deals()):
        if deal.get("real") or deals.is_sample(deal):
            continue
        for doc in store.list_documents(deal["id"]):
            if not deals.is_stale(doc):
                continue
            tries = int(doc.get("auto_retries") or 0)
            if tries >= HEAL_MAX_RETRIES:
                deals._set(store, deal["id"], doc, status="failed",
                           error=f"Stopped after {tries} automatic tries. Press Retry to read it again.")
                failed += 1
                _note(f"Stopped retrying a document in {deal['id']} after {tries} tries")
                continue
            doc = deals._set(store, deal["id"], doc, status="queued", error=None, auto_retries=tries + 1)
            deals.submit(deal["id"], doc["id"], store)
            requeued += 1
            _note(f"Queued a stuck document in {deal['id']} again (try {tries + 1})")
    return {"ok": True, "requeued": requeued, "stopped": failed}


def heal_county_data(store, all_deals: list[dict] | None = None) -> dict:
    from app import deals
    if os.getenv("COUNTY_DEALS", "1") == "0" or not deals.COUNTY_DIR.is_dir():
        return {"ok": True, "skipped": True}
    expected = sum(1 for p in deals.COUNTY_DIR.glob("*/manifest.json"))
    present = sum(1 for d in (all_deals if all_deals is not None else store.list_deals()) if d.get("real"))
    if expected and present == 0:
        seeded = deals.seed(store)
        _note(f"County agreements were missing; seeded {len(seeded)} again")
        return {"ok": True, "expected": expected, "present": present, "reseeded": len(seeded)}
    # An agreement can come up short when a record could not be fetched during a deploy (the county's server was
    # slow or busy). Reload just that agreement: free (saved readings only), at most once an hour each.
    short, reloaded = [], []
    global _last_record_scan
    if time.monotonic() - _last_record_scan < 3600:  # an hourly scan keeps Firestore reads inside the free tier
        return {"ok": present >= expected, "expected": expected, "present": present, "records": "checked hourly"}
    _last_record_scan = time.monotonic()
    for manifest_path in sorted(deals.COUNTY_DIR.glob("*/manifest.json")):
        manifest = deals._manifest(manifest_path) or {}
        slug = deals.sample_slug(manifest, manifest_path.parent)
        want = len(manifest.get("documents") or [])
        have = len(store.list_documents(slug))
        if have >= want:
            continue
        short.append(f"{slug}: {have} of {want}")
        if time.monotonic() - _reloaded_at.get(slug, -1e9) < 3600:
            continue
        _reloaded_at[slug] = time.monotonic()
        deals.seed_sample(manifest_path, store)
        after = len(store.list_documents(slug))
        reloaded.append(slug)
        _note(f"{slug} had {have} of {want} records; reloaded, now {after}")
    return {"ok": present >= expected and not short, "expected": expected, "present": present,
            "short": short, "reloaded": reloaded}


def heal_search_index() -> dict:
    from app import search
    data = search.load_index()
    if not data.get("items") and search.INDEX.is_file():
        search.load_index.cache_clear()
        data = search.load_index()
        _note("Search index reloaded")
    return {"ok": bool(data.get("items")), "quotes": len(data.get("items") or [])}


def check_storage(store) -> tuple[dict, list[dict]]:
    started = time.monotonic()
    listed = store.list_deals()
    return {"ok": True, "deals": len(listed), "ms": round((time.monotonic() - started) * 1000)}, listed


def run_once(store=None) -> dict:
    """One pass of every check. Each check is isolated: one failing does not stop the others."""
    from app import ai, ask, storage
    store = store or storage.get_store()
    checks = {}
    listed = None  # One listing of deals serves every check, so a pass costs few storage reads.
    try:
        checks["storage"], listed = check_storage(store)
    except Exception as err:
        checks["storage"] = {"ok": False, "error": type(err).__name__}
    for name, fn in (("stuck_documents", lambda: heal_stuck_documents(store, listed)),
                     ("county_data", lambda: heal_county_data(store, listed)), ("search_index", heal_search_index)):
        try:
            checks[name] = fn()
        except Exception as err:  # Reported, never raised: the watchdog must keep running.
            checks[name] = {"ok": False, "error": type(err).__name__}
    resting = max(0.0, ai._main_resting_until - time.monotonic())
    checks["model"] = {"ok": True, "key": bool(os.getenv("GEMINI_API_KEY")), "main_resting_seconds": round(resting),
                       "answer_model": ask.ask_model()}
    checks["storage_retries"] = dict(storage.storage_stats)
    checks["answer_cache"] = {"entries": len(ask.CACHE._items)}
    checks["ai_answers"] = {"ok": True, "paused_for_today": not ask.budget_ok()}  # no amounts in a public report
    with _lock:
        _status["runs"] += 1
        _status["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _status["checks"] = checks
    return checks


def status() -> dict:
    with _lock:
        healthy = all(c.get("ok", True) for c in _status["checks"].values())
        return {"ok": healthy, "interval_seconds": HEAL_INTERVAL_SECONDS, **_status}


def start() -> None:
    """Start the watchdog once per process. Its first pass waits one interval, after the startup seed has run."""
    global _thread
    if HEAL_INTERVAL_SECONDS <= 0 or (_thread and _thread.is_alive()):
        return

    def loop():
        wait = min(60, HEAL_INTERVAL_SECONDS)  # the first pass soon after start, then every interval
        while True:
            time.sleep(wait)
            wait = HEAL_INTERVAL_SECONDS
            try:
                run_once()
            except Exception as err:
                print(f"Watchdog pass failed: {type(err).__name__}")

    _thread = threading.Thread(target=loop, name="watchdog", daemon=True)
    _thread.start()
