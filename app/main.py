import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from app import ai  # noqa: E402  (needs env loaded first)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Promise Ledger")


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


@app.get("/healthz")
def healthz():
    model = ai.MODEL if os.getenv("GEMINI_API_KEY") else "mock"
    return {"ok": True, "model": model, "sources": len(ai.load_sources())}


@app.post("/api/ask", response_model=ai.Answer)
def ask(q: Question):
    # Inputs are not stored or logged (privacy rubric item).
    return ai.ask(q.question)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
