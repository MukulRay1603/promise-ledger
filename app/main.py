import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from app import ai, deals, identity, ledger, pipeline  # noqa: E402  (needs env loaded first)
from app.storage import get_store  # noqa: E402

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Seed sample deals on an empty store and pick up uploads a restart interrupted.
    if os.getenv("SEED", "1") != "0":
        try:
            seeded = deals.seed()
            if seeded:
                print(f"Seeded deals: {', '.join(seeded)}")
            deals.resume_pending()
        except Exception as err:  # A storage problem must not stop the demo page from serving.
            print(f"Seeding skipped: {type(err).__name__}: {err}")
    yield


app = FastAPI(title="Promise Ledger", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class PastedText(BaseModel):
    text: str = Field(min_length=20, max_length=ai.MAX_INPUT_CHARS)


class NewDeal(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    developer: str | None = Field(default=None, max_length=120)


# Cloud Run reserves paths ending in "z", so /healthz only works locally. Use /api/health on the live service.
@app.get("/api/health")
@app.get("/healthz")
def healthz():
    checks = ledger.build_review()["checks"]
    model = ai.MODEL if os.getenv("GEMINI_API_KEY") else "saved output"
    return {"ok": not checks["problems"], "model": model, "claims": checks["total"],
            "storage": (os.getenv("STORAGE") or "local").lower()}


@app.get("/api/review")
def review():
    sample = ai.load_sample()
    return {
        **ledger.build_review(),
        "extraction": {"sample_text": sample["text"], "max_chars": ai.MAX_INPUT_CHARS},
    }


@app.post("/api/extract", response_model=ai.ExtractResult)
def extract(pasted: PastedText):
    # Pasted text is not stored or logged.
    return ai.extract(pasted.text)


# ---------------------------------------------------------------------------
# Deals

def _deal_or_404(deal_id: str) -> dict:
    try:
        deal = get_store().get_deal(deal_id)
    except ValueError:
        deal = None
    if not deal:
        raise HTTPException(404, "Deal not found.")
    return deal


def _doc_or_404(deal_id: str, doc_id: str) -> dict:
    _deal_or_404(deal_id)
    try:
        doc = get_store().get_document(deal_id, doc_id)
    except ValueError:
        doc = None
    if not doc:
        raise HTTPException(404, "Document not found.")
    return doc


@app.get("/api/deals")
def list_deals():
    return deals.list_deals()


@app.post("/api/deals", status_code=201)
def create_deal(new: NewDeal):
    return deals.create_deal(new.name, new.city, new.developer)


@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: str):
    _deal_or_404(deal_id)
    return deals.get_deal_detail(deal_id)


@app.post("/api/deals/{deal_id}/documents", status_code=202)
async def upload_document(deal_id: str, file: UploadFile = File(...), type: str | None = Form(None),
                          date_: str | None = Form(None, alias="date"), title: str | None = Form(None)):
    _deal_or_404(deal_id)
    data = await file.read(pipeline.MAX_PDF_BYTES + 1)
    if len(data) > pipeline.MAX_PDF_BYTES:
        raise HTTPException(413, "The file is larger than 20 MB.")
    if date_:
        try:
            date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(422, "Date must be YYYY-MM-DD.")
    try:
        doc = deals.add_document(deal_id, file.filename or "document.pdf", data, type, date_ or None, title)
    except pipeline.PdfError as err:
        raise HTTPException(422, str(err))
    return deals.public_doc(get_store().get_document(deal_id, doc["id"]) or doc)


@app.get("/api/deals/{deal_id}/documents/{doc_id}")
def get_document(deal_id: str, doc_id: str):
    return deals.public_doc(_doc_or_404(deal_id, doc_id))


@app.get("/api/deals/{deal_id}/documents/{doc_id}/file")
def document_file(deal_id: str, doc_id: str):
    doc = _doc_or_404(deal_id, doc_id)
    data = get_store().get_blob(doc["file_key"])
    if data is None:
        raise HTTPException(404, "File not found.")
    name = "".join(ch for ch in (doc.get("filename") or "document.pdf") if ch.isprintable() and ch not in '"\\')
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{name}"', "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600"})


@app.get("/api/deals/{deal_id}/documents/{doc_id}/pages/{n}")
def document_page(deal_id: str, doc_id: str, n: int):
    _doc_or_404(deal_id, doc_id)
    pages = deals.page_texts(deal_id, doc_id, get_store())
    if not 1 <= n <= len(pages):
        raise HTTPException(404, "Page not found.")
    return {"page": n, "pages": len(pages), "text": pages[n - 1]}


@app.get("/api/deals/{deal_id}/review")
def deal_review(deal_id: str, request: Request):
    _deal_or_404(deal_id)
    return deals.deal_review(deal_id, session=identity.demo_session(request))


@app.get("/api/deals/{deal_id}/export.xlsx")
def export_xlsx(deal_id: str, request: Request):
    _deal_or_404(deal_id)
    data = deals.export_xlsx(deals.deal_review(deal_id, session=identity.demo_session(request)))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{deal_id}-promise-ledger.xlsx"'})


@app.get("/api/deals/{deal_id}/decisions")
def get_decisions(deal_id: str, request: Request):
    _deal_or_404(deal_id)
    return deals.deal_review(deal_id, session=identity.demo_session(request))["decisions"]


class DecisionIn(BaseModel):
    target_type: str = Field(max_length=20)
    target_id: str = Field(min_length=1, max_length=120)
    decision: str = Field(max_length=20)
    note: str | None = Field(default=None, max_length=deals.MAX_NOTE + 200)


def _rate_limited(request: Request) -> None:
    key = identity.demo_session(request) or (request.client.host if request.client else "unknown")
    if not identity.decision_limit.allow(key):
        raise HTTPException(429, "That is a lot of decisions in one minute. Wait a moment and try again.")


@app.post("/api/deals/{deal_id}/decisions", status_code=201)
def post_decision(deal_id: str, body: DecisionIn, request: Request):
    _deal_or_404(deal_id)
    _rate_limited(request)
    try:
        reviewer = identity.current_reviewer(request)
        event = deals.add_decision(deal_id, body.model_dump(), reviewer)
    except (deals.DecisionError, identity.IdentityError) as err:
        raise HTTPException(422, str(err)) from err
    return {"event": event, **deals.deal_review(deal_id, session=reviewer["session"])["decisions"]}


@app.delete("/api/deals/{deal_id}/decisions")
def reset_decisions(deal_id: str, request: Request):
    """Reset this browser's review of a sample deal. Shared deals cannot be reset from here."""
    _deal_or_404(deal_id)
    _rate_limited(request)
    session = identity.demo_session(request)
    try:
        deals.reset_decisions(deal_id, session)
    except deals.DecisionError as err:
        raise HTTPException(409, str(err)) from err
    return deals.deal_review(deal_id, session=session)["decisions"]


@app.get("/api/deals/{deal_id}/export.json")
def export_preview(deal_id: str, request: Request):
    """The rows the Excel and CSV downloads hold, for the in-app preview."""
    _deal_or_404(deal_id)
    return deals.export_preview(deals.deal_review(deal_id, session=identity.demo_session(request)), deal_id)


@app.get("/api/deals/{deal_id}/export.csv")
def export_csv(deal_id: str, request: Request):
    _deal_or_404(deal_id)
    text = deals.export_csv(deals.deal_review(deal_id, session=identity.demo_session(request)))
    return Response("﻿" + text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{deal_id}-promise-ledger.csv"'})


@app.post("/api/deals/{deal_id}/share")
def share(deal_id: str, request: Request):
    _deal_or_404(deal_id)
    token = deals.create_share(deal_id, session=identity.demo_session(request))
    base = os.getenv("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
    return {"url": f"{base}/r/{token}", "token": token}


def _shared_or_404(token: str) -> dict:
    data = deals.shared_review(token)
    if data is None:
        raise HTTPException(404, "This link is not valid.")
    return data


@app.get("/api/share/{token}")
@app.get("/api/r/{token}")
def shared_json(token: str):
    return JSONResponse(_shared_or_404(token), headers={"X-Robots-Tag": "noindex"})


@app.get("/r/{token}", response_class=HTMLResponse)
def shared(token: str):
    """Read-only review page. The review ships in #review-data with read_only: true; JSON is at /api/share/{token}."""
    data = _shared_or_404(token)
    return HTMLResponse(_page_with(data), headers={"X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})


# Explainer videos. MEDIA_BASE_URL points at a public bucket folder; empty means /static/media/.
MEDIA_DIR = STATIC / "media"
MEDIA_EXTS = ("mp4", "vtt", "jpg")
_media_cache: dict = {"at": 0.0, "base": None, "ready": {}}


def _remote_ready(base: str, slugs: list[str]) -> dict:
    """HEAD each file once every few minutes, so missing videos keep their placeholder."""
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    if _media_cache["base"] == base and time.time() - _media_cache["at"] < 300:
        return _media_cache["ready"]

    def exists(url: str) -> bool:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=3) as res:
                return res.status == 200
        except Exception:
            return False

    urls = [f"{base}{slug}.{ext}" for slug in slugs for ext in MEDIA_EXTS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = dict(zip(urls, pool.map(exists, urls)))
    ready = {slug: all(found[f"{base}{slug}.{ext}"] for ext in MEDIA_EXTS) for slug in slugs}
    _media_cache.update(at=time.time(), base=base, ready=ready)
    return ready


@app.get("/api/media")
def media():
    manifest = json.loads((MEDIA_DIR / "videos.json").read_text(encoding="utf-8"))["videos"]
    slugs = [video["slug"] for video in manifest]
    base = os.getenv("MEDIA_BASE_URL", "").strip()
    if base:
        base = base.rstrip("/") + "/"
        ready = _remote_ready(base, slugs)
    else:
        base = "/static/media/"
        ready = {slug: all((MEDIA_DIR / f"{slug}.{ext}").is_file() for ext in MEDIA_EXTS) for slug in slugs}
    return {"base": base, "videos": [{"slug": v["slug"], "title": v["title"], "ready": ready[v["slug"]]} for v in manifest]}


@app.get("/api/reminders")
def reminders():
    return deals.all_reminders()


DATA_SLOT = '<script id="review-data" type="application/json"></script>'


def _page_with(data: dict) -> str:
    # The review data ships inside the page so the dashboard draws on first paint without moving.
    # "<" is escaped so record text can never close the script tag.
    raw = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    return page.replace(DATA_SLOT, DATA_SLOT.replace("></script>", f">{raw}</script>"))


@app.get("/", response_class=HTMLResponse)
def index():
    return _page_with(review())


app.mount("/static", StaticFiles(directory=STATIC), name="static")
