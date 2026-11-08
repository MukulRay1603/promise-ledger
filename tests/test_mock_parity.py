"""The in-browser mock must export the same columns and sheets as the server, so offline previews match."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import deals, ledger

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
NODE = shutil.which("node")

SCRIPT = """
globalThis.location = { origin: "http://localhost" };
const { createMock } = await import(process.argv[2]);
const seed = JSON.parse(await (await import("node:fs/promises")).readFile(process.argv[3], "utf8"));
const mock = createMock(seed);
const review = await mock.handle("GET", "/api/deals/harbor-walk/review");
const claim = review.claims[0].id;
await mock.handle("POST", "/api/deals/harbor-walk/decisions",
  { target_type: "claim", target_id: claim, decision: "confirmed", note: "=1+1" }, { reviewer: "Dana Ortiz", session: "a".repeat(24) });
const preview = await mock.handle("GET", "/api/deals/harbor-walk/export.json");
const csv = await (await mock.handle("GET", "/api/deals/harbor-walk/export.csv")).text();
console.log(JSON.stringify({ preview, csv }));
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class MockExportParity(unittest.TestCase):
    def test_mock_export_matches_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.json"
            seed.write_text(json.dumps(ledger.build_review() | {"extraction": {}}), encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            script.write_text(SCRIPT, encoding="utf-8")
            out = subprocess.run([NODE, str(script), (STATIC / "mock.js").as_uri(), str(seed)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=60, check=True).stdout
        data = json.loads(out)
        sheets = data["preview"]["sheets"]
        self.assertEqual([s["name"] for s in sheets], ["Claims", "Terms", "Open questions", "Review log", "About"])
        self.assertEqual(sheets[0]["columns"], deals.CLAIM_COLUMNS)
        self.assertEqual(sheets[1]["columns"], deals.TERM_COLUMNS)
        self.assertEqual(sheets[2]["columns"], deals.QUESTION_COLUMNS)
        self.assertEqual(sheets[3]["columns"], deals.LOG_COLUMNS)
        first = dict(zip(sheets[0]["columns"], sheets[0]["rows"][0]))
        self.assertEqual((first["Decision"], first["Reviewer"], first["Note"]), ("Confirmed", "Dana Ortiz", "'=1+1"))
        self.assertEqual(len(sheets[3]["rows"]), 1)
        header = data["csv"].splitlines()[0]
        self.assertEqual(header, ",".join(deals.CLAIM_COLUMNS))


if __name__ == "__main__":
    unittest.main()
