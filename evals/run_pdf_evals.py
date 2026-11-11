"""Run the PDF pipeline on the sample deals and score it against each deal's expected_claims.json.

For every sample PDF: extract page text, read it with the model (or the cached reading for that
file hash in data/readings/), check quotes and decide stages in code, then compare with the gold claims.

Scores
- quote precision: kept claims that match a gold quote on the same file and page / kept claims
- quote recall:    gold claims matched / gold claims
- page accuracy:   matched claims on the gold page (the pipeline corrects pages, so this should be 100%)
- stage accuracy:  matched claims whose stage equals the gold stage
- false signed / delivered: kept claims labeled signed or delivered where gold says otherwise (must be 0)

Usage:
  python evals/run_pdf_evals.py              # uses cached readings, live calls only for new files
  python evals/run_pdf_evals.py --budget 30  # cap live model calls (default 30)
  python evals/run_pdf_evals.py --no-cache   # ignore cached readings (still capped)
  python evals/run_pdf_evals.py --env path/.env   # read GEMINI_API_KEY / GEMINI_MODEL from another file
Writes evals/results-pdf.json (gitignored).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402


def _env_path(argv: list[str]) -> Path:
    """--env has to be read before app.ai is imported, because the model name is fixed at import."""
    for i, arg in enumerate(argv):
        if arg == "--env" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--env="):
            return Path(arg.split("=", 1)[1])
    return ROOT / ".env"


if __name__ == "__main__":  # When another runner imports this module, that runner has loaded the key already.
    load_dotenv(_env_path(sys.argv[1:]))

from app import ai, deals, pipeline  # noqa: E402

SAMPLES = ROOT / "data" / "samples"
MIN_MATCH_CHARS = 20


def same_quote(pred: str, gold: str) -> bool:
    """Containment either way, after normalizing. Gold quotes are sometimes a clause of a longer sentence."""
    p, g = pipeline.normalize(pred).lower().rstrip("."), pipeline.normalize(gold).lower().rstrip(".")
    short = min(len(p), len(g))
    return short >= MIN_MATCH_CHARS and (p in g or g in p)


def match(preds: list[dict], golds: list[dict]) -> list[tuple[dict, dict]]:
    """Greedy one-to-one pairs on the same file, preferring the same term."""
    pairs, used = [], set()
    for pred in preds:
        options = [g for g in golds if g["id"] not in used and g["file"] == pred["file"] and same_quote(pred["quote"], g["quote"])]
        if not options:
            continue
        best = next((g for g in options if g["term"] == pred["topic"]), options[0])
        used.add(best["id"])
        pairs.append((pred, best))
    return pairs


class Budget:
    def __init__(self, calls: int):
        self.left = calls
        self.used = 0

    def reader(self, pages):
        if self.left <= 0:
            return ai.ReadResult(mode="limited", notice="Eval call budget used up.")
        self.left -= 1
        self.used += 1
        return ai.read_document(pages)


def run_deal(folder: Path, budget: Budget, use_cache: bool, pdf_dir: Path | None = None) -> dict:
    """Read and score one deal. With pdf_dir the PDFs are read from that folder (records kept outside the repo),
    and each file must match the SHA-256 in the manifest."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    expected = json.loads((folder / "expected_claims.json").read_text(encoding="utf-8"))
    gold = expected["claims"]
    reviewed_docs = []
    known = [manifest.get("owner") or "", f"City of {manifest.get('city')}"]
    preds, docs = [], []
    # Pages left out of every score ("ignore"), such as a scanned copy of another record in the same file.
    ignore = {(x["file"], n) for x in expected.get("excluded_pages", []) if x.get("score") == "ignore" for n in x["pages"]}
    ignored = 0
    for entry in manifest["documents"]:
        data = ((pdf_dir or folder) / entry["file"]).read_bytes()
        if entry.get("sha256") and pipeline.file_hash(data) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} is not the file the labels were written for (SHA-256 differs). "
                             f"Download it again from {entry.get('url')}.")
        pages = pipeline.extract_pages(data)
        sha = pipeline.file_hash(data)
        result, cached = pipeline.read_with_cache(sha, pages, reader=budget.reader, use_cache=use_cache)
        row = {"file": entry["file"], "pages": len(pages), "mode": result.mode, "cached": cached,
               "model": result.model, "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
               "cost_usd": result.cost_usd}
        if result.reading is None:
            row["error"] = result.notice
            docs.append(row)
            continue
        checked = pipeline.verify_reading(result.reading, pages, {"id": entry["id"], "type": entry["type"],
                                                                   "date": entry["date"], "title": entry["title"]}, known)
        expected_signers = sorted(entry.get("signed_by") or [])
        row.update(stage=checked["stage"], signed_by=checked["signed_by"], expected_signed_by=expected_signers,
                   **{f"n_{k}": v for k, v in checked["counts"].items()})
        docs.append(row)
        reviewed_docs.append({"id": entry["id"], "status": "done", "created_at": "", **checked})
        for claim in checked["claims"]:
            if (entry["file"], claim["page"]) in ignore:
                ignored += 1
                continue
            preds.append({**claim, "file": entry["file"]})

    review = deals.build_deal_review({"id": folder.name, "name": manifest["deal"], "city": manifest.get("city") or "",
                                      "developer": manifest.get("owner")}, reviewed_docs)
    got_differs = {t["key"] for t in review["terms"] if t["wording_differs"]}
    got_missing = {t["key"] for t in review["terms"] if not t["located"]}
    want_differs = {d["term"] for d in expected.get("differs", [])}
    want_missing = set(expected.get("not_located", []))
    pairs = match(preds, gold)
    matched_gold = {g["id"] for _, g in pairs}
    by_pred = {id(p): g for p, g in pairs}
    # Sentences that state a term correctly but repeat a labeled statement, so they are not in the count for recall.
    # A kept claim that matches one is not an error. Only the real record lists any.
    also = expected.get("also_right", [])
    also_right = [p for p in preds if id(p) not in by_pred
                  and any(a["file"] == p["file"] and same_quote(p["quote"], a["quote"]) for a in also)]
    by_also = {id(p) for p in also_right}
    false_late = []
    for p in preds:
        if p["status"] in ("signed", "delivered"):
            g = by_pred.get(id(p))
            gold_stages = {x["stage"] for x in gold if x["file"] == p["file"]}
            if (g and g["stage"] != p["status"]) or (not g and p["status"] not in gold_stages):
                false_late.append({"file": p["file"], "quote": p["quote"], "status": p["status"]})
    return {
        "deal": manifest["deal"],
        "documents": docs,
        "gold": len(gold),
        "kept": len(preds),
        "ignored": ignored,
        "matched": len(pairs),
        "also_right": len(also_right),
        # A sentence that runs over a page break is cited to the page where it starts; the label may be on either.
        "page_ok": sum(g["page"] in (p["page"], p.get("ends_on_page")) for p, g in pairs),
        "stage_ok": sum(p["status"] == g["stage"] for p, g in pairs),
        "term_ok": sum(p["topic"] == g["term"] for p, g in pairs),
        "false_signed_or_delivered": false_late,
        "claims": [{"file": p["file"], "topic": p["topic"], "status": p["status"], "page": p["page"],
                    "stated_page": p["stated_page"], "quote": p["quote"]} for p in preds],
        "terms_differ": {"expected": sorted(want_differs), "got": sorted(got_differs)},
        "terms_not_located": {"expected": sorted(want_missing), "got": sorted(got_missing)},
        "term_checks_ok": got_differs == want_differs and got_missing == want_missing,
        "furthest_stage": review["summary"]["furthest_status"],
        "missed": [{"id": g["id"], "file": g["file"], "term": g["term"], "quote": g["quote"]}
                   for g in gold if g["id"] not in matched_gold],
        "extra": [{"file": p["file"], "topic": p["topic"], "status": p["status"], "quote": p["quote"]}
                  for p in preds if id(p) not in by_pred and id(p) not in by_also],
        "stage_misses": [{"gold": g["id"], "expected": g["stage"], "got": p["status"], "quote": g["quote"]}
                         for p, g in pairs if p["status"] != g["stage"]],
    }


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}%" if b else "  n/a"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=str(ROOT / ".env"), help="file with GEMINI_API_KEY and GEMINI_MODEL")
    parser.add_argument("--budget", type=int, default=30, help="most live model calls to make")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached readings")
    args = parser.parse_args()
    folders = sorted(p.parent for p in SAMPLES.glob("*/expected_claims.json"))
    if not folders:
        print("No sample deals in data/samples/.")
        return 1
    budget = Budget(args.budget)
    deals = [run_deal(f, budget, not args.no_cache) for f in folders]

    print(f"{'deal':14} {'gold':>4} {'kept':>4} {'match':>5}  precision  recall  page   stage  false s/d")
    totals = {k: 0 for k in ("gold", "kept", "matched", "page_ok", "stage_ok", "term_ok")}
    false_total = 0
    for d in deals:
        for k in totals:
            totals[k] += d[k]
        false_total += len(d["false_signed_or_delivered"])
        print(f"{d['deal']:14} {d['gold']:4} {d['kept']:4} {d['matched']:5}  {pct(d['matched'], d['kept']):>9} "
              f"{pct(d['matched'], d['gold']):>7} {pct(d['page_ok'], d['matched']):>6} {pct(d['stage_ok'], d['matched']):>6} "
              f"{len(d['false_signed_or_delivered']):>6}")
    t = totals
    print(f"{'ALL':14} {t['gold']:4} {t['kept']:4} {t['matched']:5}  {pct(t['matched'], t['kept']):>9} "
          f"{pct(t['matched'], t['gold']):>7} {pct(t['page_ok'], t['matched']):>6} {pct(t['stage_ok'], t['matched']):>6} "
          f"{false_total:>6}")
    print(f"term agreement on matched claims: {pct(t['term_ok'], t['matched'])}")
    print("\nterm checks (differs / not located):")
    for d in deals:
        print(f"  {d['deal']:14} {'OK  ' if d['term_checks_ok'] else 'DIFF'} differs got {d['terms_differ']['got']} "
              f"want {d['terms_differ']['expected']} · not located got {d['terms_not_located']['got']} "
              f"want {d['terms_not_located']['expected']}")

    print("\nper document:")
    tok_in = tok_out = cost = 0
    for d in deals:
        for doc in d["documents"]:
            tok_in += doc["tokens_in"]; tok_out += doc["tokens_out"]; cost += doc["cost_usd"]
            src = "cache" if doc["cached"] else doc["mode"]
            extra = (f"stage={doc.get('stage')} signed_by={doc.get('signed_by')} kept={doc.get('n_kept')}/"
                     f"{doc.get('n_candidates')} page_fixed={doc.get('n_page_corrected')} dropped={doc.get('n_dropped')}"
                     if "stage" in doc else doc.get("error", ""))
            print(f"  {doc['file']:38} {src:6} {doc['model'] or '-':24} in={doc['tokens_in']:6} out={doc['tokens_out']:5} "
                  f"${doc['cost_usd']:.5f}  {extra}")
    print(f"\nrecords read live this run: {budget.used} (model calls with retries: {ai.pdf_calls}) · tokens in {tok_in}, out {tok_out} · est. cost ${cost:.4f} "
          f"(at ${ai.PRICE_IN_PER_M}/M in, ${ai.PRICE_OUT_PER_M}/M out; cached rows show their original cost)")

    out = ROOT / "evals" / "results-pdf.json"
    out.write_text(json.dumps({"totals": totals, "false_signed_or_delivered": false_total, "deals": deals,
                               "live_calls": budget.used}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"details: {out.relative_to(ROOT)}")
    ok = false_total == 0 and all("stage" in doc for d in deals for doc in d["documents"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
