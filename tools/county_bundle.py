"""Bundle the county records a fresh server can no longer fetch.

The county's records system regenerates some PDFs on every download, so their bytes (and SHA-256) no longer match
the file we read and checked. A server that has never stored them cannot get them back, and the seed refuses any
other file. This tool downloads every record in data/county; for each one that fails or comes back changed, it
copies the checked file from a local store (data/runtime, where it was saved when it still matched) into
data/county/<deal>/files/<sha256[:32]>.pdf, which the seed reads first (app/deals.py, real_record_bytes).

    python tools/county_bundle.py            # check all, bundle what is needed
    python tools/county_bundle.py --dry-run  # only report
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNTY = ROOT / "data" / "county"
RUNTIME = ROOT / "data" / "runtime"


def local_copy(slug: str, sha: str) -> bytes | None:
    for doc_file in (RUNTIME / "deals" / slug / "documents").glob("*.json"):
        doc = json.loads(doc_file.read_text(encoding="utf-8"))
        if doc.get("sha256") == sha and doc.get("file_key"):
            path = RUNTIME / "files" / doc["file_key"]
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
                return path.read_bytes()
    cached = RUNTIME / "county" / f"{sha[:32]}.pdf"
    if cached.is_file() and hashlib.sha256(cached.read_bytes()).hexdigest() == sha:
        return cached.read_bytes()
    return None


def fetches(url: str, sha: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PromiseLedger/2.0 (open-source civic tool)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return hashlib.sha256(resp.read(8_000_001)).hexdigest() == sha
    except Exception:  # noqa: BLE001 - any failure means a fresh server cannot fetch it
        return False


def main(dry_run: bool) -> int:
    bundled = missing = 0
    for manifest in sorted(COUNTY.glob("*/manifest.json")):
        slug = manifest.parent.name
        for entry in json.loads(manifest.read_text(encoding="utf-8")).get("documents") or []:
            sha, url = entry.get("sha256") or "", entry.get("url") or ""
            target = manifest.parent / "files" / f"{sha[:32]}.pdf"
            if target.is_file() or fetches(url, sha):
                continue
            data = local_copy(slug, sha)
            if data is None:
                print(f"NO LOCAL COPY  {slug} {entry.get('id')}")
                missing += 1
                continue
            print(f"bundle {slug} {entry.get('id')} ({len(data) // 1024} KB)")
            if not dry_run:
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(data)
            bundled += 1
    print(f"{bundled} bundled, {missing} with no local copy")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
