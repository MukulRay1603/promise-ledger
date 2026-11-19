"""Draft a public-records request for the records a deal is missing.

The draft is built by code from the review: which records to ask for (deals.next_records), which terms were not
found, and which records are already on file, so a clerk is not asked for what we already have. It is always
available, with or without a model.

"Polish" asks the model to rewrite the same draft in plainer, more courteous words. Its answer is kept only if it
keeps every requested record and invents nothing: every number, date and file number in it must already be in the
draft, and it may add no link. Otherwise the code draft is returned with a note. Nothing is sent: a person reviews,
edits and sends the letter themselves.
"""
from __future__ import annotations

import os
import re

from pydantic import BaseModel, Field

from app import ai

TIMEOUT_MS = 30_000


class LetterIn(BaseModel):
    polish: bool = False


class Letter(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=6000)


def _law(review: dict, deal: dict) -> str:
    county = (deal.get("county") or "") + " " + (review.get("city") or "")
    if "Maryland" in county or ", MD" in county or "Prince George" in county:
        return "the Maryland Public Information Act (General Provisions Article, Title 4)"
    return "your state's public records law"


# How each kind of missing record is asked for in the letter. The review's "why" text speaks to our user; these
# lines speak to the records office.
ASK = {
    "agreement": "The signed regulatory, development or PILOT agreement, with its signature pages",
    "agreement_full": "The complete signed agreement, with every page, exhibit and schedule, and any recorded covenant",
    "exhibit": "The affordability exhibit or term sheet to the agreement",
    "staff_report": "The staff report to the council on this project",
    "minutes": "The council minutes or resolution that record the vote on this project",
    "delivery": "Any certificate of occupancy, compliance report or annual certification showing the homes were built and leased",
}


def draft(deal: dict, review: dict) -> dict:
    """The request letter, built by rule from the review. Never calls a model."""
    items = review.get("next_records") or []
    missing = [t["label"] for t in review.get("terms", []) if not t.get("located")]
    source = deal.get("source") or {}
    on_file = [d for d in review.get("documents", []) if d.get("status") == "done"]
    project = deal.get("name") or review.get("project") or "this project"
    ref = f"Council file {source['file']}, " if source.get("file") else ""
    subject = f"Public records request: {ref}{project}"
    lines = [
        "To the custodian of records:",
        "",
        f"Under {_law(review, deal)}, I request copies of the following records about {project}"
        + (f" ({source['file']})" if source.get("file") else "") + ":",
        "",
    ]
    if items:
        for n, item in enumerate(items, 1):
            terms = f" In particular, the parts that state: {', '.join(t.lower() for t in item['terms'])}." if item.get("terms") else ""
            lines.append(f"{n}. {ASK.get(item.get('key'), item['record'])}.{terms}")
    else:
        lines.append("1. Any record that reports whether the affordable homes were built and leased, and any later "
                     "amendment to the agreement.")
    if missing:
        lines += ["", f"I have not found wording for these terms in the records I have: {', '.join(missing)}."]
    if on_file:
        lines += ["", "I already have these records, so there is no need to send them again:"]
        lines += [f"- {d.get('title') or d.get('filename')}" + (f" ({d['date']})" if d.get("date") else "") for d in on_file[:12]]
        if len(on_file) > 12:
            lines.append(f"- and {len(on_file) - 12} more")
    lines += [
        "",
        "Electronic copies are fine. If any part of a record is withheld, please tell me which part and the reason.",
        "",
        "Thank you,",
        "[Your name]",
        "[Your email or phone]",
    ]
    return {"mode": "template", "subject": subject, "body": "\n".join(lines),
            "requested": [ASK.get(i.get("key"), i["record"]) for i in items],
            "notice": "Drafted by code from this deal's review. Check it, add your name, and send it yourself."}


_TOKENS = re.compile(r"\b(?:[A-Z]{1,3}-\d[\d-]*|\d[\d,./-]*%?)")
_LINK = re.compile(r"https?://|www\.", re.I)

PROMPT = """You edit a public-records request letter so it reads clearly and courteously.
Rules:
- Keep every numbered request, in the same order, and keep each record's name exactly as written.
- Do not add any fact: no new numbers, dates, names, file numbers, laws, deadlines or links.
- Keep the placeholders [Your name] and [Your email or phone] exactly.
- Keep it short and plain. Return JSON with "subject" and "body"."""


def check(polished: Letter, base: dict) -> str | None:
    """Why the model's version cannot be used, or None if it keeps the draft's facts and adds none."""
    source = base["subject"] + "\n" + base["body"]
    text = polished.subject + "\n" + polished.body
    new = set(_TOKENS.findall(text)) - set(_TOKENS.findall(source))
    if new:
        return "it added numbers or dates that are not in the draft"
    if _LINK.search(text):
        return "it added a link"
    if any(record not in polished.body for record in base["requested"]):
        return "it dropped or renamed a requested record"
    if "[Your name]" not in polished.body:
        return "it removed the signature placeholder"
    return None


def _call(base: dict, model: str) -> Letter:
    from google.genai import types

    client = ai._client(os.environ["GEMINI_API_KEY"], TIMEOUT_MS)
    response = client.models.generate_content(
        model=model,
        contents=f"<subject>{base['subject']}</subject>\n<letter>\n{base['body']}\n</letter>",
        config=types.GenerateContentConfig(system_instruction=PROMPT, response_mime_type="application/json",
                                           response_schema=Letter, temperature=0.2, max_output_tokens=4096),
    )
    return Letter.model_validate_json(response.text)


def letter(deal: dict, review: dict, polish: bool = False) -> dict:
    base = draft(deal, review)
    if not polish:
        return base
    if not os.getenv("GEMINI_API_KEY"):
        return {**base, "notice": "AI polish is off on this server, so this is the code draft. " + base["notice"]}
    if not ai._allow_live_call():
        return {**base, "notice": "The AI limit was reached for this minute, so this is the code draft."}
    model = ai.MODEL
    try:
        try:
            polished = _call(base, model)
        except Exception:
            if ai.FALLBACK_MODEL == ai.MODEL or not ai._allow_live_call():
                raise
            model = ai.FALLBACK_MODEL
            polished = _call(base, model)
    except Exception as err:  # The letter text is never logged.
        print(f"Letter polish fell back to the draft: {type(err).__name__}")
        return {**base, "notice": "The AI edit did not finish, so this is the code draft."}
    why = check(polished, base)
    if why:
        return {**base, "notice": f"The AI edit was not used because {why}. This is the code draft."}
    return {**base, "mode": "polished", "subject": polished.subject, "body": polished.body, "model": model,
            "notice": f"Edited for clarity by {model}, then checked: every requested record is kept and no number, "
                      "date or link was added. Check it, add your name, and send it yourself."}
