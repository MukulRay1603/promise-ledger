"""Read one deal PDF, check what the model proposed, and decide stages by rule.

1. Store the file.                         (app/deals.py)
2. Extract text per page with pypdf; flag pages with no text. Those are transcribed by the model
   (app/vision.py) and marked, so their quotes are checked like any other.
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
from functools import lru_cache
from pathlib import Path

from app import ai, ledger

ROOT = Path(__file__).resolve().parent.parent
READINGS_DIR = Path(os.getenv("READINGS_DIR") or ROOT / "data" / "readings")
# New live readings. Locally they join the committed cache; on Cloud Run (K_SERVICE is set) the image is
# read-only in spirit and its disk is memory, so they go to the runtime folder and only the newest are kept (P16).
# None means "the same folder as READINGS_DIR".
READINGS_WRITE_DIR: Path | None = (Path(os.environ["READINGS_WRITE_DIR"]) if os.getenv("READINGS_WRITE_DIR") else
                                   Path(os.getenv("RUNTIME_DIR") or ROOT / "data" / "runtime") / "readings"
                                   if os.getenv("K_SERVICE") else None)
MAX_RUNTIME_READINGS = 200

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 60
MAX_TEXT_CHARS = 300_000  # Total text read from one PDF (S1).
PARSE_TIMEOUT_SECONDS = 15  # A crafted PDF can make pypdf very slow; parsing runs in a child process (S1).
MIN_PAGE_CHARS = 20  # Fewer characters than this and the page is treated as scanned.

# ---------------------------------------------------------------------------
# Page text

class PdfError(ValueError):
    """The upload is not a PDF we can read. The message is safe to show."""


def _read_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfError("The PDF is password protected.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfError(f"The PDF has more than {MAX_PDF_PAGES} pages.")
        pages, total = [], 0
        for page in reader.pages:
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise PdfError(f"The PDF has more than {MAX_TEXT_CHARS:,} characters of text. Upload a shorter record.")
            pages.append(text)
        return pages
    except PdfError:
        raise
    except (PdfReadError, Exception) as err:
        raise PdfError(f"The PDF could not be read ({type(err).__name__}).") from err


def _worker_main() -> None:
    """Child process entry: PDF bytes on stdin, {"pages": [...]} or {"error": "..."} as JSON on stdout."""
    import sys

    data = sys.stdin.buffer.read()
    try:
        out = {"pages": _read_pages(data)}
    except PdfError as err:
        out = {"error": str(err)}
    except Exception as err:  # pragma: no cover - _read_pages wraps everything
        out = {"error": f"The PDF could not be read ({type(err).__name__})."}
    sys.stdout.write(json.dumps(out))


def _read_pages_sandboxed(data: bytes, timeout: float) -> list[str]:
    """Parse in a separate Python process and kill it after `timeout` seconds, so one PDF cannot hold the server.

    A plain subprocess (not multiprocessing) so the child never re-imports the server's or test runner's main module.
    """
    import subprocess
    import sys

    try:
        done = subprocess.run([sys.executable, "-c", "from app.pipeline import _worker_main; _worker_main()"],
                              input=data, capture_output=True, timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        raise PdfError("The PDF took too long to read. Try a simpler or shorter file.") from None
    try:
        out = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PdfError("The PDF could not be read.") from None
    if "error" in out:
        raise PdfError(out["error"])
    return out["pages"]


def sandbox_enabled() -> bool:
    return os.getenv("PDF_SANDBOX", "1").strip().lower() not in ("0", "false", "off", "no")


def extract_pages(data: bytes, sandbox: bool | None = None) -> list[str]:
    """Page texts. Raises PdfError with a message that is safe to show.

    With the sandbox on (PDF_SANDBOX, default on) parsing runs in a child process with a time limit.
    """
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("The file is larger than 20 MB.")
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise PdfError("The file is not a PDF.")
    if sandbox_enabled() if sandbox is None else sandbox:
        return _read_pages_sandboxed(data, PARSE_TIMEOUT_SECONDS)
    return _read_pages(data)


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


def _keep_hyphens(text: str) -> str:
    """Join a compound that breaks at its own hyphen, as in "income-\neligible", keeping the hyphen."""
    return re.sub(r"(\w)-\s*\n\s*(\w)", r"\1-\2", text)


_LINE_NUMBERS = (re.compile(r"^\s*(\d{1,3})(?=\s|$)"), re.compile(r"(?<=\s)(\d{1,3})\s*$"))
MIN_NUMBERED_LINES = 5


def strip_line_numbers(text: str) -> str:
    """Page text without the line numbers printed down the margin of bills and resolutions.

    Council bills number every line ("1 WHEREAS, ...", "2 building near ..."), so a sentence that runs over
    two lines has a number in the middle of it. The numbers are removed only when most lines carry one and
    they count up by one, at the start or at the end of the line. Any other page is returned unchanged.
    """
    lines = text.split("\n")
    filled = [i for i, line in enumerate(lines) if line.strip()]
    for pattern in _LINE_NUMBERS:
        hits = {i: m for i in filled if (m := pattern.search(lines[i]))}
        if len(hits) < MIN_NUMBERED_LINES or len(hits) < 0.6 * len(filled):
            continue
        values = [int(m.group(1)) for m in hits.values()]
        if sum(b - a == 1 for a, b in zip(values, values[1:])) < 0.8 * (len(values) - 1):
            continue
        return "\n".join(line[:hits[i].start()] + line[hits[i].end():] if i in hits else line
                         for i, line in enumerate(lines))
    return text


@lru_cache(maxsize=512)
def _page_forms(page_text: str) -> tuple[str, ...]:
    """The normalized readings of one page that a quote may match: as printed, with words split across lines
    joined (without and with the hyphen), and the same again without margin line numbers."""
    texts = [page_text]
    unnumbered = strip_line_numbers(page_text)
    if unnumbered != page_text:
        texts.append(unnumbered)
    forms: list[str] = []
    for text in texts:
        for form in (normalize(text), normalize(_dehyphenate(text)), normalize(_keep_hyphens(text))):
            if form not in forms:
                forms.append(form)
    return tuple(forms)


def quote_on_page(quote: str, page_text: str) -> bool:
    q = normalize(quote)
    if len(q) < 8:
        return False
    forms = _page_forms(page_text)
    if any(q in form for form in forms):
        return True
    # Tolerate a trailing period the model added or dropped.
    q2 = q.rstrip(".")
    return len(q2) >= 8 and any(q2 in form for form in forms)


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
_UNITS = r"(?:homes?|units?|apartments?)"

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORD_NUMBER = re.compile(r"\b(?:(" + "|".join(_TENS[2:]) + r")(?:[- ](" + "|".join(_ONES[1:10]) + r"))?|("
                          + "|".join(_ONES) + r")|(one hundred|a hundred))\b", re.I)


_DOUBLED = re.compile(r"\b(\d[\d,]*)(\s*percent)?\s*\(\s*\1\s*%?\s*\)", re.I)


def numeric(text: str) -> str:
    """Normalized text with number words as digits ("thirty years" -> "30 years"), for code comparisons (L7).

    Only values read by code use this. Stored and shown quotes keep the record's exact words.
    """
    def word(m: re.Match) -> str:
        if m.group(4):
            return "100"
        if m.group(3):
            return str(_ONES.index(m.group(3).lower()))
        return str(_TENS.index(m.group(1).lower()) * 10 + (_ONES.index(m.group(2).lower()) if m.group(2) else 0))
    # Legal drafting repeats a number in brackets: "sixty percent (60%)", "eighteen (18)". Read it once.
    return _DOUBLED.sub(r"\1\2", _WORD_NUMBER.sub(word, normalize(text)))


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def numbers(topic: str, quote: str) -> dict:
    """Home counts and percent arithmetic read straight from the quote."""
    out: dict = {}
    if topic != "units":
        return out
    quote = numeric(quote)
    # "N of the M homes": a homes word must follow, so "Section 4 of the 2024 agreement" is not a count (L6).
    of_homes = r"(?:\s+[A-Za-z-]+){0,3}?\s+" + _UNITS + r"\b"
    m = re.search(rf"\b{_NUM} of (?:the |all |its )?{_NUM}\b{of_homes}", quote, re.I)
    if m and _int(m.group(1)) < _int(m.group(2)):  # "9 of the 9" is a delivery count, not a commitment.
        out["homes"] = {"count": _int(m.group(1)), "of": _int(m.group(2))}
        return out
    m = re.search(rf"\b{_NUM}\s*(?:percent|%) of (?:the |all |its )?{_NUM}\b{of_homes}", quote, re.I)
    if m:
        pct, total = _int(m.group(1)), _int(m.group(2))
        if pct * total % 100 == 0:
            out["math"] = {"percent": pct, "of": total, "equals": pct * total // 100}
        return out
    # "95 affordable rental units, 50 units in Building 1": the count is the 95, so a second describing word may follow.
    m = re.search(rf"\b{_NUM} (?:affordable |income-restricted |workforce |reduced-rent )?"
                  rf"(?:rental |dwelling |housing )?{_UNITS}\b", quote, re.I)
    if m:
        out["homes"] = {"count": _int(m.group(1))}
    return out


_YEARS = re.compile(r"\b(\d+)[\s-]*years?\b", re.I)
# Words that put a number of years on the restrictions themselves, and words that make it some other span.
_TERM_LEAD = re.compile(r"(?:\bfor|\blasts?|\bremain[a-z]*(?: in effect)?(?: for)?|\bterm of|\bperiod of|\ba|\ban)\s*$", re.I)
_OTHER_SPAN = re.compile(r"(?:\bwithin|\bafter|\bbefore|\bevery|\bonce|\bby)\s*$", re.I)
_INCOME_PCT = re.compile(r"\b(\d+)\s*(?:percent|%)\s+(?:of\s+)?(?:the\s+)?(?:area median income|AMI|median income)", re.I)


def term_years(text: str) -> int | None:
    """The length of the restrictions in years: the number led by "for", "remain" or "term of", not by "within" (L8)."""
    q = numeric(text)
    found = [(m, q[max(0, m.start() - 30):m.start()]) for m in _YEARS.finditer(q)]
    if not found:
        return None
    lead = [m for m, before in found if _TERM_LEAD.search(before)]
    plain = [m for m, before in found if not _OTHER_SPAN.search(before)]
    best = (lead or plain or [m for m, _ in found])[0]
    return int(best.group(1))


def income_percents(text: str) -> list[str]:
    """Percents tied to area median income first ("80% of AMI, averaging 60%" reads 80), else every percent (L8)."""
    q = numeric(text)
    tied = _INCOME_PCT.findall(q)
    return tied or re.findall(r"\b(\d+)\s*(?:percent|%)", q)


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
        years = term_years(quote)
        if years:
            return f"{years} years"
    if topic in ("income_basis", "rent_limits"):
        found = income_percents(quote) if topic == "income_basis" else re.findall(r"\b(\d+)\s*(?:percent|%)", numeric(q))
        if found:
            return f"{found[0]} percent of area median income" if topic == "income_basis" else f"{found[0]} percent"
    # The model's own wording is kept only if it is short and every number in it is in the quote (S10).
    value = normalize(model_value or "").strip().rstrip(".")
    if value and len(value) <= 80 and set(re.findall(r"\d+", value)) <= set(re.findall(r"\d+", normalize(quote))):
        return value
    return normalize(quote)


_AFFORD = re.compile(r"afford|income-restricted|workforce|reduced[- ]rent", re.I)
_NOT_AFFORDABILITY = re.compile(r"\btax|payment in lieu|\bPILOT\b|abate", re.I)
_DUE = re.compile(r"\bby\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})", re.I)
_END_DATE = re.compile(r"\bends?\b.*?\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})", re.I)


def compare_key(topic: str, quote: str) -> str | None:
    """What code compares to decide "wording differs": numbers and dates read from the quote.

    None means the quote states no comparable value (a total home count, a duty with no date, a party),
    so it never makes a term differ. The model's own wording of the value is shown but never compared.
    """
    q = numeric(quote)
    if topic == "units":
        # The count and the form of the commitment: "up to 12" is a cap and "10 percent of 120" is a share,
        # so both differ from a flat "12 homes", as in the hand-reviewed demo. "12 of the 120" is a flat 12.
        n = numbers(topic, quote)
        if "math" in n:
            return f"{n['math']['percent']} percent of {n['math']['of']} homes"
        # A homes word must follow the number: "up to 20% of the median income" is an income limit, not a cap on homes.
        m = re.search(rf"\bup to (\d[\d,]*)\b(?:\s+[A-Za-z-]+){{0,3}}?\s+{_UNITS}\b", q, re.I)
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
        years = term_years(q)
        return f"{years} years" if years else None
    if topic == "income_basis":
        found = income_percents(q)
        return " of ".join(found) + " percent" if found else None
    if topic == "rent_limits":  # "30 percent of 50 percent" is one limit, so every percent is kept in order.
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
    ("agreement", r"agreement|contract|covenant|\bdeed\b|regulatory"),
    ("certificate", r"\bcertificate\b|lease-?up report|rent roll"),
    ("resolution", r"resolution|ordinance"),
    ("minutes", r"minutes|meeting record"),
    ("slides", r"slide|presentation|deck"),
    ("staff_report", r"staff|memo|report|summary"),
    ("letter", r"letter|correspondence|commitment"),
]
# A recorded Council action that passed (L5). Each sentence is checked on its own, after the negation guard.
_SUPPORT_ACTED = re.compile(r"\bpassed and adopted\b|\bmotion (?:passed|carried)\b|\b(?:was|were|is) (?:approved|adopted)\b|"
                            r"\bthe (?:city )?council (?:approves|approved|adopts|adopted|resolves|authorizes)\b|"
                            r"\bbe it resolved\b|\bvoted (\d+) to (\d+) to (?:support|approve|adopt|grant)\b", re.I)
_SUPPORT_NOT = re.compile(r"\b(?:fail(?:ed|s)?|denied|denies|rejected|tabled|withdrawn|did not pass|not (?:adopt|approv|support)\w*|"
                          r"continued (?:to|until)|postponed|no action)\b|\bapproval of the (?:minutes|agenda)\b|"
                          r"\b(?:minutes|agenda|consent calendar)\b[^.;]{0,60}\b(?:was|were) approved\b|"
                          r"\bapproved as (?:posted|presented|submitted)\b|\bapproved by the council on\b", re.I)
# A certificate states what was delivered: homes leased, occupied or certified (L4).
_DELIVERY_EVIDENCE = re.compile(r"\bcertificate of occupancy\b|\b(?:were|was|are|is|has been|have been) (?:leased|occupied|"
                                r"rented|placed in service)\b|\bleased to\b|\bcertif(?:y|ies) that\b", re.I)
# The type the model reads is used only if the record names it, so the model alone never sets a stage (L4).
_KIND_IN_TEXT = {
    "agreement": re.compile(r"\bagreement\b|\bcovenant\b|\bdeed\b|\bcontract\b", re.I),
    "letter": re.compile(r"\bdear\b|\bsincerely\b|\bletter\b", re.I),
    "minutes": re.compile(r"\bminutes\b", re.I),
    "resolution": re.compile(r"\bresolution\b|\bordinance\b", re.I),
    "certificate": re.compile(r"\bcertificate\b", re.I),
}
_DRAFT_UPPER = re.compile(r"\bDRAFT\b|\bNOT SIGNED\b|\bUNSIGNED\b")
# A completed signature: "/s/ Name", "[signature on file]", "[signed]" or a digital-signature stamp (L3).
# A blank "Signature:", a typed "By: Name" or "executed in counterparts" is not a signature.
_SIGNED_MARK = re.compile(r"/s/\s*\S|\[\s*signature on file\s*\]|\[\s*signed\s*\]|\b(?:digitally|electronically) signed by\b", re.I)
_BLANK_LINE = re.compile(r"_{3,}")
# "Electronically signed by <party> on <date>": the mark comes before the name, on the same line.
_ESIGN_LEAD = re.compile(r"(?<!\bto be )(?<!\bwill be )(?<!\bnot )(?<!\bnot yet )\b(?:digitally|electronically) signed by\s*$", re.I)


def type_key(label: str | None) -> str | None:
    """Map a staff-entered type such as "Executed agreement" to a rule key, from the label's words only (L4).

    "Certified copy of the agreement" is an agreement and "Annual compliance report" a report, not a certificate.
    """
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
# A party that is only a job title ("City Clerk", "Managing Member") names no one who is bound (L1).
_TITLE_ONLY = re.compile(r"^(?:the\s+)?(?:(?:city|county|town|village|assistant|deputy|managing|general|authorized|"
                         r"executive|housing|program|compliance)\s+)*(?:clerk|manager|attorney|mayor|director|officer|member|"
                         r"partner|analyst|secretary|treasurer|president|chair(?:person)?|witness|notary(?: public)?|"
                         r"engineer|planner|staff|representative|signatory|owner)s?$", re.I)
# Lines that start another signature block or an attestation.
_BLOCK_END = re.compile(r"^(?:attest|approved as to form|witness|notary|acknowledg)", re.I)


def _starts_block(line: str) -> bool:
    """Another party's heading (a name in capitals) or an attestation label."""
    text = line.strip()
    if _BLOCK_END.search(text):
        return True
    letters = [ch for ch in text if ch.isalpha()]
    return len(text.split()) >= 2 and len(letters) >= 6 and all(ch.isupper() for ch in letters) and not _SIGNED_MARK.search(text)


def is_title_only(party: str) -> bool:
    return bool(_TITLE_ONLY.match(normalize(party).strip().rstrip(":.")))
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
            lead, same = line.lower().split(want, 1)
            if _signed_line(same) or (_ESIGN_LEAD.search(lead) and not _UNSIGNED.search(line)):
                return line
            for nxt in lines[i + 1:i + 1 + SIGNATURE_WINDOW]:
                if _signed_line(nxt):
                    return nxt
                if _starts_block(nxt):  # The next party's block: this party's signature was not found (L1).
                    break
    return None


def checked_signatures(signatures: list[dict], pages: list[str]) -> list[dict]:
    """Keep a signature only if code finds the party's name on a page with a completed signature right after it.

    The model only names the party. The signature line itself is found in the page text, so a model that
    quotes a job title, or invents a signer, cannot make a record signed.
    """
    kept = []
    for sig in signatures:
        party = (sig.get("party") or "").strip()
        if len(party) < 3 or is_title_only(party):
            continue
        stated = int(sig.get("page") or 0)
        order = ([stated] if 1 <= stated <= len(pages) else []) + [n for n in range(1, len(pages) + 1) if n != stated]
        for number in order:
            line = signature_block(party, pages[number - 1])
            if line:
                kept.append({"party": party, "quote": line, "page": number})
                break
    return kept


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;:])\s+|\n", normalize(text)) if s.strip()]


def support_actions(text: str) -> list[int]:
    """Character offsets of recorded actions that passed: adopted, carried, or a vote with more ayes (L5)."""
    found, at = [], 0
    norm = normalize(text)
    for sentence in _sentences(text):
        at = norm.find(sentence, at)
        if _SUPPORT_NOT.search(sentence):
            continue
        for m in _SUPPORT_ACTED.finditer(sentence):
            if m.group(1) and int(m.group(1)) <= int(m.group(2)):
                continue  # "voted 2 to 5 to approve" did not pass.
            found.append(max(at, 0) + m.start())
    return found


def record_kind(staff_type: str | None, model_type: str | None, pages: list[str]) -> tuple[str, bool]:
    """(kind, from_staff). With no staff type, the model's type counts only if the record names it (L4)."""
    kind = type_key(staff_type)
    if kind:
        return kind, True
    guess = type_key(model_type) or "other"
    first = "\n".join(pages[:1])
    if guess in _KIND_IN_TEXT and _KIND_IN_TEXT[guess].search(first):
        return guess, False
    return "other", False


def decide_stage(kind: str, pages: list[str], signatures: list[dict], draft: bool) -> tuple[str, list[str], str]:
    """Return (stage, signed_by, reason). The furthest a record can reach is set by its type."""
    text = "\n".join(pages)
    signers = list(dict.fromkeys(s["party"] for s in signatures))
    if kind == "certificate":
        if draft:
            return "proposed", signers, "Marked as a draft."
        if _DELIVERY_EVIDENCE.search(text):
            return "delivered", signers, "Certificate or occupancy record, as stated in the record."
        return "proposed", signers, "Marked as a certificate, but no statement that homes were leased, occupied or certified was located."
    if kind in ("agreement", "letter"):
        if signers and not draft:
            return "signed", signers, f"Signed by {', '.join(signers)}."
        why = "Marked as a draft or unsigned." if draft else "No completed signature was located."
        return "proposed", [], why
    if kind in ("minutes", "resolution"):
        if support_actions(text):
            return "supported", [], "Council minutes or resolution with a recorded action that passed."
        return "proposed", [], "Minutes or resolution, but no adopted or carried action was located."
    return "proposed", [], "Staff reports, letters and slides describe proposals."


# ---------------------------------------------------------------------------
# Reading cache (by file hash), so seeding and evals never pay twice

# The prompt and answer schema are part of the key, so changing either reads files again.
PROMPT_ID = hashlib.sha256((ai.PDF_SYSTEM_PROMPT + json.dumps(ai.PdfReading.model_json_schema(), sort_keys=True))
                           .encode()).hexdigest()[:8]


def _reading_path(sha: str) -> Path:
    return READINGS_DIR / f"{sha[:16]}-{PROMPT_ID}.json"  # Short names keep Windows paths under the limit.


def cached_reading(sha: str) -> dict | None:
    """The committed cache first, then readings saved at runtime."""
    for path in (_reading_path(sha), (READINGS_WRITE_DIR or READINGS_DIR) / _reading_path(sha).name):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return None


def save_reading(sha: str, result: ai.ReadResult) -> None:
    folder = READINGS_WRITE_DIR or READINGS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / _reading_path(sha).name).write_text(result.model_dump_json(indent=1), encoding="utf-8")
    if folder.resolve() != READINGS_DIR.resolve():  # Runtime cache: keep only the newest readings.
        saved = sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in saved[MAX_RUNTIME_READINGS:]:
            old.unlink(missing_ok=True)


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
_NOT_RECOMMENDS = re.compile(r"\b(?:not|n't|never|no longer)\s+recommend|\brecommend(?:s|ed)?\s+(?:against|denial|that the council (?:deny|reject|not))", re.I)
NEAR_ACTION = 2000  # Characters: in minutes, a claim is supported only within this distance of an action that passed (L5).


def claim_stage(doc_stage: str, kind: str, quote: str, pages: list[str] | None = None) -> str:
    """A staff recommendation is support, even inside a report. Nothing else moves a claim past its record.

    In minutes, one item's vote does not support another item: the claim must sit near an action that passed (L5).
    """
    if doc_stage == "proposed" and kind in ("staff_report", "other") and _RECOMMENDS.search(quote) \
            and not _NOT_RECOMMENDS.search(quote):
        return "supported"
    if doc_stage == "supported" and kind == "minutes" and _SUPPORT_NOT.search(normalize(quote)):
        return "proposed"  # A sentence that records a failed, denied or tabled motion is not support.
    if doc_stage == "supported" and kind == "minutes" and pages is not None:
        text = normalize("\n".join(pages))
        at = text.find(normalize(quote))
        if at >= 0 and not any(abs(at - action) <= NEAR_ACTION for action in support_actions("\n".join(pages))):
            return "proposed"
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


MAX_SET_ASIDE = 10


def term_fits(topic: str, quote: str) -> bool:
    """True if the sentence states the kind of term it is filed under. Applied to every model candidate.

    Number words count as numbers here ("Twelve affordable homes", "thirty years") (L7).
    """
    q = numeric(quote)
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
    kind, _from_staff = record_kind(doc.get("type"), reading.document_type, pages)
    draft = is_draft(pages, reading.draft)
    scans = set(doc.get("transcribed_pages") or [])
    # Stage evidence (signatures, votes, delivery) counts only from pages with their own text layer. Text the
    # model transcribed from a scan can hold claims, but it never moves a record past proposed by itself.
    evidence = [("" if i in scans else text) for i, text in enumerate(pages, 1)]
    signatures = checked_signatures([s.model_dump() for s in reading.signatures], evidence)
    for sig in signatures:
        sig["party"] = canonical_party(sig["party"], known_parties or [])
    stage, signed_by, reason = decide_stage(kind, evidence, signatures, draft)
    if scans and stage == "proposed" and decide_stage(kind, pages, checked_signatures(
            [s.model_dump() for s in reading.signatures], pages), draft)[0] != "proposed":
        reason += (" A signature, vote or delivery statement appears only on a scanned page. "
                   "A person must confirm it against the PDF before it counts.")

    # The model's title is kept only if it is printed in the record (S10); otherwise the filename shows.
    found = normalize(reading.title or "").lower().rstrip(".")
    title = doc.get("title") or (reading.title if len(found) >= 4 and any(found in normalize(p).lower() for p in pages)
                                 else None)

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
    set_aside: list[dict] = []  # Quotes found on the page whose wording the term rules did not confirm.
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
            # Not dropped silently: the quote is real, so a person checks it. It counts toward no term or stage.
            counts["off_term"] += 1
            key = normalize(cand.quote).lower().rstrip(".")
            if len(set_aside) < MAX_SET_ASIDE and all(normalize(x["quote"]).lower().rstrip(".") != key for x in set_aside):
                set_aside.append({"topic": cand.topic, "quote": normalize(cand.quote), "page": page})
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
            "document_title": title,
            "date": doc_date,
            "page": page,
            "stated_page": cand.page,
            "page_corrected": corrected,
            "topic": cand.topic,
            "status": claim_stage(stage, kind, cand.quote, pages),
            "wording": wording,
            "value": canonical_value(cand.topic, cand.quote, cand.value),
            "compare": compare_key(cand.topic, cand.quote),
            "verified": True,
            "review_note": ai.REVIEW_LABEL,
            **numbers(cand.topic, cand.quote),
        }
        if page in scans:  # The page was a scanned image; its text was transcribed by the model (app/vision.py).
            claim["from_scan"] = True
        claims.append(claim)
    counts["kept"] = len(claims)
    kept_quotes = {normalize(c["quote"]).lower().rstrip(".") for c in claims}
    set_aside = [x for x in set_aside if normalize(x["quote"]).lower().rstrip(".") not in kept_quotes]
    return {
        "set_aside": set_aside,
        "type": label,
        "type_key": kind,
        "title": title,
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
