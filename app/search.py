"""Search every checked quote across the real county deals.

The index (data/county/search-index.json) is built offline by tools/county_index.py: one Gemini embedding per
checked quote. At query time only the question is embedded. With no key, or if the call fails, the same quotes are
searched by keyword instead, and the reply says which search ran. Results are quotes that code already found word for
word on their page; search never writes or summarises anything.
"""
from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from app import ai

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "county" / "search-index.json"
EMBED_MODEL = os.getenv("EMBED_MODEL") or "gemini-embedding-001"
DIM = 256
MAX_RESULTS = 12
MIN_SCORE = 0.73  # Spot checks on the county index (Nov 18): related clauses scored 0.74-0.85, unrelated ones about 0.71.
_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by for from has have in is it of on or that the this to was were will with which "
            "who what when where how does do any all".split())


@lru_cache(maxsize=1)
def load_index() -> dict:
    if not INDEX.is_file():
        return {"items": [], "model": None}
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    for item in data["items"]:
        v = item.get("v") or []
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        item["_v"] = [x / norm for x in v]
    return data


def embed(texts: list[str], task: str) -> list[list[float]]:
    from google.genai import types

    client = ai._client(os.environ["GEMINI_API_KEY"], 15_000)
    out = client.models.embed_content(model=EMBED_MODEL, contents=texts,
                                      config=types.EmbedContentConfig(output_dimensionality=DIM, task_type=task))
    return [list(e.values) for e in out.embeddings]


def _keywords(q: str) -> list[str]:
    return [w for w in _WORD.findall(q.lower()) if w not in _STOP and len(w) > 2]


def _public(item: dict, score: float) -> dict:
    return {k: item[k] for k in ("deal_id", "deal", "file", "claim_id", "topic", "document", "date", "page", "quote")} | {
        "score": round(score, 3)}


def search(q: str) -> dict:
    q = " ".join(q.split())[:200]
    index = load_index()
    items = index["items"]
    if not q or not items:
        return {"mode": "none", "query": q, "results": [], "notice": "Nothing to search yet."}
    if os.getenv("GEMINI_API_KEY") and index.get("model") and ai._allow_live_call():
        try:
            qv = embed([q], "RETRIEVAL_QUERY")[0]
            norm = math.sqrt(sum(x * x for x in qv)) or 1.0
            qv = [x / norm for x in qv]
            scored = sorted(((sum(a * b for a, b in zip(qv, it["_v"])), it) for it in items), key=lambda p: -p[0])
            hits = [_public(it, s) for s, it in scored[:MAX_RESULTS] if s >= MIN_SCORE]
            return {"mode": "meaning", "query": q, "results": hits,
                    "notice": f"Matched by meaning across {len(items)} checked quotes. Every result is a quote found word "
                              "for word on its page; open it to read it in context."}
        except Exception as err:  # The question is never logged.
            print(f"County search fell back to keywords: {type(err).__name__}")
    words = _keywords(q)
    scored = []
    for it in items:
        text = it["quote"].lower()
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}(?:s|es|ed|ing|al)?\b", text))  # "rent", "rental"; not "renew"
        if hits:
            scored.append((hits / len(words), it))
    scored.sort(key=lambda p: -p[0])
    return {"mode": "keywords", "query": q, "results": [_public(it, s) for s, it in scored[:MAX_RESULTS]],
            "notice": f"Matched by keywords across {len(items)} checked quotes."}
