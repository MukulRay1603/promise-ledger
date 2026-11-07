"""Load the demo packet, check every claim against it, and build the review page data.

Code does the checking here. No model is involved.
Run the checks from the command line with: python -m app.ledger
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"

STATUSES = ("proposed", "supported", "signed", "delivered")
STAGE_LABELS = {
    "proposed": "Proposed",
    "supported": "Supported",
    "signed": "Signed",
    "delivered": "Delivered",
}
TERMS = {
    "units": "Units",
    "income_basis": "Income basis",
    "rent_limits": "Rent limits",
    "term": "Term",
    "responsible_party": "Responsible party",
    "reporting": "Reporting",
    "remedies": "Remedies",
}
TOPICS = {**TERMS, "public_support": "Public support"}
NOT_LOCATED = "Not located"


@lru_cache
def load_packet() -> dict:
    return json.loads((DATA_DIR / "packet.json").read_text(encoding="utf-8"))


@lru_cache
def load_claims() -> dict:
    return json.loads((DATA_DIR / "claims.json").read_text(encoding="utf-8"))


def check_claim(claim: dict, packet: dict) -> list[str]:
    """Return every problem found with one claim. An empty list means it passed."""
    label = claim.get("id", "claim with no id")
    documents = {d["id"]: d for d in packet["documents"]}
    document = documents.get(claim.get("document"))
    if document is None:
        return [f"{label}: document {claim.get('document')!r} is not in the packet"]

    problems = []
    if claim.get("document_type") != document["type"]:
        problems.append(f"{label}: document type does not match the packet")
    if claim.get("date") != document["date"]:
        problems.append(f"{label}: date does not match the packet")
    if claim.get("topic") not in TOPICS:
        problems.append(f"{label}: unknown topic {claim.get('topic')!r}")
    if claim.get("status") not in STATUSES:
        problems.append(f"{label}: unknown status {claim.get('status')!r}")

    # A status can only be as far along as the cited record allows.
    if claim.get("status") == "signed" and not document["signed"]:
        problems.append(f"{label}: marked signed but the cited document is not signed")
    if claim.get("status") == "delivered":
        problems.append(f"{label}: marked delivered but the packet has no delivery records")

    page = next((p for p in document["pages"] if p["page"] == claim.get("page")), None)
    quote = claim.get("quote", "")
    if page is None:
        problems.append(f"{label}: page {claim.get('page')} is not in {document['id']}")
    elif not quote or not any(quote in paragraph for paragraph in page["paragraphs"]):
        problems.append(f"{label}: quote not found on page {claim['page']} of {document['id']}")

    if claim.get("wording", "").lower() not in quote.lower():
        problems.append(f"{label}: wording {claim.get('wording')!r} is not in the quote")

    math = claim.get("math")
    if math and math["percent"] * math["of"] != math["equals"] * 100:
        problems.append(f"{label}: {math['percent']} percent of {math['of']} is not {math['equals']}")
    vote = claim.get("vote")
    if vote and vote["yes"] + vote["no"] != vote["present"]:
        problems.append(f"{label}: vote count does not add up to members present")
    return problems


def check_all(claims: list[dict], packet: dict) -> list[str]:
    problems = []
    seen = set()
    for claim in claims:
        if claim.get("id") in seen:
            problems.append(f"{claim['id']}: duplicate id")
        seen.add(claim.get("id"))
        problems.extend(check_claim(claim, packet))
    return problems


def _ordered(claims: list[dict]) -> list[dict]:
    return sorted(claims, key=lambda c: (c["date"], c["id"]))


def build_terms(claims: list[dict]) -> list[dict]:
    """One row per term. A term with no claims reads "Not located"; nothing is filled in."""
    rows = []
    for key, label in TERMS.items():
        found = _ordered([c for c in claims if c["topic"] == key])
        values = list(dict.fromkeys(c["value"] for c in found))
        furthest = max((STATUSES.index(c["status"]) for c in found), default=None)
        signed = [c for c in found if c["status"] == "signed"]
        rows.append({
            "key": key,
            "label": label,
            "located": bool(found),
            "result": "Located" if found else NOT_LOCATED,
            "wording_differs": len(values) > 1,
            "values": values,
            "furthest_status": STATUSES[furthest] if furthest is not None else None,
            "claim_ids": [c["id"] for c in found],
            "signed_claim_id": signed[-1]["id"] if signed else None,
        })
    return rows


def build_stages(claims: list[dict], notes: dict) -> list[dict]:
    """Group claims by the status a reviewer gave them. No status is carried forward."""
    stages = []
    for status in STATUSES:
        found = _ordered([c for c in claims if c["status"] == status])
        stages.append({
            "status": status,
            "label": STAGE_LABELS[status],
            "note": notes.get(status, ""),
            "result": "Located" if found else NOT_LOCATED,
            "claim_ids": [c["id"] for c in found],
        })
    return stages


def build_review() -> dict:
    packet = load_packet()
    reviewed = load_claims()
    claims = reviewed["claims"]
    problems = check_all(claims, packet)
    failed = {p.split(":")[0] for p in problems}
    return {
        "notice": packet["notice"],
        "city": packet["city"],
        "project": packet["project"],
        "documents": packet["documents"],
        "topics": TOPICS,
        "claims": [{**c, "quote_checked": c["id"] not in failed} for c in _ordered(claims)],
        "stages": build_stages(claims, reviewed["stage_notes"]),
        "terms": build_terms(claims),
        "checks": {"total": len(claims), "passed": len(claims) - len(failed), "problems": problems},
    }


def main() -> int:
    review = build_review()
    for problem in review["checks"]["problems"]:
        print(f"FLAGGED  {problem}")
    print(f"{review['checks']['passed']} of {review['checks']['total']} claims passed")
    return 1 if review["checks"]["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
