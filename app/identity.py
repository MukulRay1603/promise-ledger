"""Who is acting. One seam, so real sign-in can replace it without touching the decision code.

Today there are no accounts. The browser sends:
- X-Demo-Session: a random id it keeps in localStorage. On sample deals, decisions are scoped to it, so one
  visitor's review never shows for another visitor.
- X-Reviewer-Name: the name the reviewer typed, URL-encoded.

Later, current_reviewer() can read a verified Firebase ID token instead and return the same shape.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

SESSION_HEADER = "X-Demo-Session"
NAME_HEADER = "X-Reviewer-Name"
MAX_NAME = 80
_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class IdentityError(ValueError):
    """The request does not say who is acting."""


def demo_session(request) -> str | None:
    """The browser's demo session id, from the header (or ?session= for plain download links)."""
    value = request.headers.get(SESSION_HEADER) or request.query_params.get("session") or ""
    return value if _SESSION_RE.fullmatch(value) else None


def current_reviewer(request) -> dict:
    """The reviewer behind this request: {"id", "name"}.

    For now the name is what the browser sends. The id is the demo session when there is one,
    otherwise "local:<name>".
    """
    raw = request.headers.get(NAME_HEADER) or ""
    try:
        name = unquote(raw, errors="strict")
    except UnicodeDecodeError as err:
        raise IdentityError("Enter a reviewer name.") from err
    name = _CONTROL.sub("", name).strip()
    if not name:
        raise IdentityError("Enter a reviewer name.")
    if len(name) > MAX_NAME:
        raise IdentityError(f"Keep the reviewer name under {MAX_NAME} characters.")
    session = demo_session(request)
    return {"id": f"demo:{session}" if session else f"local:{name.lower()}", "name": name, "session": session}
