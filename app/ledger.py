"""Load the demo packet, check every claim against it, and build the review page data.

Code does the checking here. No model is involved.
Run the checks from the command line with: python -m app.ledger
"""
from __future__ import annotations

import json
import re
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
    homes = claim.get("homes")
    if homes:
        for key in ("count", "of"):
            if key in homes and not re.search(rf"\b{homes[key]}\b", quote):
                problems.append(f"{label}: home {key} {homes[key]} is not in the quote")
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


def check_packet(packet: dict) -> list[str]:
    """Signed records must say who signed them. Unsigned records must not list signers."""
    problems = []
    for document in packet["documents"]:
        signers = document.get("signed_by", [])
        if document["signed"] and not signers:
            problems.append(f"{document['id']}: marked signed but no signer is listed")
        if not document["signed"] and signers:
            problems.append(f"{document['id']}: lists signers but is not marked signed")
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


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _homes(claim: dict) -> tuple[int | None, int | None]:
    """Home count and total from a claim's checked numbers, or (None, None)."""
    if claim.get("homes"):
        return claim["homes"].get("count"), claim["homes"].get("of")
    if claim.get("math"):
        return claim["math"]["equals"], claim["math"]["of"]
    return None, None


def build_summary(claims: list[dict], terms: list[dict], stages: list[dict], packet: dict) -> dict:
    """The at-a-glance numbers and sentences. Every figure is counted from the records."""
    units = _ordered([c for c in claims if c["topic"] == "units"])
    counted = [c for c in units if _homes(c)[0] is not None]
    # The home count comes from the furthest-along record that states one; the latest wins a tie.
    lead = max(counted, key=lambda c: (STATUSES.index(c["status"]), c["date"]), default=None)
    totals = [_homes(c)[1] for c in units if _homes(c)[1] is not None]
    homes = _homes(lead)[0] if lead else None
    total = max(totals) if totals else None

    furthest = max((STATUSES.index(c["status"]) for c in claims), default=None)
    furthest_status = STATUSES[furthest] if furthest is not None else None

    signed_docs = [d for d in packet["documents"] if d["signed"]]
    signers = sorted({name for d in signed_docs for name in d.get("signed_by", [])})
    city = packet["city"]
    developer = packet.get("developer")
    city_signed = any("City" in name or city in name for name in signers)

    differ = [t for t in terms if t["wording_differs"]]
    missing = [t for t in terms if not t["located"]]
    unsigned = [t for t in terms if t["located"] and not t["signed_claim_id"]]

    sentences = []
    if homes is not None:
        sentences.append(f"{homes} of {total} homes described as affordable." if total
                         else f"{homes} homes described as affordable.")
    if not signers:
        sentences.append("No signed record located.")
    elif city_signed:
        sentences.append(f"Signed by {', '.join(signers)}.")
    elif signers == [developer]:
        sentences.append(f"Signed by the developer ({developer}) only; no City-signed agreement located.")
    else:
        sentences.append(f"Signed by {', '.join(signers)} only; no City-signed agreement located.")
    sentences.append(f"{_count(len(differ), 'term differs', 'terms differ')} across records · "
                     f"{_count(len(missing), 'term', 'terms')} not located.")

    return {
        "homes_described": homes,
        "homes_total": total,
        "homes_claim_id": lead["id"] if lead else None,
        "furthest_status": furthest_status,
        "furthest_label": STAGE_LABELS[furthest_status] if furthest_status else NOT_LOCATED,
        "stages_total": len(stages),
        "terms_total": len(terms),
        "terms_differ": len(differ),
        "terms_not_located": len(missing),
        "terms_not_in_signed_record": len(unsigned),
        "signers": signers,
        "developer": developer,
        "signed_by_developer_only": bool(signers) and signers == [developer],
        "city_signed": city_signed,
        "sentences": sentences,
    }


def build_questions(claims: list[dict], terms: list[dict], stages: list[dict], summary: dict) -> list[dict]:
    """Open questions for staff, from terms that are missing or differ. Plain tasks, no verdicts."""
    by_id = {c["id"]: c for c in claims}
    questions = []
    for term in terms:
        label, lower = term["label"], term["label"].lower()
        if not term["located"]:
            questions.append({"key": term["key"], "tag": "not_located",
                              "text": f"{label}: not located. Ask staff for the agreement section on {lower}."})
        elif not term["signed_claim_id"]:
            questions.append({"key": term["key"], "tag": "not_located",
                              "text": f"{label}: not located in a signed record. "
                                      f"Ask staff whether a signed agreement covers {lower}."})
        if term["wording_differs"]:
            found = [by_id[i] for i in term["claim_ids"]]
            questions.append({"key": term["key"], "tag": "differs",
                              "text": f"{label}: wording differs across {len(found)} records "
                                      f"(\u201c{found[0]['value']}\u201d to \u201c{found[-1]['value']}\u201d). "
                                      "Confirm which wording is in the signed agreement."})
    if summary["signers"] and not summary["city_signed"]:
        questions.append({"key": "city_signature", "tag": "not_located",
                          "text": "City signature: an agreement signed by the City was not located. "
                                  "Ask staff for the City-signed agreement."})
    delivered = next((s for s in stages if s["status"] == "delivered"), None)
    if delivered and not delivered["claim_ids"]:
        questions.append({"key": "delivery", "tag": "not_located",
                          "text": f"Delivery: {delivered['note']} Ask staff for occupancy or compliance records."})
    return questions


def build_review() -> dict:
    packet = load_packet()
    reviewed = load_claims()
    claims = reviewed["claims"]
    problems = check_all(claims, packet) + check_packet(packet)
    failed = {p.split(":")[0] for p in problems}
    ordered = [{**c, "quote_checked": c["id"] not in failed} for c in _ordered(claims)]
    stages = build_stages(claims, reviewed["stage_notes"])
    terms = build_terms(claims)
    summary = build_summary(claims, terms, stages, packet)
    return {
        "notice": packet["notice"],
        "city": packet["city"],
        "project": packet["project"],
        "documents": packet["documents"],
        "topics": TOPICS,
        "developer": packet.get("developer"),
        "claims": ordered,
        "stages": stages,
        "terms": terms,
        "summary": summary,
        "questions": build_questions(claims, terms, stages, summary),
        "checks": {"total": len(claims), "passed": sum(c["quote_checked"] for c in ordered), "problems": problems},
    }


def main() -> int:
    review = build_review()
    for problem in review["checks"]["problems"]:
        print(f"FLAGGED  {problem}")
    print(f"{review['checks']['passed']} of {review['checks']['total']} claims passed")
    return 1 if review["checks"]["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
