"""Say why each labeled claim was missed, from readings that are already cached. Makes no model calls.

Every missed claim falls in one bucket:
  a  never proposed   the model did not list the sentence
  b  not located      the model listed it, but the quote check did not find it on any page
  c  term rule        found on the page, then rejected by term_fits (it shows as a sentence to check)
  d  other drop       found, then dropped as boilerplate, as "term is missing" wording, or as a duplicate

Usage:
  python evals/diagnose_misses.py                                   # sample, held-out and adversarial sets
  python evals/diagnose_misses.py --pdf-dir <folder>                # also the real record (see evals/real/)
  python evals/diagnose_misses.py --pdf-dir <folder> --readings-dir <folder>/readings --list
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

import run_pdf_evals as base  # noqa: E402
from app import ai, pipeline  # noqa: E402

BUCKETS = {"a": "never proposed", "b": "quote not located", "c": "rejected by the term rule", "d": "other drop"}
SETS = {"dev": ROOT / "data" / "samples", "heldout": ROOT / "evals" / "heldout",
        "adversarial": ROOT / "evals" / "adversarial", "real": ROOT / "evals" / "real"}


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", pipeline.normalize(text).lower())


def about_same(candidate: str, gold: str) -> bool:
    """The candidate is this labeled sentence, even if the model changed a few characters of it."""
    if base.same_quote(candidate, gold):
        return True
    c, g = _key(candidate), _key(gold)
    short, long_ = sorted((c, g), key=len)
    if len(short) < base.MIN_MATCH_CHARS:
        return False
    if short in long_:
        return True
    blocks = difflib.SequenceMatcher(None, short, long_, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) >= 0.85 * len(short)


def why_missed(gold: dict, reading: ai.PdfReading, pages: list[str]) -> tuple[str, str]:
    """(bucket, the candidate quote that came closest). Mirrors the order of checks in pipeline.verify_reading."""
    close = [c for c in reading.candidates if about_same(c.quote, gold["quote"])]
    if not close:
        return "a", ""
    located = [c for c in close if pipeline.locate(c.quote, pages, c.page) is not None]
    if not located:
        return "b", close[0].quote
    chrome = pipeline.repeated_lines(pages)
    alive = [c for c in located if not pipeline._ABSENT.search(pipeline.normalize(c.quote))
             and not pipeline.is_boilerplate(c.quote, chrome)]
    if not alive:
        return "d", located[0].quote
    if not any(pipeline.term_fits(c.topic, c.quote) for c in alive):
        return "c", alive[0].quote
    return "d", alive[0].quote


def diagnose(folder: Path, pdf_dir: Path | None = None) -> list[dict]:
    rows = []
    for deal_dir in sorted(p.parent for p in folder.glob("*/expected_claims.json")):
        deal = base.run_deal(deal_dir, base.Budget(0), True, pdf_dir)
        manifest = json.loads((deal_dir / "manifest.json").read_text(encoding="utf-8"))
        gold = {g["id"]: g for g in json.loads((deal_dir / "expected_claims.json").read_text(encoding="utf-8"))["claims"]}
        loaded: dict[str, tuple] = {}
        for entry in manifest["documents"]:
            data = ((pdf_dir or deal_dir) / entry["file"]).read_bytes()
            hit = pipeline.cached_reading(pipeline.file_hash(data))
            if hit and hit.get("reading"):
                loaded[entry["file"]] = (ai.PdfReading.model_validate(hit["reading"]), pipeline.extract_pages(data))
        for miss in deal["missed"]:
            g = gold[miss["id"]]
            if g["file"] not in loaded:
                rows.append({"deal": deal["deal"], "id": g["id"], "term": g["term"], "bucket": "unread", "quote": g["quote"]})
                continue
            bucket, cand = why_missed(g, *loaded[g["file"]])
            rows.append({"deal": deal["deal"], "id": g["id"], "term": g["term"], "bucket": bucket,
                         "quote": g["quote"], "candidate": cand})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", help="folder with the real record's PDFs; without it the real set is skipped")
    parser.add_argument("--readings-dir", help="cached readings of the real record (default <pdf-dir>/readings)")
    parser.add_argument("--list", action="store_true", help="print every missed claim with its bucket")
    args = parser.parse_args()
    print(f"prompt {pipeline.PROMPT_ID}")
    print(f"{'set':12} {'missed':>6}  " + "  ".join(f"{k}: {v}" for k, v in BUCKETS.items()))
    committed = pipeline.READINGS_DIR
    for name, folder in SETS.items():
        pdf_dir = None
        pipeline.READINGS_DIR = committed
        if name == "real":
            if not args.pdf_dir:
                continue
            pdf_dir = Path(args.pdf_dir)
            pipeline.READINGS_DIR = Path(args.readings_dir) if args.readings_dir else pdf_dir / "readings"
        rows = diagnose(folder, pdf_dir)
        counts = {k: sum(r["bucket"] == k for r in rows) for k in [*BUCKETS, "unread"]}
        print(f"{name:12} {len(rows):6}  " + "  ".join(f"{k}={counts[k]}" for k in BUCKETS)
              + (f"  unread={counts['unread']}" if counts["unread"] else ""))
        if args.list:
            for r in rows:
                print(f"   {r['bucket']}  {r['id']:5} {r['term']:17} {r['quote'][:100]}")
                if r.get("candidate") and r["bucket"] in ("b", "d"):
                    print(f"      model wrote: {r['candidate'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
