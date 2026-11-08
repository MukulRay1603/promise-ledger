"""Read one deal PDF, check what the model proposed, and decide stages by rule.

1. Store the file.                         (app/deals.py)
2. Extract text per page with pypdf; flag pages with no text.
3. Ask the model for candidates            (app/ai.read_document)
4. Verify in code: the quote must be on the stated page, else on another page
   (page corrected), else dropped.
5. Stage comes from the document type and checked signatures, never the model alone.
6. The deal review is rebuilt from the stored, verified claims.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

from app import ai, ledger

ROOT = Path(__file__).resolve().parent.parent
READINGS_DIR = Path(os.getenv("READINGS_DIR") or ROOT / "data" / "readings")

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 60
MIN_PAGE_CHARS = 20  # Fewer characters than this and the page is treated as scanned.

# ---------------------------------------------------------------------------
# Page text

class PdfError(ValueError):
    """The upload is not a PDF we can read. The message is safe to show."""


def extract_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(data) > MAX_PDF_BYTES:
        raise PdfError("The file is larger than 20 MB.")
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise PdfError("The file is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfError("The PDF is password protected.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfError(f"The PDF has more than {MAX_PDF_PAGES} pages.")
        return [(page.extract_text() or "") for page in reader.pages]
    except PdfError:
        raise
    except (PdfReadError, Exception) as err:
        raise PdfError(f"The PDF could not be read ({type(err).__name__}).") from err


def scanned_pages(pages: list[str]) -> list[int]:
    return [i for i, text in enumerate(pages, 1) if len(text.strip()) < MIN_PAGE_CHARS]


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Quote checks

_QUOTES = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
           "“": '"', "”": '"', "„": '"', "″": '"', "«": '"', "»": '"',
           "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
           " ": " ", "­": ""}
_QUOTE_TABLE = str.maketrans(_QUOTES)


def normalize(text: str) -> str:
    """Compare text without caring about whitespace, quote marks, dashes or ligatures."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_TABLE)
    return re.sub(r"\s+", " ", text).strip()


def _dehyphenate(text: str) -> str:
    """Join words split across lines, as in "afford-\nable"."""
    return re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)


def quote_on_page(quote: str, page_text: str) -> bool:
    q = normalize(quote)
    if len(q) < 8:
        return False
    if q in normalize(page_text) or q in normalize(_dehyphenate(page_text)):
        return True
    # Tolerate a trailing period the model added or dropped.
    q2 = q.rstrip(".")
    return len(q2) >= 8 and q2 in normalize(page_text)


def locate(quote: str, pages: list[str], stated: int) -> int | None:
    """The page the quote is on: the stated page first, then any other. None if nowhere."""
    if 1 <= stated <= len(pages) and quote_on_page(quote, pages[stated - 1]):
        return stated
    for number, text in enumerate(pages, 1):
        if number != stated and quote_on_page(quote, text):
            return number
    return None


# ---------------------------------------------------------------------------
# Values, numbers and dates, checked by code

_NUM = r"(\d[\d,]*)"


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def numbers(topic: str, quote: str) -> dict:
    """Home counts and percent arithmetic read straight from the quote."""
    out: dict = {}
    if topic != "units":
        return out
    m = re.search(rf"\b{_NUM} of (?:the |all |its )?{_NUM}\b(?: (?:new |total )?(?:homes|units|apartments))?", quote)
    if m and _int(m.group(1)) < _int(m.group(2)):
        out["homes"] = {"count": _int(m.group(1)), "of": _int(m.group(2))}
        return out
    m = re.search(rf"\b{_NUM} (?:percent|%) of (?:the |all |its )?{_NUM}\b", quote)
    if m:
        pct, total = _int(m.group(1)), _int(m.group(2))
        if pct * total % 100 == 0:
            out["math"] = {"percent": pct, "of": total, "equals": pct * total // 100}
        return out
    m = re.search(rf"\b{_NUM} (?:affordable |income-restricted |workforce |reduced-rent )?(?:homes|units|apartments)\b", quote)
    if m:
        out["homes"] = {"count": _int(m.group(1))}
    return out


def canonical_value(topic: str, quote: str, model_value: str) -> str:
    """A comparable value, so "wording differs" is decided from numbers in the quote, not model phrasing."""
    q = normalize(quote).lower()
    if topic == "units":
        # Compare the home count itself, so "12 of the 120 homes" and "12 affordable homes" do not differ.
        # The quote, and the homes/math fields, keep the full wording.
        n = numbers(topic, quote)
        if "homes" in n:
            return f"{n['homes']['count']} homes"
        if "math" in n:
            return f"{n['math']['equals']} homes"
    if topic == "term":
        m = re.search(r"\b(\d+)[- ]years?\b", q)
        if m:
            return f"{m.group(1)} years"
    if topic in ("income_basis", "rent_limits"):
        m = re.search(r"\b(\d+)\s*(?:percent|%)", q)
        if m:
            return f"{m.group(1)} percent of area median income" if topic == "income_basis" else f"{m.group(1)} percent"
    return normalize(model_value).strip().rstrip(".") or normalize(quote)


_AFFORD = re.compile(r"afford|income-restricted|workforce|reduced[- ]rent", re.I)
_NOT_AFFORDABILITY = re.compile(r"\btax|payment in lieu|\bPILOT\b|abate", re.I)
_DUE = re.compile(r"\bby\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})", re.I)
_END_DATE = re.compile(r"\bends?\b.*?\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})", re.I)


def compare_key(topic: str, quote: str) -> str | None:
    """What code compares to decide "wording differs": numbers and dates read from the quote.

    None means the quote states no comparable value (a total home count, a duty with no date, a party),
    so it never makes a term differ. The model's own wording of the value is shown but never compared.
    """
    q = normalize(quote)
    if topic == "units":
        # The count and the form of the commitment: "up to 12" is a cap and "10 percent of 120" is a share,
        # so both differ from a flat "12 homes", as in the hand-reviewed demo. "12 of the 120" is a flat 12.
        n = numbers(topic, quote)
        if "math" in n:
            return f"{n['math']['percent']} percent of {n['math']['of']} homes"
        m = re.search(r"\bup to (\d[\d,]*)\b", q, re.I)
        if m and (_AFFORD.search(q) or _UNITS_WORDS.search(q)):
            return f"up to {_int(m.group(1))} homes"
        if "homes" in n and (_AFFORD.search(q) or "of" in n["homes"]):
            return f"{n['homes']['count']} homes"
        return None
    if topic == "term":
        if _NOT_AFFORDABILITY.search(q):
            return None
        m = _END_DATE.search(q)
        if m:
            return f"ends {m.group(1).lower()} {int(m.group(2))} {m.group(3)}"
        m = re.search(r"\b(\d+)[\s-]*years?\b", q, re.I)
        return f"{m.group(1)} years" if m else None
    if topic in ("income_basis", "rent_limits"):
        found = re.findall(r"\b(\d+)\s*(?:percent|%)", q)
        return " of ".join(found) + " percent" if found else None
    if topic == "reporting":
        m = _DUE.search(q)
        return f"due {m.group(1).lower()} {int(m.group(2))}" if m else None
    if topic == "remedies":
        m = re.search(r"\b(\d+)\s*days\b", q, re.I)
        return f"{m.group(1)} days to cure" if m else None
    return None


_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]


def date_in_text(iso: str, pages: list[str]) -> bool:
    """True if the ISO date is printed somewhere in the record, in a common format."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    month = _MONTHS[d.month - 1]
    patterns = [
        iso,
        rf"{month}\s+{d.day},?\s+{d.year}",
        rf"{month[:3]}\.?\s+{d.day},?\s+{d.year}",
        rf"{d.day}\s+{month}\s+{d.year}",
        rf"\b0?{d.month}/0?{d.day}/{d.year}\b",
    ]
    text = normalize(" ".join(pages)).lower()
    return any(re.search(p, text) for p in patterns)


# ---------------------------------------------------------------------------
# Stage rules

TYPE_LABELS = {
    "staff_report": "Staff report",
    "letter": "Letter",
    "slides": "Slides",
    "minutes": "Minutes",
    "resolution": "Resolution",
    "agreement": "Agreement",
    "certificate": "Certificate",
    "other": "Other record",
}
_TYPE_WORDS = [
    ("certificate", r"certif|occupancy|compliance report|lease-?up|rent roll"),
    ("agreement", r"agreement|contract|covenant|deed|regulatory"),
    ("resolution", r"resolution|ordinance"),
    ("minutes", r"minutes|meeting record"),
    ("slides", r"slide|presentation|deck"),
    ("staff_report", r"staff|memo|report|summary"),
    ("letter", r"letter|correspondence|commitment"),
]
_SUPPORT_EVIDENCE = re.compile(r"\b(vote[ds]?|voting|adopt(ed|s)?|approv(ed|es|al)|resolved|motion (passed|carried)|ayes?)\b", re.I)
_DELIVERY_EVIDENCE = re.compile(r"certificate of occupancy|occupan(cy|t|ts)|certif(y|ies|ied|icate)|leased|placed in service|compliance", re.I)
_DRAFT_UPPER = re.compile(r"\bDRAFT\b|\bNOT SIGNED\b|\bUNSIGNED\b")
_SIGNED_MARK = re.compile(r"/s/|\bsigned\b|\bsignature\b|\bexecuted\b|\bby:\s*\S", re.I)
_BLANK_LINE = re.compile(r"_{3,}")


def type_key(label: str | None) -> str | None:
    """Map a staff-entered type such as "Executed agreement" to a rule key."""
    if not label:
        return None
    low = label.strip().lower().replace(" ", "_")
    if low in TYPE_LABELS:
        return low
    low = label.lower()
    for key, words in _TYPE_WORDS:
        if re.search(words, low):
            return key
    return "other"


def is_draft(pages: list[str], model_says_draft: bool) -> bool:
    """A record is a draft if it says so in capitals, says "not signed", or the model flags it."""
    text = "\n".join(pages)
    return bool(model_says_draft or _DRAFT_UPPER.search(text) or re.search(r"not signed|unsigned|for discussion only", text, re.I))


SIGNATURE_WINDOW = 3  # Lines after a party's name that count as its signature block.
_UNSIGNED = re.compile(r"unsigned|not signed|signature pending|to be signed", re.I)


def _signed_line(line: str) -> bool:
    if not _SIGNED_MARK.search(line) or _UNSIGNED.search(line):
        return False
    return not (_BLANK_LINE.search(line) and "/s/" not in line)


def signature_block(party: str, page_text: str) -> str | None:
    """The completed-signature line printed just after the party's name on this page, or None."""
    want = normalize(party).lower()
    lines = [normalize(line) for line in page_text.split("\n")]
    for i, line in enumerate(lines):
        if want and want in line.lower():
            same = line.lower().split(want, 1)[1]
            if _signed_line(same):
                return line
            for nxt in lines[i + 1:i + 1 + SIGNATURE_WINDOW]:
                if _signed_line(nxt):
                    return nxt
    return None


def checked_signatures(signatures: list[dict], pages: list[str]) -> list[dict]:
    """Keep a signature only if code finds the party's name on a page with a completed signature right after it.

    The model only names the party. The signature line itself is found in the page text, so a model that
    quotes a job title, or invents a signer, cannot make a record signed.
    """
    kept = []
    for sig in signatures:
        party = (sig.get("party") or "").strip()
        if len(party) < 3:
            continue
        stated = int(sig.get("page") or 0)
        order = ([stated] if 1 <= stated <= len(pages) else []) + [n for n in range(1, len(pages) + 1) if n != stated]
        for number in order:
            line = signature_block(party, pages[number - 1])
            if line:
                kept.append({"party": party, "quote": line, "page": number})
                break
    return kept


def decide_stage(kind: str, pages: list[str], signatures: list[dict], draft: bool) -> tuple[str, list[str], str]:
    """Return (stage, signed_by, reason). The furthest a record can reach is set by its type."""
    text = "\n".join(pages)
    signers = list(dict.fromkeys(s["party"] for s in signatures))
    if kind == "certificate":
        if _DELIVERY_EVIDENCE.search(text):
            return "delivered", signers, "Certificate or occupancy record."
        return "proposed", signers, "Marked as a certificate, but no occupancy or certification wording was located."
    if kind in ("agreement", "letter"):
        if signers and not draft:
            return "signed", signers, f"Signed by {', '.join(signers)}."
        why = "Marked as a draft or unsigned." if draft else "No completed signature was located."
        return "proposed", [], why
    if kind in ("minutes", "resolution"):
        if _SUPPORT_EVIDENCE.search(text):
            return "supported", [], "Council minutes or resolution with a recorded action."
        return "proposed", [], "Minutes or resolution, but no vote or approval wording was located."
    return "proposed", [], "Staff reports, letters and slides describe proposals."


# ---------------------------------------------------------------------------
# Reading cache (by file hash), so seeding and evals never pay twice

# The prompt and answer schema are part of the key, so changing either reads files again.
PROMPT_ID = hashlib.sha256((ai.PDF_SYSTEM_PROMPT + json.dumps(ai.PdfReading.model_json_schema(), sort_keys=True))
                           .encode()).hexdigest()[:8]


def _reading_path(sha: str) -> Path:
    return READINGS_DIR / f"{sha[:16]}-{PROMPT_ID}.json"  # Short names keep Windows paths under the limit.


def cached_reading(sha: str) -> dict | None:
    try:
        return json.loads(_reading_path(sha).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_reading(sha: str, result: ai.ReadResult) -> None:
    READINGS_DIR.mkdir(parents=True, exist_ok=True)
    _reading_path(sha).write_text(result.model_dump_json(indent=1), encoding="utf-8")


def read_with_cache(sha: str, pages: list[str], reader=None, use_cache: bool = True) -> tuple[ai.ReadResult, bool]:
    """(result, from_cache). use_cache=False skips the lookup; successful live readings are always saved."""
    if use_cache:
        hit = cached_reading(sha)
        if hit:
            return ai.ReadResult.model_validate(hit), True
    result = (reader or ai.read_document)(pages)
    if result.mode == "live":
        try:
            save_reading(sha, result)
        except OSError:
            pass
    return result, False


# ---------------------------------------------------------------------------
# One document, start to finish (after the file is stored)

# A sentence saying a term is missing ("rent levels were not described") does not locate that term.
_ABSENT = re.compile(r"\b(?:not|never) (?:yet )?(?:been )?(?:described|included|specified|stated|addressed|"
                     r"defined|set out|provided|attached|located)\b|\bto be (?:set|decided|determined) later\b", re.I)

_RECOMMENDS = re.compile(r"\brecommend(s|ed)?\b", re.I)


def claim_stage(doc_stage: str, kind: str, quote: str) -> str:
    """A staff recommendation is support, even inside a report. Nothing else moves a claim past its record."""
    if doc_stage == "proposed" and kind in ("staff_report", "other") and _RECOMMENDS.search(quote):
        return "supported"
    return doc_stage


def canonical_party(party: str, known: list[str]) -> str:
    """Use the deal's own spelling of a party name; tidy names printed in capitals."""
    for name in known:
        if name and normalize(name).lower() == normalize(party).lower():
            return name
    if party.isupper():
        keep = ("LLC", "LP", "LLP", "INC", "INC.")
        return " ".join(w if w in keep else "of" if w == "OF" else w.capitalize() for w in party.split())
    return party


# ---------------------------------------------------------------------------
# Term fit and boilerplate: code rules that keep only sentences that state the term they are filed under

_NUMBER_HOMES = re.compile(r"\b\d[\d,]*\b(?:[^.]{0,40}?)\b(?:homes?|units?|apartments?)\b", re.I)
_UNITS_WORDS = re.compile(r"afford|reserve|set(?:ting)? aside|set-aside|workforce|income|restricted|required|leased|"
                          r"reduced rents?", re.I)
_TERM_WORDS = re.compile(r"\b\d+[\s-]*years?\b|\bends?\b|\buntil\b|\bexpires?\b|\bperiod\b|\bremain in effect\b", re.I)
_SUPPORT_WORDS = re.compile(r"\btax|payment in lieu|\bPILOT\b|abate|exemption|subsid|loan|grant|incentive|support", re.I)
_SUPPORT_ACTION = re.compile(r"recommend|approv|adopt|vote|support|award|grant|shall pay|asked staff|confirm", re.I)
_MOTION = re.compile(r"\bmoved to\b|\bseconded\b", re.I)
# A condition the Council puts on its support, such as asking for the terms in writing.
_SUPPORT_CONDITION = re.compile(r"\bCouncil\b.*\b(?:asked|directed|required) (?:the )?(?:staff|owner|developer)\b|"
                                r"\bsubject to\b|\bon (?:the )?condition\b", re.I)
# Status notes ("marked not received") are observations about a duty, not the duty itself.
_STATUS_NOTE = re.compile(r"\bnot received\b|\bis marked\b|\bwas received\b|\breminder notice\b", re.I)
_REPORT_WORDS = re.compile(r"report|certif|records?|submit|file|deliver", re.I)
# A reporting duty has a cadence. A one-off deadline ("a second notice ... by May 15") is a follow-up, not the duty.
_REPORT_WHEN = re.compile(r"annual|yearly|each year|every year|submitted|reporting year \d{4}", re.I)
_REMEDY_WORDS = re.compile(r"default|cure|repay|recapture|penalt|terminat|liquidated|breach", re.I)
_PARTY_WORDS = re.compile(r"responsib|\bbinds?\b|successor|later owner|obligat|liable", re.I)
_RENT_WORDS = re.compile(r"\brents?\b|\brental charge", re.I)
_RENT_LIMIT = re.compile(r"limit|exceed|above|below|percent|%|\bcap\b|maximum|\bHUD\b", re.I)
_INCOME_WORDS = re.compile(r"income|\bAMI\b|median", re.I)
_SELF_DESCRIPTION = re.compile(r"^(?:this|the) (?:memo|memorandum|report|letter|presentation|summary|document)\b"
                               r"[^.]{0,20}\b(?:reports|describes|summarizes|follows|provides|is)\b", re.I)
_TAX_SPAN = re.compile(r"\btax|payment in lieu|\bPILOT\b|abate", re.I)


def term_fits(topic: str, quote: str) -> bool:
    """True if the sentence states the kind of term it is filed under. Applied to every model candidate."""
    q = normalize(quote)
    if topic == "units":
        return bool(_NUMBER_HOMES.search(q) and _UNITS_WORDS.search(q))
    if topic == "term":
        return bool(_TERM_WORDS.search(q)) and not _TAX_SPAN.search(q)
    if topic == "public_support":
        if _MOTION.search(q):
            return False
        return bool(_SUPPORT_WORDS.search(q) and _SUPPORT_ACTION.search(q)) or bool(_SUPPORT_CONDITION.search(q))
    if topic == "reporting":
        return bool(_REPORT_WORDS.search(q) and _REPORT_WHEN.search(q)) and not _STATUS_NOTE.search(q)
    if topic == "remedies":
        return bool(_REMEDY_WORDS.search(q))
    if topic == "responsible_party":
        return bool(_PARTY_WORDS.search(q))
    if topic == "rent_limits":
        return bool(_RENT_WORDS.search(q) and _RENT_LIMIT.search(q))
    if topic == "income_basis":
        return bool(_INCOME_WORDS.search(q))
    return True


def repeated_lines(pages: list[str]) -> set[str]:
    """Lines printed on more than one page, such as headers and footers."""
    seen: dict[str, int] = {}
    for text in pages:
        for line in {normalize(l).lower() for l in text.split("\n") if len(l.strip()) >= 8}:
            seen[line] = seen.get(line, 0) + 1
    return {line for line, n in seen.items() if n > 1} if len(pages) > 1 else set()


_FOOTER = re.compile(r"sample document|\bpage \d+ of \d+\b|made-up demo record", re.I)
# A definition ('"Area Median Income" means ...') explains a word; the term itself is stated elsewhere.
_DEFINITION = re.compile(r'^(?:\(?[a-z0-9]{1,3}[.)]\s*)?["“][^"”]{2,60}["”]\s+(?:means|shall mean|refers to)\b', re.I)


def is_boilerplate(quote: str, chrome: set[str]) -> bool:
    """Headers, footers, page numbers and a record describing itself are not terms."""
    q = normalize(quote)
    low = q.lower()
    if _FOOTER.search(q) or _SELF_DESCRIPTION.search(q) or _DEFINITION.search(q):
        return True
    # A quote that sits inside a line repeated on every page is a header or footer.
    return any(low.rstrip(".") in line for line in chrome)


def verify_reading(reading: ai.PdfReading, pages: list[str], doc: dict, known_parties: list[str] | None = None) -> dict:
    """Check the model's reading against the page text. Returns the fields to save on the document."""
    kind = type_key(doc.get("type")) or reading.document_type
    draft = is_draft(pages, reading.draft)
    signatures = checked_signatures([s.model_dump() for s in reading.signatures], pages)
    for sig in signatures:
        sig["party"] = canonical_party(sig["party"], known_parties or [])
    stage, signed_by, reason = decide_stage(kind, pages, signatures, draft)

    doc_date = doc.get("date") or ""
    date_note = ""
    if not doc_date:
        if reading.date and date_in_text(reading.date, pages):
            doc_date = reading.date
        else:
            date_note = "Date not located in the record."

    claims, counts = [], {"candidates": len(reading.candidates), "kept": 0, "page_corrected": 0,
                          "dropped": 0, "duplicates": 0, "absent": 0,
                          "boilerplate": 0, "off_term": 0}
    chrome = repeated_lines(pages)
    seen = set()
    label = doc.get("type") or TYPE_LABELS.get(kind, "Record")
    for cand in reading.candidates:
        if cand.topic not in ledger.TOPICS:
            counts["dropped"] += 1
            continue
        page = locate(cand.quote, pages, cand.page)
        if page is None:
            counts["dropped"] += 1
            continue
        if _ABSENT.search(normalize(cand.quote)):
            counts["absent"] += 1
            continue
        if is_boilerplate(cand.quote, chrome):
            counts["boilerplate"] += 1
            continue
        if not term_fits(cand.topic, cand.quote):
            counts["off_term"] += 1
            continue
        # One sentence is one claim: the same quote filed under a second term is a duplicate.
        key = normalize(cand.quote).lower().rstrip(".")
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        corrected = page != cand.page
        counts["page_corrected"] += corrected
        wording = cand.wording if normalize(cand.wording).lower() in normalize(cand.quote).lower() else ""
        claim = {
            "id": f"{doc['id']}-{len(claims) + 1:02d}",
            "quote": normalize(cand.quote),
            "document": doc["id"],
            "document_type": label,
            "document_title": doc.get("title") or reading.title,
            "date": doc_date,
            "page": page,
            "stated_page": cand.page,
            "page_corrected": corrected,
            "topic": cand.topic,
            "status": claim_stage(stage, kind, cand.quote),
            "wording": wording,
            "value": canonical_value(cand.topic, cand.quote, cand.value),
            "compare": compare_key(cand.topic, cand.quote),
            "verified": True,
            "review_note": ai.REVIEW_LABEL,
            **numbers(cand.topic, cand.quote),
        }
        claims.append(claim)
    counts["kept"] = len(claims)
    return {
        "type": label,
        "type_key": kind,
        "title": doc.get("title") or reading.title,
        "date": doc_date,
        "date_note": date_note,
        "stage": stage,
        "stage_reason": reason,
        "signed": stage == "signed",
        "signed_by": signed_by,
        "signatures": signatures,
        "draft": draft,
        "claims": claims,
        "counts": counts,
    }
