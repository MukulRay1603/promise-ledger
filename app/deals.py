"""Deals and their documents: upload, background reading, per-deal review, reminders, export."""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

from app import ai, ledger, pipeline
from app.storage import Storage, get_store

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"
STATUSES = ("queued", "reading", "checking", "done", "failed")
DEMO_DEAL_ID = "harbor-walk-demo"

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reader")
run_inline = False  # Tests set this to process uploads synchronously.


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "deal"


# ---------------------------------------------------------------------------
# Deals

def create_deal(name: str, city: str, developer: str | None = None, deal_id: str | None = None,
                store: Storage | None = None) -> dict:
    store = store or get_store()
    deal_id = deal_id or f"{_slug(name)}-{uuid.uuid4().hex[:6]}"
    stamp = now()
    deal = {"id": deal_id, "name": name.strip(), "city": city.strip(), "developer": (developer or "").strip() or None,
            "created_at": stamp, "updated_at": stamp}
    store.put_deal(deal)
    return deal


def touch(deal_id: str, store: Storage) -> None:
    deal = store.get_deal(deal_id)
    if deal:
        deal["updated_at"] = now()
        store.put_deal(deal)


PUBLIC_DOC_FIELDS = ("id", "filename", "type", "type_key", "date", "date_note", "title", "pages", "status", "error",
                     "scanned_pages", "stage", "stage_reason", "signed", "signed_by", "counts", "model",
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
    return {**deal, "documents": [public_doc(d) for d in _sort_docs(store.list_documents(deal_id))]}


def list_deals(store: Storage | None = None) -> list[dict]:
    store = store or get_store()
    rows = []
    reminders = all_reminders(store)
    for deal in store.list_deals():
        docs = store.list_documents(deal["id"])
        review = build_deal_review(deal, docs)
        summary = review["summary"]
        upcoming = [r for r in reminders if r["deal_id"] == deal["id"]]
        nxt = upcoming[0] if upcoming else None
        rows.append({
            "id": deal["id"],
            "name": deal["name"],
            "city": deal["city"],
            "document_count": len(docs),
            "documents": len(docs),
            "documents_processing": sum(d.get("status") in ("queued", "reading", "checking") for d in docs),
            "claim_count": len(review["claims"]),
            "furthest_stage": summary["furthest_status"],
            "furthest_status": summary["furthest_status"],
            "terms_differ": summary["terms_differ"],
            "terms_not_located": summary["terms_not_located"],
            "next_reminder": {"date": nxt["date"], "due": nxt["date"], "text": nxt["text"], "kind": nxt["kind"]} if nxt else None,
            "updated_at": deal.get("updated_at"),
        })
    return sorted(rows, key=lambda r: r["updated_at"] or "", reverse=True)


# ---------------------------------------------------------------------------
# Documents

def add_document(deal_id: str, filename: str, data: bytes, type_: str | None = None, date_: str | None = None,
                 title: str | None = None, store: Storage | None = None, process: bool = True) -> dict:
    """Check and store the file, then queue it for reading. Raises pipeline.PdfError for a bad file."""
    store = store or get_store()
    pages = pipeline.extract_pages(data)  # Size, type and page limits are checked here, before anything is stored.
    if date_:
        date.fromisoformat(date_)  # ValueError is turned into a 422 by the API.
    doc_id = f"d{uuid.uuid4().hex[:8]}"
    stamp = now()
    file_key = f"deals/{deal_id}/{doc_id}.pdf"
    store.put_blob(file_key, data, "application/pdf")
    store.put_blob(f"deals/{deal_id}/{doc_id}.pages.json", json.dumps(pages, ensure_ascii=False).encode(), "application/json")
    doc = {
        "id": doc_id, "filename": Path(filename or "document.pdf").name, "type": (type_ or "").strip() or None,
        "date": date_ or None, "title": (title or "").strip() or None, "pages": len(pages),
        "scanned_pages": pipeline.scanned_pages(pages), "status": "queued", "error": None,
        "file_key": file_key, "sha256": pipeline.file_hash(data), "claims": [],
        "created_at": stamp, "updated_at": stamp,
    }
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
                     use_cache: bool = True) -> dict | None:
    """Read, check and save one document. Never raises; failures are recorded on the document."""
    store = store or get_store()
    doc = store.get_document(deal_id, doc_id)
    if not doc:
        return None
    try:
        pages = page_texts(deal_id, doc_id, store)
        if not any(len(p.strip()) >= pipeline.MIN_PAGE_CHARS for p in pages):
            return _set(store, deal_id, doc, status="failed",
                        error="No text layer was found. The pages look scanned; run OCR and upload again.")
        _set(store, deal_id, doc, status="reading", error=None)
        result, from_cache = pipeline.read_with_cache(doc["sha256"], pages, reader=reader, use_cache=use_cache)
        if result.mode != "live" or result.reading is None:
            return _set(store, deal_id, doc, status="failed", error=result.notice)
        _set(store, deal_id, doc, status="checking", model=result.model, from_cache=from_cache,
             tokens_in=result.tokens_in, tokens_out=result.tokens_out, cost_usd=result.cost_usd)
        deal = store.get_deal(deal_id) or {}
        known = [deal.get("developer") or "", f"City of {deal.get('city')}" if deal.get("city") else ""]
        checked = pipeline.verify_reading(result.reading, pages, doc, known)
        doc = _set(store, deal_id, doc, status="done", **checked)
        touch(deal_id, store)
        return doc
    except Exception as err:  # Record text is never logged.
        print(f"Processing {deal_id}/{doc_id} failed: {type(err).__name__}")
        return _set(store, deal_id, doc, status="failed", error=f"Processing failed ({type(err).__name__}).")


def resume_pending(store: Storage | None = None) -> int:
    """After a restart, queue documents that never finished."""
    store = store or get_store()
    count = 0
    for deal in store.list_deals():
        for doc in store.list_documents(deal["id"]):
            if doc.get("status") in ("queued", "reading", "checking"):
                submit(deal["id"], doc["id"], store)
                count += 1
    return count


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
        "delivered": "Certificate or occupancy records located." if by["delivered"]
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
        if q["tag"] == "differs" and q["key"] in keyed:
            t = keyed[q["key"]]
            q["text"] = (f"{t['label']}: wording differs across {len(t['differs_claim_ids'])} records "
                         f"(“{t['values'][0]}” to “{t['values'][-1]}”). "
                         "Confirm which wording is in the signed agreement.")
    for d in docs:
        if d.get("scanned_pages"):
            questions.append({"key": f"scanned-{d['id']}", "tag": "not_located",
                              "text": f"{d.get('title') or d.get('filename')}: pages {', '.join(map(str, d['scanned_pages']))} "
                                      "have no text layer and were not read. Ask for a text copy or run OCR."})
        if d.get("status") == "failed":
            questions.append({"key": f"failed-{d['id']}", "tag": "not_located",
                              "text": f"{d.get('filename')}: not read. {d.get('error') or ''}".strip()})
    end = term_end(claims, done)
    if end and end["date"] is None:
        questions.append({"key": "term_start", "tag": "not_located",
                          "text": f"Term: the signed record counts the term from an event with no date on file "
                                  f"(“{end['claim']['quote']}”). Ask staff for that date to set the end date."})
    counts = {k: sum((d.get("counts") or {}).get(k, 0) for d in done)
              for k in ("candidates", "kept", "page_corrected", "dropped", "duplicates", "absent")}
    by_id = {c["id"]: c for c in ordered}
    what_changed = [
        {"key": t["key"], "label": t["label"], "values": t["values"],
         "records": [{"claim_id": i, "value": by_id[i].get("compare") or by_id[i]["value"], "date": by_id[i]["date"],
                      "document_type": by_id[i]["document_type"], "status": by_id[i]["status"]}
                     for i in (t.get("differs_claim_ids") or t["claim_ids"])]}
        for t in terms if t["wording_differs"]
    ]
    return {
        "notice": "Every quote below was checked against the page text by code. Flagged for human review.",
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


def deal_review(deal_id: str, store: Storage | None = None, with_pages: bool = False) -> dict | None:
    store = store or get_store()
    deal = store.get_deal(deal_id)
    if not deal:
        return None
    return build_deal_review(deal, store.list_documents(deal_id), store=store, with_pages=with_pages)


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
    """Upcoming end dates and missing yearly checks, from signed agreement terms and certificate records."""
    today = today or date.today()
    done = [d for d in docs if d.get("status") == "done"]
    claims = [c for d in done for c in d.get("claims") or []]
    out = []

    def add(kind: str, when: date, text: str, source: str | None):
        # kind: term_end, missing_record (a yearly check that is past due and not on file) or other.
        out.append({"deal_id": deal["id"], "deal_name": deal["name"], "city": deal["city"], "kind": kind,
                    "check": "term" if kind == "term_end" else "yearly", "date": when.isoformat(),
                    "due": when.isoformat(), "overdue": when < today, "text": text, "claim_id": source})

    end = term_end(claims, done)
    if end and end["date"]:
        claim = end["claim"]
        how = ("as stated in the" if end["how"] == "stated"
               else f"{end['years']} years from the") + f" {claim['document_type'].lower()} dated {claim['date']}"
        verb = "ended" if end["date"] < today else "ends"
        add("term_end", end["date"], f"Affordability term {verb} {end['date'].isoformat()}, {how}.", claim["id"])

    signed_ids = {d["id"] for d in done if d.get("stage") == "signed"}
    reporting = [c for c in claims if c["topic"] == "reporting" and c["document"] in signed_ids]
    if reporting:
        rule = max(reporting, key=lambda c: c["date"] or "")
        due = _DUE_RE.search(rule["quote"])
        start = date.fromisoformat(rule["date"]) if rule["date"] else today
        month, day = (_MONTHS[due.group(1).lower()], int(due.group(2))) if due else (start.month, start.day)
        received = {date.fromisoformat(d["date"]).year for d in done
                    if d.get("type_key") == "certificate" and d.get("stage") == "delivered" and d.get("date")}
        last_year = end["date"].year + 1 if end and end["date"] else today.year + 1
        # Only the recent past is listed, so an old deal does not bury the queue.
        for year in range(max(start.year + 1, today.year - 1), min(today.year + 1, last_year) + 1):
            when = date(year, month, min(day, 28) if month == 2 else day)
            if year in received:
                continue
            if when < today:
                add("missing_record", when, f"Yearly certificate due {when.isoformat()} not located. "
                                          "Ask the owner or staff for it.", rule["id"])
            else:
                add("other", when, f"Yearly certificate due {when.isoformat()}.", rule["id"])
                break
    return out


def all_reminders(store: Storage | None = None, today: date | None = None) -> list[dict]:
    store = store or get_store()
    rows = []
    for deal in store.list_deals():
        rows.extend(deal_reminders(deal, store.list_documents(deal["id"]), today))
    return sorted(rows, key=lambda r: (not r["overdue"], r["date"]))


# ---------------------------------------------------------------------------
# Export

CLAIM_COLUMNS = ["Term", "Quote", "Document", "Date", "Page", "Stage", "Wording differs", "Verified"]
TERM_COLUMNS = ["Term", "Result", "Furthest stage", "Wording differs", "Values", "Signed record"]


def claim_rows(review: dict) -> list[list]:
    titles = {d["id"]: d.get("title") or d.get("filename") for d in review["documents"]}
    differs = {t["key"] for t in review["terms"] if t["wording_differs"]}
    return [[ledger.TOPICS.get(c["topic"], c["topic"]), c["quote"], titles.get(c["document"]) or c["document_type"],
             c["date"], c["page"], ledger.STAGE_LABELS[c["status"]], "Yes" if c["topic"] in differs else "No",
             "Yes" if c.get("quote_checked") else "No"] for c in review["claims"]]


def term_rows(review: dict) -> list[list]:
    return [[t["label"], t["result"], ledger.STAGE_LABELS.get(t["furthest_status"], "") if t["furthest_status"] else "",
             "Yes" if t["wording_differs"] else "No", "; ".join(t["values"]), "Yes" if t["signed_claim_id"] else "No"]
            for t in review["terms"]]


def _cell(value):
    """Stop spreadsheet formula injection from record text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_csv(review: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CLAIM_COLUMNS)
    writer.writerows([[_cell(v) for v in row] for row in claim_rows(review)])
    return buf.getvalue()


def export_xlsx(review: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    sheets = [("Claims", CLAIM_COLUMNS, claim_rows(review), [18, 70, 40, 12, 6, 12, 10, 10]),
              ("Terms", TERM_COLUMNS, term_rows(review), [18, 14, 14, 10, 50, 12])]
    for index, (name, header, rows, widths) in enumerate(sheets):
        ws = wb.active if index == 0 else wb.create_sheet()
        ws.title = name
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append([_cell(v) for v in row])
        for col, width in zip("ABCDEFGH", widths):
            ws.column_dimensions[col].width = width
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
    note = wb.create_sheet("About")
    note.append([f"{review['project']}, {review['city']}"])
    note.append([review["notice"]])
    note.append([f"Exported {now()}"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Share links

def create_share(deal_id: str, store: Storage | None = None) -> str:
    store = store or get_store()
    token = secrets.token_urlsafe(16)
    store.put_share(token, deal_id)
    return token


def shared_review(token: str, store: Storage | None = None) -> dict | None:
    store = store or get_store()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token or ""):
        return None
    deal_id = store.get_share(token)
    review = deal_review(deal_id, store) if deal_id else None
    if review is None:
        return None
    return {**review, "read_only": True, "share_token": token}


# ---------------------------------------------------------------------------
# Seeding

def seed(store: Storage | None = None, samples_dir: Path = SAMPLES_DIR) -> list[str]:
    """If there are no deals yet, add the sample deals (or the Harbor Walk demo). Returns seeded ids."""
    store = store or get_store()
    if store.list_deals():
        return []
    manifests = sorted(samples_dir.glob("*/manifest.json")) if samples_dir.exists() else []
    seeded = [sid for m in manifests if (sid := seed_sample(m, store))]
    if not seeded:
        seeded = [seed_demo(store)]
    return seeded


def seed_sample(manifest_path: Path, store: Storage) -> str | None:
    """Create one deal from data/samples/<deal>/manifest.json and queue its PDFs."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    folder = manifest_path.parent
    deal = create_deal(manifest.get("deal") or manifest.get("name") or manifest.get("project") or folder.name,
                       manifest.get("city") or "", manifest.get("owner") or manifest.get("developer"),
                       deal_id=manifest.get("slug") or manifest.get("id") or _slug(folder.name), store=store)
    for entry in manifest.get("documents") or []:
        path = folder / (entry.get("file") or entry.get("filename") or "")
        if not path.is_file():
            continue
        try:
            add_document(deal["id"], path.name, path.read_bytes(), entry.get("type"), entry.get("date"),
                         entry.get("title"), store=store)
        except (pipeline.PdfError, ValueError) as err:
            print(f"Seed skipped {path.name}: {err}")
    return deal["id"]


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
