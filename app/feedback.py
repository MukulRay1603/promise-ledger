"""Feedback from people testing the site (#/test).

Each response is appended to one JSON-lines file in storage. Nothing that identifies the tester is kept unless they
choose to be quoted with their name: no IP address, no session id, no browser details. Reading the responses back
needs FEEDBACK_TOKEN, which only whoever runs the server sets; without it the read route answers 404.
"""
from __future__ import annotations

import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.storage import Storage, get_store

KEY = "feedback/responses.jsonl"
LOCK = "feedback-append"

Role = Literal["staff", "council", "nonprofit", "resident", "journalist", "student", "other"]
Found = Literal["yes", "partly", "no", "skipped"]
Quote = Literal["no", "anonymous", "named"]


class Timed(BaseModel):
    seconds: int | None = Field(default=None, ge=0, le=7200)
    found: Found = "skipped"
    answer: str = Field(default="", max_length=300)


class FeedbackIn(BaseModel):
    role: Role
    by_hand: Timed = Timed()
    with_tool: Timed = Timed()
    county_task: Timed = Timed()
    ask_rating: int | None = Field(default=None, ge=1, le=5)
    easy_to_learn: int | None = Field(default=None, ge=1, le=5)
    trust: int | None = Field(default=None, ge=1, le=5)
    would_use: int | None = Field(default=None, ge=1, le=5)
    confusing: str = Field(default="", max_length=2000)
    more_useful: str = Field(default="", max_length=2000)
    quote: Quote = "no"
    name: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=120)


def save(entry: FeedbackIn, store: Storage | None = None) -> dict:
    store = store or get_store()
    row = entry.model_dump()
    if row["quote"] != "named":  # A name is kept only when the tester asked to be quoted by name.
        row["name"] = row["title"] = ""
    row = {"id": uuid.uuid4().hex[:12], "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
    owner = uuid.uuid4().hex
    for _ in range(50):
        if store.acquire_lock(LOCK, owner, 10):
            break
        import time

        time.sleep(0.1)
    else:
        raise RuntimeError("feedback store busy")
    try:
        current = store.get_blob(KEY) or b""
        store.put_blob(KEY, current + (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"), "application/x-ndjson")
    finally:
        store.release_lock(LOCK, owner)
    return {"id": row["id"]}


def allowed(token: str | None) -> bool:
    expected = os.getenv("FEEDBACK_TOKEN") or ""
    return bool(expected) and bool(token) and hmac.compare_digest(expected, token)


def read_all(store: Storage | None = None) -> list[dict]:
    data = (store or get_store()).get_blob(KEY) or b""
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
