import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from app import ai, ledger  # noqa: E402  (needs env loaded first)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Promise Ledger")


class PastedText(BaseModel):
    text: str = Field(min_length=20, max_length=ai.MAX_INPUT_CHARS)


@app.get("/healthz")
def healthz():
    checks = ledger.build_review()["checks"]
    model = ai.MODEL if os.getenv("GEMINI_API_KEY") else "saved output"
    return {"ok": not checks["problems"], "model": model, "claims": checks["total"]}


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
