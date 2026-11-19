"""Read the real county records once with the live model and save the readings to data/readings/.

The app never reads a real county record live: it seeds those deals only from these saved readings
(app/deals.py, seed_sample). Run this after tools/county_import.py, with a Gemini key:

    python tools/county_read.py --env path/to/.env              # every county deal still missing a reading
    python tools/county_read.py --env path/to/.env --only CR-044-2026
    python tools/county_read.py --dry-run                        # list what would be read, no calls

Readings are keyed by the PDF's SHA-256 and the prompt version, like the sample readings, so re-running reads
only what is missing. Scanned pages of these public records are transcribed by the model (SCANS_TO_MODEL=1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", help="file with GEMINI_API_KEY")
    parser.add_argument("--only", nargs="*", help="council file numbers, e.g. CR-044-2026")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-usd", type=float, default=6.0, help="stop once the estimated spend passes this")
    parser.add_argument("--model", help="read with this model only (e.g. gemini-3.5-flash-lite when the main model "
                                         "is overloaded); the model is saved with each reading")
    args = parser.parse_args()
    if args.model:
        os.environ["GEMINI_MODEL"] = os.environ["GEMINI_FALLBACK_MODEL"] = args.model
    if args.env:
        from dotenv import dotenv_values
        key = dotenv_values(args.env).get("GEMINI_API_KEY")
        if key:
            os.environ["GEMINI_API_KEY"] = key  # Only the key: the model names come from app/ai.py defaults.
    os.environ.setdefault("SCANS_TO_MODEL", "1")
    os.environ["COUNTY_DEALS"] = "1"
    tmp = tempfile.mkdtemp(prefix="pl-county-")
    os.environ["STORAGE"] = "local"
    os.environ["RUNTIME_DIR"] = tmp

    from app import ai, deals, pipeline, storage

    # A batch of public records is not in a hurry: stay well under the free tier's per-minute quota.
    ai.MAX_LIVE_CALLS_PER_MINUTE = int(os.getenv("COUNTY_CALLS_PER_MINUTE") or 8)

    store = storage.LocalStorage(Path(tmp))
    manifests = sorted(deals.COUNTY_DIR.glob("*/manifest.json"))
    if args.only:
        wanted = set(args.only)
        manifests = [m for m in manifests if json.loads(m.read_text(encoding="utf-8"))["source"]["file"] in wanted]
    spent, read, failed, started = 0.0, 0, [], time.time()
    for number, path in enumerate(manifests, 1):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        deal_id = deals.seed_sample(path, store)  # Downloads and checks the PDFs; reads nothing live.
        docs = store.list_documents(deal_id)
        todo = [d for d in docs if not pipeline.cached_reading(d["sha256"])]
        print(f"[{number}/{len(manifests)}] {manifest['source']['file']} {manifest['deal']}: "
              f"{len(docs)} records, {len(todo)} to read", flush=True)
        if args.dry_run:
            continue
        for doc in todo:
            if spent > args.max_usd:
                print(f"Stopping: estimated spend ${spent:.2f} passed --max-usd {args.max_usd}.", flush=True)
                return 1
            deals.process_document(deal_id, doc["id"], store)
            done = store.get_document(deal_id, doc["id"]) or {}
            if done.get("status") != "done":  # Usually a per-minute quota: wait it out and try once more.
                time.sleep(65)
                deals.process_document(deal_id, doc["id"], store)
                done = store.get_document(deal_id, doc["id"]) or {}
            spent += float(done.get("cost_usd") or 0)
            ok = done.get("status") == "done" and pipeline.cached_reading(doc["sha256"])
            read += bool(ok)
            if not ok:
                failed.append((manifest["source"]["file"], doc.get("title"), done.get("status"), done.get("error")))
            print(f"    {'ok ' if ok else 'NO '} {doc.get('type')}: {done.get('model') or '-'} "
                  f"${float(done.get('cost_usd') or 0):.4f} (total ${spent:.2f}, {time.time() - started:.0f}s)", flush=True)
    print(f"\nRead {read} record(s), {len(failed)} not read, estimated ${spent:.2f}.")
    for item in failed:
        print("  not read:", *item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
