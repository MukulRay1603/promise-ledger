"""Build real-record deals from Prince George's County, Maryland council records (Legistar Web API).

Each PILOT (payment in lieu of taxes) agreement the County Council considered becomes one deal folder under
data/county/<slug>/ with a manifest.json listing its public records: transmittal, legislative summary, the
agreement itself, fiscal note, committee report, the resolution as adopted, and so on. The PDFs are public
records of Prince George's County. They are not committed: each manifest entry keeps the official URL and the
file's SHA-256, and the app downloads and checks the file when it seeds the deal (app/deals.py).

    python tools/county_import.py                       # deals introduced since 2023, write manifests
    python tools/county_import.py --since 2019-01-01    # more years
    python tools/county_import.py --only CR-044-2026    # one deal
    python tools/county_import.py --download            # also keep the PDFs locally (gitignored) for reading

The Legistar Web API is public and read-only (https://webapi.legistar.com/Home/Examples). This tool pages and
filters its queries, waits between requests, and identifies itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "county"
CLIENT = "princegeorgescountymd"
API = f"https://webapi.legistar.com/v1/{CLIENT}"
SITE = f"https://{CLIENT}.legistar.com"
UA = "PromiseLedger/2.0 (open-source civic tool; https://github.com/MukulRay1603/promise-ledger)"
PAUSE = 0.4  # Seconds between API requests.
MAX_PDF_BYTES = 6_000_000  # Larger files (mostly slide decks of photos) are listed but not read.

# Attachment name -> (record type, which council action dates it, keep?)
KINDS = [
    (r"\bMBE\b|minority business", ("MBE plan", "intro", False)),
    (r"withdraw", ("Withdrawal", "last", True)),
    (r"presentation|\bppt\b|overview", ("Presentation", "intro", True)),
    (r"transmittal", ("Transmittal letter", "intro", True)),
    (r"fiscal|\bPAFI\b|policy note", ("Fiscal and policy note", "intro", True)),
    (r"summary|\bAIS\b", ("Legislative summary", "intro", True)),
    (r"\bOMB\b|\bOOL\b|comment|memo", ("Agency comments", "intro", True)),
    (r"committee report|\breport\b", ("Committee report", "committee", True)),
    (r"signed", ("Signed resolution", "passed", True)),
    (r"attachment b|pilot agreement|master pilot|agreement", ("PILOT agreement", "intro", True)),
    (r"attachment|exhibit|schedule", ("Attachment", "intro", True)),
    (r"^R\d{7}", ("Resolution", "passed", True)),
]


def get(path: str, **params) -> list | dict:
    url = API + path + ("?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    time.sleep(PAUSE)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch(url: str) -> bytes:
    for attempt in range(3):  # The attachment server sometimes answers 5xx once; wait and try again.
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        time.sleep(PAUSE * (1 + 5 * attempt))
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read(MAX_PDF_BYTES + 1)
        except urllib.error.HTTPError as err:
            if attempt == 2 or err.code < 500 and err.code != 429:
                raise
    raise RuntimeError("unreachable")


WORD_FORMATS = {"docx", "doc"}
WORD_TO_PDF = r"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($args[0], $false, $true)
  $doc.ExportAsFixedFormat($args[1], 17)
  $doc.Close($false)
} finally { $word.Quit() }
"""


def word_to_pdf(data: bytes, suffix: str) -> bytes:
    """Convert a Word record to PDF with Microsoft Word itself (Windows), so pages match the official file.

    Only the importer converts. The PDF is committed next to the manifest, with the original's URL and SHA-256,
    because the app cannot convert Word files on the server.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / f"record.{suffix}", Path(tmp) / "record.pdf"
        src.write_bytes(data)
        script = Path(tmp) / "convert.ps1"
        script.write_text(WORD_TO_PDF, encoding="utf-8")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        str(src), str(out)], check=True, timeout=180, capture_output=True)
        return out.read_bytes()


def is_housing_pilot(title: str) -> bool:
    return bool(re.search(r"payments? in lieu of taxes|PILOT\)?\s+agreement", title, re.I)) and not re.search(
        r"vending|agritourism|pilot program|citizenship and immigration|right of first refusal", title, re.I)


def project_name(title: str) -> str:
    """'... AGREEMENT FOR THE HOLLY PLACE PROJECT for the purpose ...' -> 'Holly Place'."""
    t = re.sub(r"\s+", " ", title)
    named = re.search(r"\bfor the (.+?) project\b", t, re.I)
    if named and "county" not in named.group(1).lower():
        t = "agreement for " + named.group(1) + " project"
    m = re.search(r"\b(?:for|between)\s+(?:the\s+)?(.+?)(?:\s+project\b|\s+for the purpose|\s*,|$)", t[t.lower().find("agreement"):], re.I)
    name = (m.group(1) if m else t).strip(" .")
    name = re.sub(r"\s*-\s*", " - ", name)
    small = {"at", "of", "the", "on", "and", "by", "in"}
    words = name.lower().split()
    return " ".join(w if (i and w in small) else (w.upper() if re.fullmatch(r"[ivx]+|\d+%?", w) else w.capitalize())
                    for i, w in enumerate(words))[:80]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def kind(name: str) -> tuple[str, str, bool]:
    for pattern, value in KINDS:
        if re.search(pattern, name, re.I):
            return value
    return ("Attachment", "intro", True)


def action_dates(histories: list[dict]) -> dict:
    """Dates of the first action, the first committee action and the final passage, from the official history."""
    dates = sorted((h.get("MatterHistoryActionDate") or "")[:10] for h in histories if h.get("MatterHistoryActionDate"))
    committee = [h for h in histories if h.get("MatterHistoryActionBodyName") and "council" not in h["MatterHistoryActionBodyName"].lower()]
    passed = [h for h in histories if h.get("MatterHistoryPassedFlag") == 1]
    return {
        "intro": dates[0] if dates else None,
        "committee": min(((h.get("MatterHistoryActionDate") or "")[:10] for h in committee), default=None),
        "passed": max(((h.get("MatterHistoryActionDate") or "")[:10] for h in passed), default=None),
        "last": dates[-1] if dates else None,
    }


def votes(histories: list[dict]) -> list[dict]:
    """The council's own record of each vote: body, action, result and tally, as Legistar publishes it."""
    out = []
    for h in histories:
        if h.get("MatterHistoryPassedFlag") is None:
            continue
        out.append({
            "date": (h.get("MatterHistoryActionDate") or "")[:10],
            "body": h.get("MatterHistoryActionBodyName"),
            "action": h.get("MatterHistoryActionName"),
            "passed": h.get("MatterHistoryPassedFlag") == 1,
            "tally": h.get("MatterHistoryTally") or None,
        })
    return out


def build(matter: dict, download: bool) -> dict | None:
    mid = matter["MatterId"]
    histories = get(f"/matters/{mid}/histories")
    dates = action_dates(histories)
    attachments = get(f"/matters/{mid}/attachments")
    name = project_name(matter["MatterTitle"])
    folder = OUT / slug(f"{name}-{matter['MatterFile']}")
    folder.mkdir(parents=True, exist_ok=True)
    documents, listed = [], []
    for att in attachments:
        att_name = re.sub(r"\s+", " ", att.get("MatterAttachmentName") or "").strip()
        url = att.get("MatterAttachmentHyperlink") or ""
        record_type, when, keep = kind(att_name)
        entry = {"type": record_type, "title": f"{matter['MatterFile']} {att_name}".strip() if not att_name.startswith(matter["MatterFile"]) else att_name,
                 "date": dates.get(when) or dates["intro"], "url": url}
        ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
        if not keep or ext not in WORD_FORMATS | {"pdf"}:
            listed.append({**entry, "skipped": "not a housing record" if not keep else f"not a PDF or Word file ({ext})"})
            continue
        try:
            data = fetch(url)
        except Exception as err:  # A missing file is listed, not fatal.
            listed.append({**entry, "skipped": f"download failed ({type(err).__name__})"})
            continue
        if len(data) > MAX_PDF_BYTES:
            listed.append({**entry, "skipped": f"larger than {MAX_PDF_BYTES // 1_000_000} MB"})
            continue
        number = len(documents) + 1
        if ext in WORD_FORMATS:
            try:
                pdf = word_to_pdf(data, ext)
            except Exception as err:
                listed.append({**entry, "skipped": f"Word conversion failed ({type(err).__name__})"})
                continue
            file_name = f"{number:02d}-{slug(record_type)}.from-{ext}.pdf"
            (folder / file_name).write_bytes(pdf)  # Committed: the app cannot convert Word files itself.
            documents.append({**entry, "file": file_name, "id": f"r{number:02d}", "sha256": hashlib.sha256(pdf).hexdigest(),
                              "bytes": len(pdf), "signed_by": [], "committed": True,
                              "converted_from": {"format": ext, "url": url, "sha256": hashlib.sha256(data).hexdigest()}})
            continue
        if not data.startswith(b"%PDF"):
            listed.append({**entry, "skipped": "not a PDF"})
            continue
        file_name = f"{number:02d}-{slug(record_type)}.pdf"
        if download:
            (folder / file_name).write_bytes(data)
        documents.append({**entry, "file": file_name, "id": f"r{number:02d}",
                          "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "signed_by": []})
    if not documents:
        return None
    manifest = {
        "notice": ("Real public records of Prince George's County, Maryland, from the County Council's Legistar system. "
                   "Promise Ledger lists what the records say; it does not judge whether any party met an obligation."),
        "real": True,
        "deal": name,
        "slug": folder.name,
        "city": "Prince George's County",
        "county": "Prince George's County, MD",
        "owner": None,
        "as_of": dates["last"] or dates["intro"],
        "source": {
            "system": "Prince George's County Legistar",
            "file": matter["MatterFile"],
            "title": re.sub(r"\s+", " ", matter["MatterTitle"]).strip(),
            "status": matter.get("MatterStatusName"),
            "introduced": dates["intro"],
            "passed": dates["passed"],
            "url": f"{SITE}/gateway.aspx?M=L&ID={mid}",  # LegislationDetail links answer "Invalid parameters".
            "api": f"{API}/matters/{mid}",
            "votes": votes(histories),
            "retrieved": time.strftime("%Y-%m-%d"),
        },
        "documents": documents,
        "not_read": listed,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default="2023-01-01", help="first introduction date (YYYY-MM-DD)")
    parser.add_argument("--only", nargs="*", help="council file numbers, e.g. CR-044-2026")
    parser.add_argument("--download", action="store_true", help="keep the PDFs in each folder (gitignored)")
    args = parser.parse_args()
    query = f"substringof('PILOT',MatterTitle) and MatterIntroDate ge datetime'{args.since}'"
    matters = [m for m in get("/matters", **{"$filter": query}) if is_housing_pilot(m["MatterTitle"])]
    if args.only:
        matters = [m for m in matters if m["MatterFile"] in set(args.only)]
    print(f"{len(matters)} PILOT agreement(s) since {args.since}")
    for matter in sorted(matters, key=lambda m: m["MatterIntroDate"]):
        manifest = build(matter, args.download)
        if manifest:
            print(f"  {matter['MatterFile']:<13} {manifest['deal'][:40]:<40} {len(manifest['documents'])} records "
                  f"({sum(d['bytes'] for d in manifest['documents']) / 1e6:.1f} MB), {len(manifest['not_read'])} not read, "
                  f"status {manifest['source']['status']}")
        else:
            print(f"  {matter['MatterFile']:<13} no readable records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
