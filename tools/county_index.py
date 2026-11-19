"""Build data/county/search-index.json: one embedding per checked quote in the real county deals.

    python tools/county_index.py --env path/to/.env

Run after tools/county_read.py. Seeds the county deals from their saved readings in a temporary store (no live
reading), takes every checked claim, and embeds its quote with Gemini (gemini-embedding-001, 256 dimensions).
Vectors are rounded to 4 decimals to keep the file small. The quotes are from public records.
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
    args = parser.parse_args()
    if args.env:
        from dotenv import dotenv_values
        os.environ["GEMINI_API_KEY"] = dotenv_values(args.env).get("GEMINI_API_KEY") or ""
    tmp = tempfile.mkdtemp(prefix="pl-index-")
    os.environ.update(STORAGE="local", RUNTIME_DIR=tmp, COUNTY_DEALS="1")
    from app import deals, search, storage

    store = storage.LocalStorage(Path(tmp))
    items = []
    for path in sorted(deals.COUNTY_DIR.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        deal_id = deals.seed_sample(path, store)
        for doc in store.list_documents(deal_id):
            if doc.get("status") != "done":
                continue
            for c in doc.get("claims") or []:
                items.append({"deal_id": deal_id, "deal": manifest["deal"], "file": manifest["source"]["file"],
                              "claim_id": c["id"], "topic": c["topic"], "document": c.get("document_type"),
                              "date": c.get("date"), "page": c.get("page"), "quote": c["quote"]})
        print(f"{manifest['source']['file']}: {len(items)} quotes so far", flush=True)
    vectors = []
    # The free tier counts each quote in a batch as one request, 100 a minute: 50 quotes, then a 32-second pause.
    for start in range(0, len(items), 50):
        batch = [it["quote"][:2000] for it in items[start:start + 50]]
        for attempt in range(4):
            try:
                vectors += search.embed(batch, "RETRIEVAL_DOCUMENT")
                break
            except Exception as err:
                if "429" not in str(err) or attempt == 3:
                    raise
                time.sleep(65)
        print(f"embedded {len(vectors)} of {len(items)}", flush=True)
        time.sleep(32)
    for it, v in zip(items, vectors):
        it["v"] = [round(x, 4) for x in v]
    search.INDEX.write_text(json.dumps({"model": search.EMBED_MODEL, "dim": search.DIM, "built": time.strftime("%Y-%m-%d"),
                                        "count": len(items), "items": items}, separators=(",", ":")) + "\n",
                            encoding="utf-8")
    print(f"Indexed {len(items)} quotes into {search.INDEX.relative_to(ROOT)} "
          f"({search.INDEX.stat().st_size / 1e6:.1f} MB).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
