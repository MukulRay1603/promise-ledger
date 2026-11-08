"""Check the sample deal PDFs in data/samples/ against their gold answers.

Every gold quote must appear word for word on its stated page, using pypdf text
extraction. Line breaks in the extracted text are treated as spaces; nothing else
is normalized, so a hyphenated line break or a ligature would fail.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"
DEALS = ["harbor-walk", "beacon-point", "mill-street"]
TERMS = ["units", "income_basis", "rent_limits", "term", "responsible_party", "reporting", "remedies"]
TOPICS = set(TERMS) | {"public_support"}
STAGES = {"proposed", "supported", "signed", "delivered"}
FOOTER = "SAMPLE DOCUMENT · fictional · for demonstration"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load(slug: str, name: str) -> dict:
    return json.loads((SAMPLES / slug / name).read_text(encoding="utf-8"))


@unittest.skipIf(PdfReader is None, "pypdf is not installed (pip install pypdf)")
class SampleDeals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {}  # (slug, file) -> list of page texts
        for slug in DEALS:
            for d in load(slug, "manifest.json")["documents"]:
                reader = PdfReader(SAMPLES / slug / d["file"])
                cls.pages[(slug, d["file"])] = [flat(p.extract_text()) for p in reader.pages]

    def test_manifest_page_counts(self):
        for slug in DEALS:
            m = load(slug, "manifest.json")
            self.assertEqual(m["city"], "Lantern Bay")
            for d in m["documents"]:
                for key in ("file", "type", "date", "title", "pages"):
                    self.assertIn(key, d, f"{slug}/{d.get('file')}")
                self.assertTrue(1 <= d["pages"] <= 4, f"{slug}/{d['file']} has {d['pages']} pages")
                self.assertEqual(len(self.pages[(slug, d["file"])]), d["pages"], f"{slug}/{d['file']}")

    def test_every_page_has_footer(self):
        for (slug, file), pages in self.pages.items():
            for n, text in enumerate(pages, 1):
                self.assertIn(FOOTER, text, f"{slug}/{file} page {n}")

    def test_quotes_appear_on_their_page(self):
        for slug in DEALS:
            gold = load(slug, "expected_claims.json")
            for c in gold["claims"] + gold.get("observations", []):
                with self.subTest(deal=slug, id=c["id"]):
                    pages = self.pages[(slug, c["file"])]
                    self.assertLessEqual(c["page"], len(pages))
                    self.assertIn(c["quote"], pages[c["page"] - 1],
                                  f"{c['id']} not on {c['file']} page {c['page']}")
                    others = [i + 1 for i, t in enumerate(pages) if i + 1 != c["page"] and c["quote"] in t]
                    self.assertEqual(others, [], f"{c['id']} also appears on page(s) {others}")

    def test_gold_fields_are_consistent(self):
        for slug in DEALS:
            gold = load(slug, "expected_claims.json")
            docs = {d["file"]: d for d in load(slug, "manifest.json")["documents"]}
            ids = [c["id"] for c in gold["claims"]]
            self.assertEqual(len(ids), len(set(ids)), slug)
            for c in gold["claims"]:
                self.assertIn(c["term"], TOPICS, c["id"])
                self.assertIn(c["stage"], STAGES, c["id"])
                self.assertIn(c["file"], docs, c["id"])
                self.assertIn(c["wording"].lower(), c["quote"].lower(), c["id"])
                if c["stage"] == "signed":
                    self.assertTrue(docs[c["file"]]["signed_by"], f"{c['id']} is signed but its document is not")
            located = {c["term"] for c in gold["claims"]}
            self.assertEqual(gold["not_located"], [t for t in TERMS if t not in located], slug)
            for d in gold["differs"]:
                self.assertIn(d["term"], TERMS)
                self.assertTrue(set(d["claims"]) <= set(ids), slug)

    def test_harbor_walk_matches_old_demo(self):
        demo = json.loads((ROOT / "data" / "demo" / "claims.json").read_text(encoding="utf-8"))["claims"]
        gold = {c["id"]: c for c in load("harbor-walk", "expected_claims.json")["claims"]}
        self.assertEqual(set(gold), {c["id"] for c in demo})
        for c in demo:
            self.assertEqual((gold[c["id"]]["quote"], gold[c["id"]]["page"], gold[c["id"]]["stage"]),
                             (c["quote"], c["page"], c["status"]), c["id"])

    def test_beacon_point_signed_by_both(self):
        docs = load("beacon-point", "manifest.json")["documents"]
        agreement = next(d for d in docs if d["id"] == "agreement")
        self.assertEqual(agreement["signed_by"], ["City of Lantern Bay", "Beacon Point Housing LLC"])
        signed_terms = {c["term"] for c in load("beacon-point", "expected_claims.json")["claims"]
                        if c["stage"] == "signed"}
        self.assertTrue(set(TERMS) <= signed_terms)

    def test_mill_street_follow_up(self):
        gold = load("mill-street", "expected_claims.json")
        self.assertEqual(gold["follow_up"], {"term_ends": "2026-12-31", "reports_not_received": ["2025"]})
        memo = self.pages[("mill-street", "03-staff-memo-2026.pdf")][0]
        self.assertIn("2025 March 31, 2026 Not received", memo)

    def test_generator_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(ROOT / "tools" / "make_samples.py"), tmp], check=True,
                           capture_output=True)
            for slug in DEALS:
                for f in sorted((SAMPLES / slug).iterdir()):
                    self.assertEqual((Path(tmp) / slug / f.name).read_bytes(), f.read_bytes(), f"{slug}/{f.name}")


if __name__ == "__main__":
    unittest.main()
