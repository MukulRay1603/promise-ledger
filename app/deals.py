"""Deals and their documents: upload, background reading, per-deal review, reminders, export."""
from __future__ import annotations

import calendar
import csv
import io
import hashlib
import json
import os
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import guard, ledger, pipeline, vision
from app.storage import Storage, get_store

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"
# Real public records (tools/county_import.py). Each manifest entry keeps the official URL and SHA-256; PDFs that
# are not committed are downloaded and checked when the deal is seeded.
COUNTY_DIR = ROOT / "data" / "county"
STATUSES = ("queued", "reading", "checking", "done", "failed")
DEMO_DEAL_ID = "harbor-walk-demo"

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reader")
run_inline = False  # Tests set this to process uploads synchronously.


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def display_date(value) -> str:
    """Dates in display text read "Nov 8, 2026" (W20). ISO stays in data fields and data cells."""
    d = date.fromisoformat(value[:10]) if isinstance(value, str) else value
    return f"{d:%b} {d.day}, {d.year}"


STALE_SECONDS = 300  # A document still reading after this long is treated as stuck (L12).


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "deal"


# ---------------------------------------------------------------------------
# Deals

def create_deal(name: str, city: str, developer: str | None = None, deal_id: str | None = None,
                store: Storage | None = None, as_of: str | None = None, demo: bool | None = None,
                owner_session: str | None = None) -> dict:
    """demo defaults to on for visitor deals (no fixed id) while DEMO_MODE is on; the sweep expires those.

    owner_session is the creating browser's demo session. In DEMO_MODE only that browser can see the deal.
    """
    store = store or get_store()
    if demo is None:
        demo = deal_id is None and guard.enabled()
    deal_id = deal_id or f"{_slug(name)}-{uuid.uuid4().hex[:6]}"
    stamp = now()
    deal = {"id": deal_id, "name": name.strip(), "city": city.strip(), "developer": (developer or "").strip() or None,
            "created_at": stamp, "updated_at": stamp}
    deal["demo"] = bool(demo)  # Always stored: a deal with no flag predates it, and the demo sweep treats it as a visitor's.
    if owner_session:
        deal["owner_session"] = owner_session  # Never returned by the API (see public_deal).
    if as_of:
        deal["as_of"] = date.fromisoformat(as_of).isoformat()  # Reminders are computed as of this date.
    store.put_deal(deal)
    return deal


PRIVATE_DEAL_FIELDS = ("owner_session",)


def public_deal(deal: dict) -> dict:
    """A deal as the API returns it: without the owner's session id (S3)."""
    return {k: v for k, v in deal.items() if k not in PRIVATE_DEAL_FIELDS}


def visible_to(deal: dict, session: str | None) -> bool:
    """Who may see and change a deal (S2). Sample deals are public; in DEMO_MODE a visitor deal belongs to the
    browser that made it. With DEMO_MODE off (a staff deployment) every deal is shared."""
    if not guard.enabled() or is_sample(deal):
        return True
    owner = deal.get("owner_session")
    return bool(owner) and owner == session


def touch(deal_id: str, store: Storage) -> None:
    deal = store.get_deal(deal_id)
    if deal:
        deal["updated_at"] = now()
        store.put_deal(deal)


PUBLIC_DOC_FIELDS = ("id", "filename", "type", "type_key", "date", "date_note", "title", "pages", "status", "error",
                     "scanned_pages", "transcribed_pages", "stage", "stage_reason", "signed", "signed_by", "counts", "model",
                     "from_cache", "tokens_in", "tokens_out", "cost_usd", "created_at", "updated_at")


def public_doc(doc: dict) -> dict:
    out = {k: doc.get(k) for k in PUBLIC_DOC_FIELDS}
    out["claim_count"] = len(doc.get("claims") or [])
    return out


def _sort_docs(docs: list[dict]) -> list[dict]:
    return sorted(docs, key=lambda d: (d.get("date") or "9999", d.get("created_at") or "", d["id"]))


def get_deal_detail(deal_id: str, store: Storage | None = None) -> dict | None:
    store = store or get_store()
    deal = store.get_deal(deal_id)
    if not deal:
        return None
    return {**public_deal(deal), "documents": [public_doc(d) for d in _sort_docs(store.list_documents(deal_id))]}


def _sort_reminders(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (not r["overdue"], r["date"]))


def list_deals(store: Storage | None = None, session: str | None = None) -> list[dict]:
    """The deals this browser may see, each with its next reminder. Each deal's documents are listed once (P5)."""
    store = store or get_store()
    rows = []
    for deal in store.list_deals():
        if not visible_to(deal, session):
            continue
        docs = store.list_documents(deal["id"])
        review = build_deal_review(deal, docs)
        summary = review["summary"]
        upcoming = _sort_reminders(deal_reminders(deal, docs))
        nxt = upcoming[0] if upcoming else None
        rows.append({
            "id": deal["id"],
            "name": deal["name"],
            "city": deal["city"],
            "documents": len(docs),
            "documents_processing": sum(d.get("status") in ("queued", "reading", "checking") for d in docs),
            "claim_count": len(review["claims"]),
            "furthest_status": summary["furthest_status"],
            "terms_differ": summary["terms_differ"],
            "terms_not_located": summary["terms_not_located"],
            "next_reminder": {"date": nxt["date"], "due": nxt["date"], "days": nxt["days"], "text": nxt["text"],
                              "kind": nxt["kind"], "claim_id": nxt["claim_id"]} if nxt else None,
            "updated_at": deal.get("updated_at"),
            "real": bool(deal.get("real")),
        })
    return sorted(rows, key=lambda r: r["updated_at"] or "", reverse=True)


# Terms a monitoring office needs on file for every deal (Lincoln Institute 2015 practitioner list; DC Auditor 2024).
OBLIGATION_TERMS = ("reporting", "remedies", "rent_limits", "income_basis", "term")
_TEMPLATE = re.compile(r"\(insert\b|\[insert\b|(?-i:\bOR \[)|\[(?:name|date|number|amount)\b|_{5,}", re.I)
_STATUTE = re.compile(r"governing body of|\(a\)\(\d\)|§|Tax[- ]Property Article|Section 7-50\d", re.I)
_YEAR_TERM = re.compile(r"\b(\d{1,2})[- ]year (?:term|affordability|compliance|restriction)", re.I)


# A record that corrects another states the corrected term after "but": "is listed as being for 99 years in
# Attachment B ..., but the Agreement's affordability period is for 40 years as confirmed by DHCD staff."
_CORRECTED_YEARS = re.compile(r"\bbut\b[^.;]*?\b(\d{1,2})\)?[- ]years?\b", re.I)


def _term_years(c: dict) -> int | None:
    fixed = _CORRECTED_YEARS.search(c["quote"])
    if fixed:
        return int(fixed.group(1))
    m = _YEAR_TERM.search(c["quote"])
    if m:
        return int(m.group(1))
    return (_years(c["value"]) or _years(c["quote"])) if c["topic"] == "term" else None


# "60% of AMI", "seventy percent (70%) or below of the Area Median Income", "70% or less than AMI".
_AMI = re.compile(r"(\d{2,3})\s*(?:%|percent)\)?\s+(?:or (?:less|below)\s+)?(?:(?:of|than)\s+)?(?:the\s+)?(?:area\s+)?"
                  r"(?:median|AMI\b)", re.I)
# A count the record gives only as a floor or an estimate: "over 100 affordable units".
_DESCRIPTIVE_AMI = re.compile(r"\b(average|median of residents|around|currently earn)\b[^.]{0,60}$", re.I)


def _ami_limits(quote: str) -> set[int]:
    """Shares of median income a quote states as a limit. "An average income of around 23% of AMI" describes
    today's residents, not a limit, and is left out."""
    return {int(m.group(1)) for m in _AMI.finditer(quote)
            if 10 <= int(m.group(1)) <= 150 and not _DESCRIPTIVE_AMI.search(quote[max(0, m.start() - 70):m.start()])}


_APPROX_COUNT = re.compile(r"\b(?:over|more than|at least|approximately|about|nearly|roughly|up to)\s+$", re.I)


# A count is taken as affordable homes only when the number sits right next to words that say so. In real county
# records one sentence often holds several counts ("Of the 158 units, 128 will be income-restricted, and 30 units
# will be market-rate"; "16 units will be designated for residents with mobility impairments"), so a looser reading
# picks the wrong one. Numbers may be written "thirty six (36)"; the digits are used.
# Most specific first: a count of the restricted homes out of a stated total ("57 of the 94 units", "restrict rents
# for fifty seven (57) of the units", "affordable housing for fifty seven (57) low-income households").
_RESTRICTED_COUNT = [
    re.compile(r"(\d[\d,]*)\)?\s+of\s+the\s+(?:[\w-]+\s+){0,3}?\(?\d[\d,]*\)?\s+(?:[\w-]+\s+)?units?\b", re.I),
    re.compile(r"affordable housing for\s+(?:[\w-]+\s+){0,3}?\(?(\d[\d,]*)\)?\s+(?:low|moderate|income|households|units|famil)", re.I),
    re.compile(r"restrict\s+(?:rents?|rent levels)\s+for\s+(?:[\w-]+\s+){0,3}?\(?(\d[\d,]*)\)?\s+(?:of|units|homes)", re.I),
    re.compile(r"(\d[\d,]*)\)?\s+(?:units?|homes?|apartments?)\s+(?:will|shall|are|to)\s+(?:be\s+)?"
               r"(?:income[- ]restricted|set[- ]aside|rent[- ]restricted|reserved for (?:families|households))\b", re.I),
]
_AFFORDABLE_COUNT = [
    re.compile(r"(\d[\d,]*)\)?\s+(?:new\s+)?(?:affordable|income[- ]restricted|rent[- ]restricted)\b", re.I),
    re.compile(r"(\d[\d,]*)\)?[- ]unit\s+(?:affordable|income[- ]restricted)", re.I),
    re.compile(r"(\d[\d,]*)\)?\s+(?:units?|homes?|apartments?)\s+(?:will|shall|are|to)\s+(?:be\s+)?"
               r"(?:income[- ]restricted|affordable|set[- ]aside|rent[- ]restricted)\b", re.I),
    re.compile(r"(\d[\d,]*)\)?\s+(?:units?|homes?)\s+(?:at|for households (?:earning|at))\s+(?:or below\s+)?\d{2}\s*(?:%|percent)", re.I),
]


_ACCESSIBLE = re.compile(r"mobility|sensory|hearing|visual|vision|disabilit|impair|accessib|wheelchair", re.I)


def affordable_homes(claims: list[dict]) -> tuple[int | None, str | None]:
    """The count of affordable homes the records state outright, and that claim's id.

    The largest count that council records state as restricted or affordable ("57 of the 94 units", "a 245-unit
    affordable community"). Counts of accessible units ("9 units will be set aside for residents with mobility
    impairments") are not affordability counts and are skipped. A developer's slide is used only when no council
    record states a count: slides also list the developer's other projects.
    """
    def best_in(keep) -> tuple[int, str] | None:
        best = None
        for c in claims:
            if c["topic"] not in ("units", "income_basis") or not keep(c):
                continue
            for pattern in (*_RESTRICTED_COUNT, *_AFFORDABLE_COUNT):
                for m in pattern.finditer(c["quote"]):
                    if _ACCESSIBLE.search(c["quote"][m.end():m.end() + 90]):
                        continue
                    n = int(m.group(1).replace(",", ""))
                    if 0 < n < 5000 and (best is None or n > best[0]):
                        best = (n, c["id"])
        return best

    slide = lambda c: "presentation" in (c.get("document_type") or "").lower()  # noqa: E731
    return best_in(lambda c: not slide(c)) or best_in(slide) or (None, None)


def _homes(claims: list[dict]) -> tuple[int | None, int | None]:
    """Affordable homes and total homes from the furthest-stage claim that states a count."""
    order = {s: i for i, s in enumerate(ledger.STATUSES)}
    counted = [c for c in claims if c["topic"] == "units" and (c.get("homes") or {}).get("count")]
    if not counted:
        return None, None
    best = max(counted, key=lambda c: (order.get(c.get("status"), 0), c.get("date") or ""))
    total = max((c["homes"].get("of") or 0 for c in counted), default=0) or None
    return best["homes"]["count"], total


def _county_json(name: str):
    """A small JSON file shipped with the county records (locations, outline), or None when it is missing."""
    path = COUNTY_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def county_board(store: Storage | None = None, today: date | None = None) -> dict:
    """Every real county deal in one table, plus county-wide totals.

    Each number comes from checked quotes in that deal's records ("not found" means no wording was found in the
    records read, not that the agreement lacks it). Nothing here is a finding about any party.
    """
    store = store or get_store()
    today = today or date.today()
    rows = []
    # Each location is the property address as a record states it (record and page kept), geocoded once.
    places = _county_json("locations.json") or {}
    for deal in store.list_deals():
        if not deal.get("real"):
            continue
        docs = store.list_documents(deal["id"])
        done = [d for d in docs if d.get("status") == "done"]
        claims = [c for d in done for c in d.get("claims") or []]
        review = build_deal_review(deal, docs)
        located = {t["key"]: bool(t.get("located")) for t in review["terms"]}
        _, total = _homes(claims)
        homes, homes_claim = affordable_homes(claims)
        end = term_end(claims, done)
        source = deal.get("source") or {}
        # Council files hold the approved agreement, rarely the executed copy, so a signed end date is often missing.
        # Then the approved term is counted from the Council's adoption date and marked as an estimate: the signed
        # agreement may start later (for example at occupancy), never earlier.
        estimate = None
        if not (end and end.get("date")) and source.get("passed"):
            # Leave out template options ("OR [Owner agrees ... for a term of at least ...]") and quoted state law
            # ("enters into an agreement with the governing body of the county ..."): they state minimums, not
            # this deal's term. "for the 30-year term" counts wherever it is filed.
            spans = [c for c in claims if (c["topic"] == "term" or _YEAR_TERM.search(c["quote"]))
                     and not _TEMPLATE.search(c["quote"]) and not _STATUTE.search(c["quote"])
                     and (_term_years(c))]
            if spans:
                # The longest term the records state (in PILOT records usually the PILOT term), not a judgement of
                # which clause governs: the board links the quote so a person can check it.
                pick = max(spans, key=lambda c: (_term_years(c) or 0, c.get("date") or ""))
                years = _term_years(pick)
                estimate = {"date": _add_years(date.fromisoformat(source["passed"]), years).isoformat(), "years": years,
                            "claim_id": pick["id"]}
        # Agreements often set several income tiers; list every share of median income the checked quotes state.
        tiers = sorted({t for c in claims if c["topic"] == "income_basis" for t in _ami_limits(c["quote"])})
        homes_quote = next((c["quote"] for c in claims if c["id"] == homes_claim), "") if homes else ""
        if not tiers and homes_quote:
            # The sentence that states the home count often states who the homes are for, too ("112 units ... for
            # seniors earning seventy percent (70%) or below of the Area Median Income"). Only that sentence is used:
            # other unit quotes (developer slides) can list a different phase's tiers.
            tiers = sorted(_ami_limits(homes_quote))
        at = re.search(rf"\b{homes:,}\b|\b{homes}\b", homes_quote) if homes else None
        homes_approx = bool(at and _APPROX_COUNT.search(homes_quote[max(0, at.start() - 20):at.start()]))
        income = ", ".join(f"{t}%" for t in tiers) + " of area median income" if tiers else None
        rows.append({
            "id": deal["id"], "name": deal["name"], "file": source.get("file"), "council_status": source.get("status"),
            "introduced": source.get("introduced"), "passed": source.get("passed"), "source_url": source.get("url"),
            "votes": source.get("votes") or [],
            "records": len(docs), "records_read": len(done), "claims": len(claims),
            "pages": sum(int(d.get("pages") or d.get("page_count") or 0) for d in done),
            "cost_usd": round(sum(float(d.get("cost_usd") or 0) for d in done), 4),
            "location": ({k: places[deal["id"]].get(k) for k in ("address", "city", "lat", "lon", "approx", "geocoder")}
                         | {"record": places[deal["id"]]["source"].get("record"), "page": places[deal["id"]]["source"].get("page")})
            if deal["id"] in places else None,
            "homes": homes, "homes_approx": homes_approx, "homes_claim_id": homes_claim, "total_homes": total,
            "income_limit": income,
            "term_end": end["date"].isoformat() if end and end.get("date") else (estimate or {}).get("date"),
            "term_end_estimated": bool(estimate),
            "term_years": (end.get("years") if end and end.get("date") else None) or (estimate or {}).get("years"),
            "term_claim_id": end["claim"]["id"] if end and end.get("date") else (estimate or {}).get("claim_id"),
            "furthest_stage": review["summary"]["furthest_status"],
            "found": {k: located.get(k, False) for k in OBLIGATION_TERMS},
            "not_found": [k for k in OBLIGATION_TERMS if not located.get(k, False)],
            "terms_differ": review["summary"]["terms_differ"],
            # Approved text that still holds template blanks or alternatives, e.g. "(insert specific dates upon
            # approval)" or "OR [Owner agrees ...]". Quoted so a person can see exactly what was left unfilled.
            "template_text": [{"claim_id": c["id"], "quote": c["quote"][:160], "document": c.get("document_type"),
                               "page": c.get("page")}
                              for c in claims if _TEMPLATE.search(c["quote"])][:5],
        })
    rows.sort(key=lambda r: r["passed"] or r["introduced"] or "", reverse=True)
    read = [r for r in rows if r["records_read"]]
    ends = [r for r in read if r["term_end"]]
    return {
        "county": "Prince George's County, Maryland",
        "source": "Prince George's County Council records (Legistar)",
        "as_of": today.isoformat(),
        "deals": rows,
        "map": _county_json("boundary.json"),
        "totals": {
            "pages": sum(r["pages"] for r in rows), "located": sum(1 for r in rows if r["location"]),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 2),
            "deals": len(rows), "deals_read": len(read),
            "records": sum(r["records"] for r in rows), "records_read": sum(r["records_read"] for r in rows),
            "homes": sum(r["homes"] or 0 for r in read), "deals_with_homes": sum(1 for r in read if r["homes"]),
            "total_homes": sum(r["total_homes"] or 0 for r in read if r["homes"]),
            "found": {k: sum(1 for r in read if r["found"][k]) for k in OBLIGATION_TERMS},
            "term_ends_known": len(ends),
            "ending_by_2040": sum(1 for r in ends if r["term_end"] < "2041-01-01"),
            "terms_differ": sum(1 for r in read if r["terms_differ"]),
            "template_text": sum(1 for r in read if r["template_text"]),
        },
    }


# ---------------------------------------------------------------------------
# Documents

def add_document(deal_id: str, filename: str, data: bytes, type_: str | None = None, date_: str | None = None,
                 title: str | None = None, store: Storage | None = None, process: bool = True,
                 demo: bool | None = None, doc_id: str | None = None) -> dict:
    """Check and store the file, then queue it for reading. Raises pipeline.PdfError for a bad file.

    Uploads made while DEMO_MODE is on are marked demo, so the sweep removes them even from sample deals.
    The same file uploaded twice to one deal returns the first copy, marked "duplicate", so claims never double (L11).
    `doc_id` fixes the id (sample deals), replacing any document stored under it.
    """
    store = store or get_store()
    sha = pipeline.file_hash(data)
    if doc_id is None:
        same = next((d for d in store.list_documents(deal_id) if d.get("sha256") == sha), None)
        if same:
            return {**same, "duplicate": True}
    pages = pipeline.extract_pages(data)  # Size, type and page limits are checked here, before anything is stored.
    if date_:
        date.fromisoformat(date_)  # ValueError is turned into a 422 by the API.
    doc_id = doc_id or f"d{uuid.uuid4().hex[:8]}"
    stamp = now()
    file_key = f"deals/{deal_id}/{doc_id}.pdf"
    store.put_blob(file_key, data, "application/pdf")
    store.put_blob(f"deals/{deal_id}/{doc_id}.pages.json", json.dumps(pages, ensure_ascii=False).encode(), "application/json")
    doc = {
        "id": doc_id, "filename": Path(filename or "document.pdf").name, "type": (type_ or "").strip() or None,
        "date": date_ or None, "title": (title or "").strip() or None, "pages": len(pages),
        "scanned_pages": pipeline.scanned_pages(pages), "status": "queued", "error": None,
        "file_key": file_key, "sha256": sha, "claims": [],
        "created_at": stamp, "updated_at": stamp,
    }
    if (guard.enabled() if demo is None else demo):
        doc["demo"] = True
    store.put_document(deal_id, doc)
    touch(deal_id, store)
    if process:
        submit(deal_id, doc_id, store)
    return doc


def submit(deal_id: str, doc_id: str, store: Storage) -> None:
    if run_inline:
        process_document(deal_id, doc_id, store)
    else:
        _executor.submit(process_document, deal_id, doc_id, store)


def _set(store: Storage, deal_id: str, doc: dict, **fields) -> dict:
    doc.update(fields, updated_at=now())
    store.put_document(deal_id, doc)
    return doc


def page_texts(deal_id: str, doc_id: str, store: Storage) -> list[str]:
    raw = store.get_blob(f"deals/{deal_id}/{doc_id}.pages.json")
    return json.loads(raw) if raw else []


def process_document(deal_id: str, doc_id: str, store: Storage | None = None, reader=None,
                     use_cache: bool = True, transcriber=None) -> dict | None:
    """Read, check and save one document. Never raises; failures are recorded on the document."""
    store = store or get_store()
    doc = store.get_document(deal_id, doc_id)
    if not doc:
        return None
    try:
        pages = page_texts(deal_id, doc_id, store)
        # Scanned pages are transcribed first (app/vision.py); the text takes the page's place from here on.
        filled, scan = vision.fill_scanned(doc, pages, lambda: store.get_blob(doc["file_key"]), call=transcriber,
                                           use_cache=use_cache)
        if filled != pages:
            pages = filled
            store.put_blob(f"deals/{deal_id}/{doc_id}.pages.json", json.dumps(pages, ensure_ascii=False).encode(),
                           "application/json")
        if not any(len(p.strip()) >= pipeline.MIN_PAGE_CHARS for p in pages):
            return _set(store, deal_id, doc, status="failed",
                        error="No text layer was found. The pages look scanned; run OCR and upload again.")
        _set(store, deal_id, doc, status="reading", error=None, started_at=now())
        result, from_cache = pipeline.read_with_cache(doc["sha256"], pages, reader=reader, use_cache=use_cache)
        if result.mode != "live" or result.reading is None:
            return _set(store, deal_id, doc, status="failed", error=result.notice)
        _set(store, deal_id, doc, status="checking", model=result.model, from_cache=from_cache,
             tokens_in=result.tokens_in + scan.tokens_in, tokens_out=result.tokens_out + scan.tokens_out,
             cost_usd=round(result.cost_usd + scan.cost_usd, 6))
        deal = store.get_deal(deal_id) or {}
        known = [deal.get("developer") or "", f"City of {deal.get('city')}" if deal.get("city") else ""]
        checked = pipeline.verify_reading(result.reading, pages, doc, known)
        doc = _set(store, deal_id, doc, status="done", **checked)
        touch(deal_id, store)
        return doc
    except Exception as err:  # Record text is never logged.
        print(f"Processing {deal_id}/{doc_id} failed: {type(err).__name__}")
        try:
            return _set(store, deal_id, doc, status="failed", error=f"Processing failed ({type(err).__name__}).")
        except Exception as save_err:  # The store itself failed; resume_pending or a retry picks the document up (L12).
            print(f"Could not record the failure for {deal_id}/{doc_id}: {type(save_err).__name__}")
            return None


def is_stale(doc: dict, now_at: datetime | None = None) -> bool:
    """Still queued, reading or checking, with no progress for STALE_SECONDS (another instance may have died)."""
    if doc.get("status") not in ("queued", "reading", "checking"):
        return False
    try:
        last = datetime.fromisoformat(doc.get("updated_at") or doc.get("started_at") or doc.get("created_at") or "")
    except ValueError:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return ((now_at or datetime.now(timezone.utc)) - last).total_seconds() > STALE_SECONDS


def resume_pending(store: Storage | None = None, now_at: datetime | None = None) -> int:
    """After a restart, queue documents that stopped. Only stale ones: another instance may be reading the rest (L12)."""
    store = store or get_store()
    count = 0
    for deal in store.list_deals():
        for doc in store.list_documents(deal["id"]):
            if is_stale(doc, now_at):
                submit(deal["id"], doc["id"], store)
                count += 1
    return count


class RetryError(ValueError):
    """The document cannot be read again now. The message is safe to show."""


def retry_document(deal_id: str, doc_id: str, store: Storage | None = None) -> dict:
    """Read a failed or stuck document again (L12). The UI's Retry button calls this."""
    store = store or get_store()
    doc = store.get_document(deal_id, doc_id)
    if not doc:
        raise RetryError("Document not found.")
    if doc.get("status") != "failed" and not is_stale(doc):
        raise RetryError("This document is not stuck or failed. Wait for it to finish.")
    doc = _set(store, deal_id, doc, status="queued", error=None)
    submit(deal_id, doc_id, store)
    return store.get_document(deal_id, doc_id) or doc


# ---------------------------------------------------------------------------
# Review (same shape as /api/review)

def _stage_notes(claims: list[dict], docs: list[dict]) -> dict:
    signers = sorted({s for d in docs if d.get("signed") for s in d.get("signed_by") or []})
    by = {s: sum(c["status"] == s for c in claims) for s in ledger.STATUSES}
    return {
        "proposed": "Described as an idea, a plan or an understanding." if by["proposed"] else "No proposal records located.",
        "supported": "Recommended by staff or backed by a recorded Council action. Support is not a signed term."
                     if by["supported"] else "No minutes or resolution with a recorded action located.",
        "signed": f"Signed by {', '.join(signers)}." if signers else "No signed record located.",
        "delivered": "Certificate or occupancy record located (as stated in the record)." if by["delivered"]
                     else "No record located that homes were built, leased or checked.",
    }


def _document_view(doc: dict, pages: list[str] | None) -> dict:
    view = {
        "id": doc["id"], "type": doc.get("type") or "Record", "title": doc.get("title") or doc.get("filename"),
        "date": doc.get("date") or "", "signed": bool(doc.get("signed")), "signed_by": doc.get("signed_by") or [],
        "filename": doc.get("filename"), "status": doc.get("status"), "stage": doc.get("stage"),
        "page_count": doc.get("pages"),
    }
    if pages is not None:
        view["pages"] = [{"page": i, "paragraphs": [p for p in text.split("\n") if p.strip()]}
                         for i, text in enumerate(pages, 1)]
    return view


def _compare_term(term: dict, claims: list[dict]) -> dict:
    """Decide "wording differs" from code-read keys when the claims have them (uploaded records).

    Hand-reviewed demo claims have no "compare" field and keep the ledger's value comparison.
    """
    found = [c for c in claims if c["id"] in set(term["claim_ids"])]
    if not found or not all("compare" in c for c in found):
        return term
    keyed = sorted([c for c in found if c["compare"]], key=lambda c: (c["date"] or "", c["id"]))
    keys = list(dict.fromkeys(c["compare"] for c in keyed))
    return {**term, "wording_differs": len(keys) > 1, "values": keys if len(keys) > 1 else term["values"],
            "differs_claim_ids": [c["id"] for c in keyed] if len(keys) > 1 else []}


LEGAL_TERMS = ("term", "responsible_party", "reporting", "remedies")
AFFORDABILITY_TERMS = ("units", "income_basis", "rent_limits")


def next_records(claims: list[dict], terms: list[dict], docs: list[dict]) -> list[dict]:
    """Which records to ask for next, by rule: the terms not located and the stages no record reaches.

    No model is asked. Each item names a kind of record, why it helps, and the missing terms it usually holds.
    """
    if not claims:
        return []  # The no-commitments note covers a deal with nothing located.
    missing = {t["key"]: t["label"] for t in terms if not t["located"]}
    stages = {c["status"] for c in claims}
    kinds = {d.get("type_key") for d in docs}
    labels = lambda keys: [missing[k] for k in keys if k in missing]  # noqa: E731
    out = []
    if not stages & {"signed", "delivered"}:
        out.append({"key": "agreement", "record": "Signed agreement",
                    "why": "The regulatory or development agreement, with its signature pages. "
                           "Until one is on file, no commitment can count as Signed.",
                    "terms": labels(LEGAL_TERMS)})
    elif labels(LEGAL_TERMS):
        out.append({"key": "agreement_full", "record": "The full signed agreement",
                    "why": "A signed record is on file, but some terms were not located in it. "
                           "Ask for every page and exhibit, including any recorded covenant.",
                    "terms": labels(LEGAL_TERMS)})
    if labels(AFFORDABILITY_TERMS):
        if "staff_report" in kinds:
            out.append({"key": "exhibit", "record": "Affordability exhibit or term sheet",
                        "why": "The staff report on file does not state these. They are often in an exhibit to the agreement.",
                        "terms": labels(AFFORDABILITY_TERMS)})
        else:
            out.append({"key": "staff_report", "record": "Staff report",
                        "why": "The report to council usually states the homes, income limits and rent limits.",
                        "terms": labels(AFFORDABILITY_TERMS)})
    if not stages & {"supported", "signed", "delivered"} and not kinds & {"minutes", "resolution"}:
        out.append({"key": "minutes", "record": "Council minutes or resolution",
                    "why": "Shows whether officials voted to approve the deal. Without it, nothing can count as Supported.",
                    "terms": []})
    if stages & {"signed"} and "delivered" not in stages:
        out.append({"key": "delivery", "record": "Certificate of occupancy or compliance report",
                    "why": "Shows whether the homes were built and leased. Without it, nothing can count as Delivered.",
                    "terms": []})
    return out


def build_deal_review(deal: dict, docs: list[dict], store: Storage | None = None, with_pages: bool = False) -> dict:
    """Rebuild the review from verified claims. Same keys as /api/review, plus a few aliases."""
    done = [d for d in _sort_docs(docs) if d.get("status") == "done"]
    claims = [c for d in done for c in d.get("claims") or []]
    pages = {d["id"]: page_texts(deal["id"], d["id"], store) for d in done} if (with_pages and store) else {}
    documents = [_document_view(d, pages.get(d["id"]) if with_pages else None) for d in _sort_docs(docs)]
    # An empty city would match every signer name in ledger.build_summary, so use a value no name contains.
    packet = {"city": deal["city"] or "\0","developer": deal.get("developer"),
              "documents": [{"signed": d.get("signed", False), "signed_by": d.get("signed_by") or []} for d in done]}
    ordered = [{**c, "quote_checked": bool(c.get("verified", True))} for c in sorted(claims, key=lambda c: (c["date"] or "", c["id"]))]
    stages = ledger.build_stages(claims, _stage_notes(claims, done))
    terms = [_compare_term(t, claims) for t in ledger.build_terms(claims)]
    summary = ledger.build_summary(claims, terms, stages, packet)
    questions = ledger.build_questions(claims, terms, stages, summary)
    keyed = {t["key"]: t for t in terms if t.get("differs_claim_ids")}
    for q in questions:
        if q["tag"] == "differs" and q.get("term") in keyed:
            t = keyed[q["term"]]
            q["text"] = (f"{t['label']}: wording differs across {len(t['differs_claim_ids'])} records "
                         f"(“{t['values'][0]}” to “{t['values'][-1]}”). "
                         "Ask staff which wording, if any, is in a signed agreement.")
    for d in docs:
        # A failed document already has its own question; a scanned one that was read gets one (L13).
        if d.get("scanned_pages") and d.get("status") != "failed":
            questions.extend(vision.scan_questions(d))
        if d.get("status") == "failed":
            questions.append({"key": f"failed-{d['id']}", "tag": "not_located",
                              "text": f"{d.get('filename')}: not read. {d.get('error') or ''}".strip()})
    end = term_end(claims, done)
    if end and end["date"] is None:
        questions.append({"key": "term_start", "tag": "not_located",
                          "text": f"Term: the signed record counts the term from an event with no date on file "
                                  f"(“{end['claim']['quote']}”). Ask staff for that date to set the end date."})
    counts = {k: sum((d.get("counts") or {}).get(k, 0) for d in done)
              for k in ("candidates", "kept", "page_corrected", "dropped", "duplicates", "absent", "boilerplate", "off_term")}
    by_id = {c["id"]: c for c in ordered}
    what_changed = [
        {"key": t["key"], "label": t["label"], "values": t["values"],
         "records": [{"claim_id": i, "value": by_id[i].get("compare") or by_id[i]["value"], "date": by_id[i]["date"],
                      "document_type": by_id[i]["document_type"], "status": by_id[i]["status"]}
                     for i in (t.get("differs_claim_ids") or t["claim_ids"])]}
        for t in terms if t["wording_differs"]
    ]
    return {
        "notice": "Code checked each quote against its cited page. People make every decision.",
        "deal_id": deal["id"],
        "city": deal["city"],
        "project": deal["name"],
        "developer": deal.get("developer"),
        "documents": documents,
        "topics": ledger.TOPICS,
        "claims": ordered,
        "stages": stages,
        "terms": terms,
        "summary": summary,
        "questions": questions,
        "open_questions": questions,
        "what_changed": what_changed,
        "next_records": next_records(claims, terms, done),
        # Quotes found on their page that the term rules did not confirm. Optional to check; never counted.
        "possible": [{"key": f"possible-{d['id']}-{i}", "topic": item["topic"],
                      "label": ledger.TOPICS.get(item["topic"], item["topic"]), "quote": item["quote"],
                      "page": item["page"], "document": d["id"],
                      "document_title": d.get("title") or d.get("filename"), "document_type": d.get("type") or "Record",
                      "date": d.get("date") or ""}
                     for d in done for i, item in enumerate(d.get("set_aside") or [], 1)],
        "kpis": {
            "documents": len(docs),
            "documents_done": len(done),
            "claims": len(ordered),
            "furthest_stage": summary["furthest_status"],
            "terms_differ": summary["terms_differ"],
            "terms_not_located": summary["terms_not_located"],
            "terms_total": summary["terms_total"],
        },
        "receipt": [
            {"key": t["key"], "label": t["label"], "result": t["result"], "furthest_status": t["furthest_status"],
             "wording_differs": t["wording_differs"], "signed_claim_id": t["signed_claim_id"],
             "claim_ids": t["claim_ids"]}
            for t in terms
        ],
        "checks": {"total": len(ordered), "passed": len(ordered), "problems": [], **counts},
    }


def is_sample(deal: dict) -> bool:
    """Sample deals are public. Their reviews are kept per browser so visitors never see each other's."""
    return bool(deal.get("sample_slug")) or deal.get("id") == DEMO_DEAL_ID


def deal_review(deal_id: str, store: Storage | None = None, with_pages: bool = False,
                session: str | None = None) -> dict | None:
    store = store or get_store()
    deal = store.get_deal(deal_id)
    if not deal:
        return None
    review = build_deal_review(deal, store.list_documents(deal_id), store=store, with_pages=with_pages)
    # Reviewer decisions sit beside the record. They never change a claim, a term or a stage.
    sandboxed = is_sample(deal)
    if sandboxed:  # Only this browser's events, read with a query rather than by streaming everyone's (P2).
        events = store.list_decisions(deal_id, session=session) if session else []
    else:
        events = store.list_decisions(deal_id)
    review["decisions"] = decision_view(review, events)
    review["decisions"]["sandboxed"] = sandboxed
    return review


# ---------------------------------------------------------------------------
# Reviewer decisions: "People decide"

DECISIONS = {"confirmed": "Confirmed", "follow_up": "Needs follow-up", "disputed": "Disputed"}
TARGET_TYPES = ("claim", "question")
MAX_NOTE = 500
MAX_REVIEWER = 80
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DecisionError(ValueError):
    """The decision is not valid for this deal."""


def _clean(text, limit: int, field: str, required: bool) -> str:
    text = _CONTROL.sub("", str(text or "")).strip()
    if required and not text:
        raise DecisionError(f"Enter a {field}.")
    if len(text) > limit:
        raise DecisionError(f"Keep the {field} under {limit} characters.")
    return text


def decision_targets(review: dict) -> dict:
    """Everything a person can decide on: each claim, and each open question (the term checks)."""
    targets = {("claim", c["id"]): c for c in review["claims"]}
    targets.update({("question", q["key"]): q for q in review["questions"]})
    return targets


def add_decision(deal_id: str, payload: dict, reviewer: dict, store: Storage | None = None,
                 review: dict | None = None) -> dict:
    """Record one reviewer decision. `reviewer` comes from identity.current_reviewer(), never from the payload.

    Notes are stored as plain text and never read as instructions. Pass `review` to reuse one already built.
    """
    store = store or get_store()
    review = review or deal_review(deal_id, store, session=reviewer.get("session"))
    if review is None:
        raise DecisionError("Deal not found.")
    target = (str(payload.get("target_type") or ""), str(payload.get("target_id") or ""))
    if target[0] not in TARGET_TYPES:
        raise DecisionError("Choose a claim or an open question.")
    if target not in decision_targets(review):
        raise DecisionError("That item is not in this deal.")
    decision = str(payload.get("decision") or "")
    if decision not in DECISIONS:
        raise DecisionError("Choose Confirm, Needs follow-up or Disputed.")
    event = {
        "id": f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{secrets.token_hex(3)}",
        "target_type": target[0],
        "target_id": target[1],
        "decision": decision,
        "label": DECISIONS[decision],
        "note": _clean(payload.get("note"), MAX_NOTE, "note", required=False),
        "reviewer_id": reviewer["id"],
        "reviewer_name": _clean(reviewer.get("name"), MAX_REVIEWER, "reviewer name", required=True),
        "session": reviewer.get("session"),
        "at": now(),
    }
    store.put_decision(deal_id, event)
    return event


def decide(deal_id: str, payload: dict, reviewer: dict, store: Storage | None = None) -> dict:
    """Record a decision and return the public event with the updated decisions view, building the review once."""
    store = store or get_store()
    review = deal_review(deal_id, store, session=reviewer.get("session"))
    event = add_decision(deal_id, payload, reviewer, store, review=review)
    deal = store.get_deal(deal_id) or {}
    session = reviewer.get("session")
    events = (store.list_decisions(deal_id, session=session) if session else []) if is_sample(deal) \
        else store.list_decisions(deal_id)
    if event["id"] not in {e["id"] for e in events}:  # A store with delayed reads still shows the new event.
        events.append(event)
    view = decision_view(review, events)
    view["sandboxed"] = is_sample(deal)
    return {"event": public_event(event), **view}


def reset_decisions(deal_id: str, session: str | None, store: Storage | None = None) -> dict:
    """Start this browser's review of a sample deal over. Earlier events stay stored; a marker hides them."""
    store = store or get_store()
    deal = store.get_deal(deal_id)
    if not deal or not is_sample(deal):
        raise DecisionError("Only a sample deal's review can be reset.")
    if not session:
        raise DecisionError("This browser has no demo session to reset.")
    event = {"id": f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{secrets.token_hex(3)}",
             "kind": "reset", "session": session, "at": now()}
    store.put_decision(deal_id, event)
    return event


PRIVATE_EVENT_FIELDS = ("session", "reviewer_id")


def public_event(event: dict) -> dict:
    """A decision as the API, exports and share pages show it: no session or reviewer id (S3)."""
    return {k: v for k, v in event.items() if k not in PRIVATE_EVENT_FIELDS}


def _normalize(event: dict) -> dict:
    """Events saved before the identity seam had a plain "reviewer" field."""
    if "reviewer_name" not in event:
        event = {**event, "reviewer_name": event.get("reviewer", ""), "reviewer_id": f"local:{event.get('reviewer', '').lower()}"}
    return event


def decision_view(review: dict, events: list[dict]) -> dict:
    """The latest decision per item, the full log, progress, and the receipt stamp. One source for every view."""
    targets = decision_targets(review)
    resets = [e["id"] for e in events if e.get("kind") == "reset"]
    since = max(resets) if resets else ""
    log = sorted((public_event(_normalize(e)) for e in events if e.get("kind") != "reset" and e["id"] > since
                  and (e.get("target_type"), e.get("target_id")) in targets), key=lambda e: e["id"])
    latest = {}
    for event in log:
        latest[f"{event['target_type']}:{event['target_id']}"] = event
    claims_done = sum(1 for c in review["claims"] if f"claim:{c['id']}" in latest)
    flagged = [q["key"] for q in review["questions"]]
    flagged_done = sum(1 for key in flagged if f"question:{key}" in latest)
    complete = bool(flagged) and flagged_done == len(flagged)
    return {
        "latest": latest,
        "log": list(reversed(log)),
        "progress": {"claims_reviewed": claims_done, "claims_total": len(review["claims"]),
                     "flagged_reviewed": flagged_done, "flagged_total": len(flagged),
                     "reviewed": claims_done + flagged_done, "total": len(review["claims"]) + len(flagged),
                     "complete": complete},
        "stamp": review_stamp(review, latest),
        "footer": REVIEW_FOOTER,
        "labels": DECISIONS,
    }


REVIEW_FOOTER = "A review records people's decisions. It is not a legal finding."
STAMP_STATES = ("flagged", "in_progress", "complete_confirmed", "complete_follow_up", "complete_disputed")


def _count_text(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def review_stamp(review: dict, latest: dict) -> dict:
    """The receipt stamp, from the decisions on the open questions (or on the claims when there are none) (W1).

    The text states the outcome; the last reviewer and date are separate fields for the line under the stamp.
    """
    keys = [f"question:{q['key']}" for q in review["questions"]] or [f"claim:{c['id']}" for c in review["claims"]]
    decided = [latest[key] for key in keys if key in latest]
    stamp = {"state": "flagged", "text": "Flagged for human review", "reviewer": None, "date": None,
             "decided": len(decided), "total": len(keys)}
    if not decided:
        return stamp
    last = max(decided, key=lambda e: e["id"])
    stamp.update(reviewer=last["reviewer_name"], date=last["at"][:10])
    if len(decided) < len(keys):
        return {**stamp, "state": "in_progress", "text": f"Review in progress · {len(decided)} of {len(keys)} decided"}
    disputed = sum(e["decision"] == "disputed" for e in decided)
    follow_up = sum(e["decision"] == "follow_up" for e in decided)
    if disputed:
        text = f"Review complete · {disputed} disputed"
        if follow_up:
            text += f" · {follow_up} need{'s' if follow_up == 1 else ''} follow-up"
        return {**stamp, "state": "complete_disputed", "text": text}
    if follow_up:
        return {**stamp, "state": "complete_follow_up",
                "text": f"Review complete · {follow_up} need{'s' if follow_up == 1 else ''} follow-up"}
    return {**stamp, "state": "complete_confirmed", "text": "Review complete · all confirmed"}


# ---------------------------------------------------------------------------
# Reminders

_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}
_DATE_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_DUE_RE = re.compile(r"\bby\s+(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\s+of each year", re.I)
# A term counted from an event the records do not date, such as the first move-in.
_EVENT_START = re.compile(r"from the (first|date the first|date of first|initial)|move-in|placed in service|is leased|occupancy", re.I)


_AFFORDABILITY = re.compile(r"afford|requirement|income|rent|restrict|commitment", re.I)


def _years(value: str) -> int | None:
    m = re.search(r"\b(\d+)[\s-]*years?\b", value or "")
    return int(m.group(1)) if m else None


def _dates(text: str) -> list[date]:
    out = []
    for month, day, year in _DATE_RE.findall(text or ""):
        try:
            out.append(date(int(year), _MONTHS[month.lower()], int(day)))
        except ValueError:
            pass
    return out


def _add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 29 February
        return d.replace(year=d.year + n, day=28)


def term_end(claims: list[dict], docs: list[dict]) -> dict | None:
    """When the affordability term ends, from signed records only, or why it cannot be dated."""
    signed_docs = {d["id"]: d for d in docs if d.get("stage") == "signed"}
    terms = [c for c in claims if c["topic"] == "term" and c["document"] in signed_docs]
    if not terms:
        return None
    # Prefer clauses about the affordability rules over other time spans, such as a tax payment period.
    about = [c for c in terms if _AFFORDABILITY.search(c["quote"])] or terms
    latest = max(c["date"] or "" for c in about)
    about = [c for c in about if (c["date"] or "") == latest]
    for term in about:
        stated = _dates(term["quote"])
        if stated and re.search(r"\bend", term["quote"], re.I):
            return {"date": max(stated), "claim": term, "how": "stated"}
    # If any clause counts from an undated event, do not guess an end date.
    for term in about:
        if _EVENT_START.search(term["quote"]):
            return {"date": None, "claim": term, "how": "event", "years": _years(term["value"]) or _years(term["quote"])}
    for term in about:
        years = _years(term["value"]) or _years(term["quote"])
        if years and term["date"]:
            return {"date": _add_years(date.fromisoformat(term["date"]), years), "claim": term, "how": "counted",
                    "years": years}
    return {"date": None, "claim": about[0], "how": "event", "years": None}


def deal_reminders(deal: dict, docs: list[dict], today: date | None = None) -> list[dict]:
    """Upcoming end dates and missing yearly checks, from signed agreement terms and certificate records.

    A deal with an "as_of" date (the sample deals) is read as of that date, so its reminders never change.
    """
    today = today or (date.fromisoformat(deal["as_of"]) if deal.get("as_of") else date.today())
    done = [d for d in docs if d.get("status") == "done"]
    claims = [c for d in done for c in d.get("claims") or []]
    out = []

    def add(kind: str, when: date, text: str, source: str | None):
        # kind: term_end, missing_record (a yearly check that is past due and not on file) or other.
        # days: positive until the date, negative after it, counted from the deal's as_of date when it has one (L2).
        out.append({"deal_id": deal["id"], "deal_name": deal["name"], "city": deal["city"], "kind": kind,
                    "check": "term" if kind == "term_end" else "yearly", "date": when.isoformat(),
                    "due": when.isoformat(), "days": (when - today).days, "as_of": today.isoformat(),
                    "overdue": when < today, "text": text, "claim_id": source})

    end = term_end(claims, done)
    if end and end["date"]:
        claim = end["claim"]
        how = ("as stated in the" if end["how"] == "stated"
               else f"{end['years']} years from the") + f" {claim['document_type'].lower()} dated {display_date(claim['date'])}"
        verb = "ended" if end["date"] < today else "ends"
        add("term_end", end["date"], f"Affordability term {verb} {display_date(end['date'])}, {how}.", claim["id"])

    signed_ids = {d["id"] for d in done if d.get("stage") == "signed"}
    reporting = [c for c in claims if c["topic"] == "reporting" and c["document"] in signed_ids]
    if reporting:
        rule = max(reporting, key=lambda c: c["date"] or "")
        due = _DUE_RE.search(rule["quote"])
        start = date.fromisoformat(rule["date"]) if rule["date"] else today
        month, day = (_MONTHS[due.group(1).lower()], int(due.group(2))) if due else (start.month, start.day)
        received = {due_year for d in done if (due_year := _certificate_due_year(d)) is not None}
        last_year = end["date"].year + 1 if end and end["date"] else today.year + 1
        # Only the recent past is listed, so an old deal does not bury the queue.
        for year in range(max(start.year + 1, today.year - 1), min(today.year + 1, last_year) + 1):
            # "April 31" or "February 29" in a quote is clamped to the month's last day, never a 500 (L14).
            when = date(year, month, min(day, calendar.monthrange(year, month)[1]))
            if year in received:
                continue
            first = not received and year == start.year + 1
            name = "First yearly certificate" if first else "Yearly certificate"
            if when < today:
                add("missing_record", when, f"{name} due {display_date(when)}: not in the file yet. "
                                          "Ask the owner or staff for it.", rule["id"])
            else:
                add("other", when, f"{name} due {display_date(when)}" + ("; not in the file yet." if first else "."),
                    rule["id"])
                break
    return out


_REPORTING_YEAR = re.compile(r"\breporting year\s+(\d{4})\b|\b(?:calendar|fiscal) year\s+(\d{4})\b|"
                             r"\bfor (?:the year|year)\s+(\d{4})\b", re.I)


def _certificate_due_year(doc: dict) -> int | None:
    """The year whose yearly due date a delivered certificate meets (L15).

    A certificate for reporting year 2024 meets the 2025 due date, whenever it is dated. Without a stated
    reporting year, the certificate's own date is used.
    """
    if doc.get("type_key") != "certificate" or doc.get("stage") != "delivered":
        return None
    text = " ".join([doc.get("title") or ""] + [c.get("quote", "") for c in doc.get("claims") or []])
    m = _REPORTING_YEAR.search(text)
    if m:
        return int(next(g for g in m.groups() if g)) + 1
    return date.fromisoformat(doc["date"]).year if doc.get("date") else None


def all_reminders(store: Storage | None = None, today: date | None = None, session: str | None = None) -> list[dict]:
    store = store or get_store()
    rows = []
    for deal in store.list_deals():
        if visible_to(deal, session):
            rows.extend(deal_reminders(deal, store.list_documents(deal["id"]), today))
    return _sort_reminders(rows)


# Years before an affordability term ends when staff get a heads-up: the window to negotiate an extension,
# a right of first refusal or a new regulatory agreement before the homes can leave the affordable stock.
TERM_WARNING_YEARS = (5, 3, 1)


def _ics_text(value: str) -> str:
    """RFC 5545 TEXT escaping."""
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    """Fold a content line at 75 octets (RFC 5545 3.1)."""
    raw, out = line.encode("utf-8"), []
    while len(raw) > 75:
        cut = 75
        while cut and (raw[cut] & 0xC0) == 0x80:  # Never split a UTF-8 character.
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def county_reminders(board: dict) -> list[dict]:
    """Each county agreement's longest stated term as a calendar reminder, worded as what it is: the term the records
    state, counted from the Council's adoption date unless a signed record dates it, so the real end is then or later."""
    rows = []
    for r in board["deals"]:
        if not r.get("term_end"):
            continue
        how = (f"{r['term_years']}-year term counted from the Council's adoption, so it ends then or later"
               if r.get("term_end_estimated") else "dated by a signed record")
        rows.append({"deal_id": r["id"], "deal_name": r["name"], "city": "", "kind": "term_end", "date": r["term_end"],
                     "text": f"Stated affordability term runs to {display_date(date.fromisoformat(r['term_end']))} ({how}). "
                             f"Council file {r.get('file') or ''}.", "claim_id": r.get("term_claim_id")})
    return rows


def reminders_ics(reminders: list[dict], base_url: str = "", today: date | None = None) -> str:
    """The reminders as an iCalendar file any calendar app can subscribe to or import.

    Each term end also gets heads-up events TERM_WARNING_YEARS before it. Every event says where its date came
    from, so a person can check it against the record before acting on it.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Promise Ledger//Affordability reminders//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Promise Ledger reminders"]

    def event(uid: str, when: date, summary: str, description: str, url: str) -> None:
        lines.extend(["BEGIN:VEVENT", f"UID:{uid}@promise-ledger", f"DTSTAMP:{stamp}",
                      f"DTSTART;VALUE=DATE:{when:%Y%m%d}", f"DTEND;VALUE=DATE:{(when + timedelta(days=1)):%Y%m%d}",
                      f"SUMMARY:{_ics_text(summary)}", f"DESCRIPTION:{_ics_text(description)}"]
                     + ([f"URL:{url}"] if url else []) + ["TRANSP:TRANSPARENT", "END:VEVENT"])

    today = today or date.today()
    for r in reminders:
        when = date.fromisoformat(r["date"])
        if when < today:
            continue  # A calendar is for what is still ahead.
        url = f"{base_url}/#/deals/{r['deal_id']}" if base_url else ""
        note = f"{r['text']} Source: Promise Ledger, from a checked quote; confirm against the record."
        key = f"{r['deal_id']}-{r['kind']}-{r['date']}"
        title = (f"affordability term ends {display_date(when)}" if r["kind"] == "term_end"
                 else r["text"].split(":")[0].split(",")[0])
        event(key, when, f"{r['deal_name']}: {title}", note, url)
        if r["kind"] == "term_end":
            for years in TERM_WARNING_YEARS:
                try:
                    early = when.replace(year=when.year - years)
                except ValueError:  # 29 February
                    early = when.replace(year=when.year - years, day=28)
                if early < today:
                    continue
                event(f"{key}-warn{years}", early,
                      f"{r['deal_name']}: affordability ends in {years} year{'s' if years > 1 else ''}",
                      f"{note} Time to plan for preservation before {display_date(when)}.", url)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------------------
# Export

CLAIM_COLUMNS = ["Term", "Quote", "Document", "Date", "Page", "Stage", "Wording differs", "Quote found on page",
                 "Decision", "Reviewer", "Decided", "Note"]
QUESTION_COLUMNS = ["Open question", "Flag", "Decision", "Reviewer", "Decided", "Note"]
LOG_COLUMNS = ["When", "Reviewer", "Item", "Decision", "Note"]


def _decided(review: dict, key: str) -> list:
    event = (review.get("decisions") or {}).get("latest", {}).get(key)
    if not event:
        return ["Not reviewed", "", "", ""]
    return [event["label"], event["reviewer_name"], event["at"].replace("T", " ").replace("+00:00", " UTC"), event["note"]]


def question_rows(review: dict) -> list[list]:
    flags = {"differs": "Wording differs", "not_located": "Not located"}
    return [[q["text"], flags.get(q.get("tag"), q.get("tag") or ""), *_decided(review, f"question:{q['key']}")]
            for q in review.get("questions", [])]


def log_rows(review: dict) -> list[list]:
    claims = {c.get("id"): c for c in review["claims"]}
    questions = {q["key"]: q for q in review.get("questions", [])}

    def item(e):
        if e["target_type"] == "claim" and e["target_id"] in claims:
            c = claims[e["target_id"]]
            return f"Claim: {ledger.TOPICS.get(c['topic'], c['topic'])}, {c['document_type']} p. {c['page']}"
        q = questions.get(e["target_id"])
        return f"Open question: {q['text'][:80]}" if q else e["target_id"]
    return [[e["at"].replace("T", " ").replace("+00:00", " UTC"), e["reviewer_name"], item(e), e["label"], e["note"]]
            for e in (review.get("decisions") or {}).get("log", [])]
TERM_COLUMNS = ["Term", "Result", "Furthest stage (any term)", "Wording differs", "Values", "Signed record"]


def claim_rows(review: dict) -> list[list]:
    titles = {d["id"]: d.get("title") or d.get("filename") for d in review["documents"]}
    differs = {t["key"] for t in review["terms"] if t["wording_differs"]}
    return [[ledger.TOPICS.get(c["topic"], c["topic"]), c["quote"], titles.get(c["document"]) or c["document_type"],
             c["date"], c["page"], ledger.STAGE_LABELS[c["status"]], "Yes" if c["topic"] in differs else "No",
             "Found" if c.get("quote_checked") else "Flagged for human review", *_decided(review, f"claim:{c.get('id')}")]
            for c in review["claims"]]


def term_rows(review: dict) -> list[list]:
    return [[t["label"], t["result"], ledger.STAGE_LABELS.get(t["furthest_status"], "") if t["furthest_status"] else "",
             "Yes" if t["wording_differs"] else "No", "; ".join(t["values"]), "Yes" if t["signed_claim_id"] else "No"]
            for t in review["terms"]]


def _cell(value):
    """Stop spreadsheet formula injection from record text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_sheets(review: dict) -> list[dict]:
    """The sheets every export is built from. The xlsx has all of them; the csv is the Claims sheet."""
    return [
        {"name": "Claims", "columns": CLAIM_COLUMNS, "rows": [[_cell(v) for v in row] for row in claim_rows(review)],
         "widths": [18, 70, 40, 12, 6, 12, 10, 10, 16, 20, 20, 40]},
        {"name": "Terms", "columns": TERM_COLUMNS, "rows": [[_cell(v) for v in row] for row in term_rows(review)],
         "widths": [18, 14, 14, 10, 50, 12]},
        {"name": "Open questions", "columns": QUESTION_COLUMNS, "rows": [[_cell(v) for v in row] for row in question_rows(review)],
         "widths": [70, 16, 16, 20, 20, 40]},
        {"name": "Review log", "columns": LOG_COLUMNS, "rows": [[_cell(v) for v in row] for row in log_rows(review)],
         "widths": [22, 20, 50, 16, 50]},
    ]


def export_about(review: dict, exported: str) -> list[list]:
    stamp = ((review.get("decisions") or {}).get("stamp") or {})
    rows = [[_cell(f"{review['project']}, {review['city']}")], [_cell(review["notice"])]]
    if stamp.get("text"):
        rows.append([_cell(stamp["text"] + (f" (last decision {display_date(stamp['date'])} by {stamp['reviewer']})"
                                            if stamp.get("date") and stamp.get("reviewer") else ""))])
    rows.append([REVIEW_FOOTER])
    rows.append([f"Exported {display_date(exported)}"])
    return rows


def export_preview(review: dict, deal_id: str) -> dict:
    """What the Excel and CSV files hold, as JSON, so the in-app preview always matches the download."""
    sheets = [{k: v for k, v in sheet.items() if k != "widths"} for sheet in export_sheets(review)]
    sheets.append({"name": "About", "columns": ["Note"], "rows": export_about(review, now())})
    base = f"{deal_id}-promise-ledger"
    return {"title": f"{review['project']} · Promise receipt", "project": review["project"], "city": review["city"],
            "files": {"xlsx": f"{base}.xlsx", "csv": f"{base}.csv"}, "csv_sheet": "Claims", "sheets": sheets}


def export_csv(review: dict) -> str:
    claims = export_sheets(review)[0]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(claims["columns"])
    writer.writerows(claims["rows"])
    return buf.getvalue()


def _as_text(cells) -> None:
    """Store every string as text, never as a formula, whatever it starts with (S4)."""
    for cell in cells:
        if isinstance(cell.value, str):
            cell.data_type = "s"


def export_xlsx(review: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    for index, sheet in enumerate(export_sheets(review)):
        ws = wb.active if index == 0 else wb.create_sheet()
        ws.title = sheet["name"]
        ws.append(sheet["columns"])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in sheet["rows"]:
            ws.append(row)
            _as_text(ws[ws.max_row])
        for col, width in zip("ABCDEFGHIJKL", sheet["widths"]):
            ws.column_dimensions[col].width = width
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
    note = wb.create_sheet("About")
    for row in export_about(review, now()):
        note.append(row)
        _as_text(note[note.max_row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Share links

def create_share(deal_id: str, store: Storage | None = None, session: str | None = None) -> str:
    store = store or get_store()
    token = secrets.token_urlsafe(16)
    store.put_share(token, deal_id, session=session)
    return token


def shared_review(token: str, store: Storage | None = None) -> dict | None:
    store = store or get_store()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token or ""):
        return None
    record = store.get_share_record(token)
    deal_id = record["deal_id"] if record else None
    review = deal_review(deal_id, store, session=record.get("session")) if deal_id else None
    if review is None:
        return None
    return {**review, "read_only": True, "share_token": token}


# ---------------------------------------------------------------------------
# Seeding

REFRESH_LOCK = "sample-refresh"
REFRESH_LOCK_TTL = 600  # Seconds before a lock left by a crashed instance is ignored.
# Code that shapes stored claims. When it changes, sample deals are re-checked from the cached readings.
_PIPELINE_FILES = [ROOT / "app" / "pipeline.py", ROOT / "app" / "deals.py", ROOT / "app" / "vision.py"]


def _manifest(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def sample_slug(manifest: dict, folder: Path) -> str:
    return manifest.get("slug") or manifest.get("id") or _slug(folder.name)


def sample_version(manifest_path: Path) -> str:
    """Hash of the manifest, its PDFs, the prompt version and the pipeline code."""
    h = hashlib.sha256()
    h.update(manifest_path.read_bytes())
    manifest = _manifest(manifest_path) or {}
    for entry in manifest.get("documents") or []:
        path = manifest_path.parent / (entry.get("file") or entry.get("filename") or "")
        h.update(path.name.encode())
        if entry.get("sha256"):  # Real records: the checked hash stands for the file, present on disk or not.
            h.update(str(entry["sha256"]).encode())
            # A record seeded before its saved reading existed is re-seeded once the reading arrives.
            h.update(b"read" if pipeline.cached_reading(str(entry["sha256"])) else b"unread")
        else:
            h.update(path.read_bytes() if path.is_file() else b"missing")
    h.update(pipeline.PROMPT_ID.encode())
    for source in _PIPELINE_FILES:
        h.update(source.read_bytes() if source.exists() else b"")
    return h.hexdigest()[:16]


def is_sample_deal(deal: dict, slug: str) -> bool:
    """A deal seeded from a sample: it carries the slug, or (seeded before slugs were stored) its id is the slug.

    Deals people create always get a random suffix on their id, so they never match.
    """
    return deal.get("sample_slug") == slug or (not deal.get("sample_slug") and deal.get("id") == slug)


def stale_samples(store: Storage, manifests: list[Path]) -> list[tuple[Path, str]]:
    """(manifest, version) for each sample that is missing or stored with another version."""
    out = []
    for path in manifests:
        manifest = _manifest(path)
        if manifest is None:
            continue
        slug, version = sample_slug(manifest, path.parent), sample_version(path)
        try:
            existing = store.get_deal(slug)
        except ValueError:
            continue
        if existing and not is_sample_deal(existing, slug):
            continue  # Never touch a deal that is not a sample.
        if not existing or existing.get("sample_version") != version:
            out.append((path, version))
    return out


def refresh_samples(store: Storage | None = None, samples_dir: Path = SAMPLES_DIR, owner: str | None = None) -> list[str]:
    """Re-seed sample deals whose manifest, PDFs, prompt or pipeline changed. Returns the refreshed ids.

    Idempotent: nothing happens when every stored version matches. Only one instance does the work:
    the others see the lock and leave it, and the next start finds the versions already current.
    Cached readings make this free; a sample with no cached reading is read in the background.
    """
    store = store or get_store()
    manifests = sorted(samples_dir.glob("*/manifest.json")) if samples_dir.exists() else []
    if not stale_samples(store, manifests):
        return []
    owner = owner or uuid.uuid4().hex
    if not store.acquire_lock(REFRESH_LOCK, owner, REFRESH_LOCK_TTL):
        print("Sample refresh: another instance holds the lock.")
        return []
    try:
        refreshed = []
        for path, version in stale_samples(store, manifests):  # Checked again under the lock.
            slug = sample_slug(_manifest(path) or {}, path.parent)
            # Upsert in place: the deal never disappears, document ids stay fixed, decisions are kept (L10).
            if seed_sample(path, store, version=version):
                refreshed.append(slug)
        return refreshed
    finally:
        store.release_lock(REFRESH_LOCK, owner)


def seed(store: Storage | None = None, samples_dir: Path = SAMPLES_DIR, county_dir: Path | None = None) -> list[str]:
    """Bring the sample deals (and the real county deals) up to date, or seed the Harbor Walk demo into an empty
    store without samples."""
    store = store or get_store()
    # COUNTY_DEALS=0 leaves the real county deals out (the test suite does, so tests never touch the network).
    if county_dir is None:
        county_dir = COUNTY_DIR if os.getenv("COUNTY_DEALS", "1") != "0" else Path("/nonexistent")
    if samples_dir.exists() and any(samples_dir.glob("*/manifest.json")):
        refreshed = refresh_samples(store, samples_dir)
        if county_dir.exists() and any(county_dir.glob("*/manifest.json")):
            refreshed += refresh_samples(store, county_dir)
        return refreshed
    if store.list_deals():
        return []
    return [seed_demo(store)]


def seed_sample(manifest_path: Path, store: Storage, version: str | None = None) -> str | None:
    """Create one deal from data/samples/<deal>/manifest.json and read its PDFs.

    A PDF with a cached reading is checked right away, so the deal is complete when this returns;
    one without is queued for the background reader.
    """
    manifest = _manifest(manifest_path)
    if manifest is None:
        return None
    folder = manifest_path.parent
    slug = sample_slug(manifest, folder)
    existing = store.get_deal(slug)
    real = bool(manifest.get("real"))
    # A real deal's reminders count from today; a made-up sample is frozen at its own as_of date.
    deal = create_deal(manifest.get("deal") or manifest.get("name") or manifest.get("project") or folder.name,
                       manifest.get("city") or "", manifest.get("owner") or manifest.get("developer"),
                       deal_id=slug, store=store, as_of=None if real else manifest.get("as_of"))
    if existing and existing.get("created_at"):
        deal["created_at"] = existing["created_at"]
    deal.update(sample_slug=slug, sample_version=version or sample_version(manifest_path))
    if real:
        deal.update(real=True, county=manifest.get("county"), source=manifest.get("source") or {})
    store.put_deal(deal)
    keep = set()
    stored = {d.get("sha256"): d for d in store.list_documents(slug)} if real else {}
    for entry in manifest.get("documents") or []:
        path = folder / (entry.get("file") or entry.get("filename") or "")
        data = path.read_bytes() if path.is_file() else (real_record_bytes(entry, folder, store, stored) if real else None)
        if data is None:
            continue
        doc_id = sample_doc_id(slug, entry, path)
        keep.add(doc_id)
        try:
            doc = add_document(deal["id"], path.name, data, entry.get("type"), entry.get("date"),
                               entry.get("title"), store=store, process=False, demo=False, doc_id=doc_id)
        except (pipeline.PdfError, ValueError) as err:
            print(f"Seed skipped {path.name}: {err}")
            continue
        if entry.get("url"):
            doc["source_url"] = entry["url"]
            store.put_document(deal["id"], doc)
        if pipeline.cached_reading(doc["sha256"]):
            process_document(deal["id"], doc["id"], store)
        elif not real:
            submit(deal["id"], doc["id"], store)
        else:
            # A real record with no saved reading waits for tools/county_read.py. It is marked, not queued, so a
            # restart never picks it up and spends on a live read.
            _set(store, deal["id"], doc, status="failed", error="Not read yet: this public record is waiting for its one-time reading.")
    for doc in store.list_documents(deal["id"]):  # Records no longer in the manifest. Visitor uploads go via the sweep.
        if doc["id"] not in keep and not doc.get("demo"):
            store.delete_document(deal["id"], doc["id"])
    return deal["id"]


COUNTY_CACHE_DIR = ROOT / "data" / "runtime" / "county"
RECORD_MAX_BYTES = 8_000_000


def record_bytes(entry: dict) -> bytes | None:
    """A real record's PDF: from the local cache, else downloaded from its official URL. Returned only if its
    SHA-256 matches the manifest, so a changed or replaced file is never read as the one we checked."""
    import urllib.request

    sha, url = str(entry.get("sha256") or ""), str(entry.get("url") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not url.startswith("https://"):
        return None
    cached = COUNTY_CACHE_DIR / f"{sha[:32]}.pdf"
    if cached.is_file():
        data = cached.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha:
            return data
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PromiseLedger/2.0 (open-source civic tool)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read(RECORD_MAX_BYTES + 1)
    except Exception as err:  # The record is listed as missing; the rest of the deal still seeds.
        print(f"Seed could not download a county record: {type(err).__name__}")
        return None
    if len(data) > RECORD_MAX_BYTES or hashlib.sha256(data).hexdigest() != sha:
        print("Seed skipped a county record whose file no longer matches its checked hash.")
        return None
    try:
        COUNTY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError:
        pass  # A read-only disk only costs a download next time.
    return data


BUNDLED_DIR = "files"  # data/county/<deal>/files/<sha256[:32]>.pdf: records the source now serves changed


def real_record_bytes(entry: dict, folder: Path, store: Storage, stored: dict) -> bytes | None:
    """A real record's checked PDF, from the first place that has it with the checked hash:
    1. a copy bundled with the repo, for records the county's server now regenerates on every download;
    2. the copy this deployment already stores (so a redeploy never drops a record it had);
    3. the local cache, or a fresh download from the official URL (record_bytes).
    Any other file is never used: the readings and checks belong to the file with this hash."""
    sha = str(entry.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        return None
    bundled = folder / BUNDLED_DIR / f"{sha[:32]}.pdf"
    if bundled.is_file():
        data = bundled.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha:
            return data
    have = stored.get(sha)
    if have and have.get("file_key"):
        try:
            data = store.get_blob(have["file_key"])
        except Exception:  # Fall through to the download.
            data = None
        if data and hashlib.sha256(data).hexdigest() == sha:
            return data
    return record_bytes(entry)


def sample_doc_id(slug: str, entry: dict, path: Path) -> str:
    """A fixed id per sample record (the manifest's "id", else a hash of deal and file name), so claim ids and
    decisions survive a refresh (L10)."""
    if entry.get("id") and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(entry["id"])):
        return str(entry["id"])
    return "d" + hashlib.sha256(f"{slug}/{path.name}".encode()).hexdigest()[:8]


def demo_pdf(document: dict) -> bytes:
    """Render a demo packet document as a PDF, one packet page per PDF page."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    story = [Paragraph(document["title"], styles["Title"]), Paragraph(document["date"], styles["Normal"]), Spacer(1, 12)]
    for i, page in enumerate(document["pages"]):
        if i:
            story.append(PageBreak())
        for para in page["paragraphs"]:
            story.extend([Paragraph(para, styles["BodyText"]), Spacer(1, 8)])
    SimpleDocTemplate(buf, pagesize=letter, title=document["title"], author="Promise Ledger demo").build(story)
    return buf.getvalue()


def seed_demo(store: Storage) -> str:
    """The reviewed Harbor Walk packet as one deal. Claims come from the hand-reviewed file, checked again here."""
    packet, reviewed = ledger.load_packet(), ledger.load_claims()
    deal = create_deal(packet["project"], packet["city"], packet.get("developer"), deal_id=DEMO_DEAL_ID, store=store)
    for document in packet["documents"]:
        data = demo_pdf(document)
        pages = pipeline.extract_pages(data)
        doc_id = document["id"]
        file_key = f"deals/{deal['id']}/{doc_id}.pdf"
        store.put_blob(file_key, data, "application/pdf")
        store.put_blob(f"deals/{deal['id']}/{doc_id}.pages.json", json.dumps(pages, ensure_ascii=False).encode(),
                       "application/json")
        claims = []
        for c in reviewed["claims"]:
            if c["document"] != doc_id:
                continue
            page = pipeline.locate(c["quote"], pages, c["page"])
            claims.append({**c, "document_title": document["title"], "page": page or c["page"],
                           "stated_page": c["page"], "page_corrected": bool(page and page != c["page"]),
                           "verified": page is not None})
        statuses = {c["status"] for c in claims}
        stage = max(statuses, key=ledger.STATUSES.index) if statuses else "proposed"
        stamp = now()
        store.put_document(deal["id"], {
            "id": doc_id, "filename": f"{doc_id}.pdf", "type": document["type"], "type_key": pipeline.type_key(document["type"]),
            "date": document["date"], "title": document["title"], "pages": len(pages),
            "scanned_pages": pipeline.scanned_pages(pages), "status": "done", "error": None, "file_key": file_key,
            "sha256": pipeline.file_hash(data), "stage": "signed" if document["signed"] else stage,
            "stage_reason": "Hand-reviewed demo record.", "signed": document["signed"],
            "signed_by": document.get("signed_by", []), "claims": claims, "model": "hand-reviewed",
            "counts": {"candidates": len(claims), "kept": sum(c["verified"] for c in claims), "page_corrected": 0,
                       "dropped": 0, "duplicates": 0},
            "created_at": stamp, "updated_at": stamp,
        })
    return deal["id"]
