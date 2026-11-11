"""The real-record evaluation: labels and manifest in the repository, PDFs outside it. No model is called.

- The labels are well formed and the manifest names every file by URL and SHA-256. No PDF is committed.
- The runner reads PDFs from --pdf-dir, refuses a file whose hash differs, leaves excluded pages out of the scores,
  and counts a kept claim that matches an "also right" sentence as right without counting it for recall.
- evals/diagnose_misses.py puts each missed claim in the right bucket.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from app import ai, deals, pipeline

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
REAL = EVALS / "real" / "howard-county"
TERMS = {"units", "income_basis", "rent_limits", "term", "responsible_party", "reporting", "remedies", "public_support"}


def load(name):
    sys.path.insert(0, str(EVALS))
    spec = importlib.util.spec_from_file_location(name, EVALS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Labels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = json.loads((REAL / "expected_claims.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((REAL / "manifest.json").read_text(encoding="utf-8"))

    def test_labels_are_well_formed(self):
        claims = self.expected["claims"]
        files = {d["file"] for d in self.manifest["documents"]}
        self.assertEqual(len(claims), 31)
        self.assertEqual(len({c["id"] for c in claims}), 31)
        for c in claims:
            self.assertIn(c["term"], TERMS)
            self.assertIn(c["file"], files)
            self.assertIn(c["stage"], ("proposed", "supported"))  # Nothing in this record is signed or delivered.
            self.assertGreaterEqual(len(c["quote"]), 20)
        excluded = {(x["file"], n) for x in self.expected["excluded_pages"] for n in x["pages"]}
        self.assertFalse([c["id"] for c in claims if (c["file"], c["page"]) in excluded])
        for extra in self.expected["also_right"]:
            self.assertIn(extra["file"], files)
            self.assertIn(extra["term"], TERMS)

    def test_pdfs_are_named_by_url_and_hash_and_not_committed(self):
        for d in self.manifest["documents"]:
            self.assertTrue(d["url"].startswith("https://apps.howardcountymd.gov/"))
            self.assertRegex(d["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(list((EVALS / "real").rglob("*.pdf")), [])


def pdf(pages: list[str]) -> bytes:
    return deals.demo_pdf({"title": "T", "date": "2026", "pages": [{"paragraphs": [p]} for p in pages]})


class Runner(unittest.TestCase):
    """A two-page stand-in record in temporary folders, read from a cached reading."""

    KEEP = "The Owner shall reserve 20 of the 100 homes as affordable homes."
    ALSO = "The developer plans to reserve 20 of the 100 homes as affordable homes."
    COPY = "A scanned copy says the Owner shall reserve 20 of the 100 homes as affordable homes."
    MISSED = "The restrictions remain in effect for 30 years."

    def setUp(self):
        self.base = load("run_pdf_evals")
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.deal_dir, self.pdf_dir, self.readings = root / "labels" / "deal", root / "pdfs", root / "readings"
        for folder in (self.deal_dir, self.pdf_dir, self.readings):
            folder.mkdir(parents=True)
        data = pdf([f"{self.KEEP} {self.ALSO} {self.MISSED}", self.COPY])
        (self.pdf_dir / "a.pdf").write_bytes(data)
        self.sha = pipeline.file_hash(data)
        self.manifest = {"deal": "Stand-in", "owner": "Owner LLC", "city": "", "documents": [
            {"file": "a.pdf", "id": "a", "type": "Staff report", "date": "", "title": None, "sha256": self.sha,
             "url": "https://example.org/a.pdf"}]}
        self.expected = {"claims": [
            {"id": "g1", "term": "units", "quote": self.KEEP, "file": "a.pdf", "page": 1, "stage": "proposed"},
            {"id": "g2", "term": "term", "quote": self.MISSED, "file": "a.pdf", "page": 1, "stage": "proposed"}],
            "also_right": [{"file": "a.pdf", "term": "units", "quote": self.ALSO}],
            "excluded_pages": [{"file": "a.pdf", "pages": [2], "score": "ignore", "why": "copy"}],
            "not_located": [], "differs": []}
        self.write()
        cands = [ai.PdfCandidate(topic="units", quote=q, page=n, wording="", value="")
                 for q, n in ((self.KEEP, 1), (self.ALSO, 1), (self.COPY, 2))]
        cands.append(ai.PdfCandidate(topic="term", quote="The restrictions remain in effect for 40 years.", page=1, wording="", value=""))
        result = ai.ReadResult(mode="live", model="test", reading=ai.PdfReading(
            document_type="staff_report", title="T", date="", draft=False, signatures=[], candidates=cands))
        self.old = pipeline.READINGS_DIR, pipeline.READINGS_WRITE_DIR
        pipeline.READINGS_DIR, pipeline.READINGS_WRITE_DIR = self.readings, None
        pipeline.save_reading(self.sha, result)

    def tearDown(self):
        pipeline.READINGS_DIR, pipeline.READINGS_WRITE_DIR = self.old
        self.tmp.cleanup()

    def write(self):
        (self.deal_dir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.deal_dir / "expected_claims.json").write_text(json.dumps(self.expected), encoding="utf-8")

    def test_scores_from_a_pdf_folder(self):
        deal = self.base.run_deal(self.deal_dir, self.base.Budget(0), True, self.pdf_dir)
        # Kept: the labeled sentence and the "also right" one. The claim on the excluded page is left out.
        self.assertEqual((deal["gold"], deal["kept"], deal["matched"], deal["also_right"], deal["ignored"]), (2, 2, 1, 1, 1))
        self.assertEqual(deal["extra"], [])
        self.assertEqual([m["id"] for m in deal["missed"]], ["g2"])
        self.assertEqual(deal["false_signed_or_delivered"], [])

    def test_a_changed_file_is_refused(self):
        self.manifest["documents"][0]["sha256"] = "0" * 64
        self.write()
        with self.assertRaises(SystemExit) as stop:
            self.base.run_deal(self.deal_dir, self.base.Budget(0), True, self.pdf_dir)
        self.assertIn("SHA-256", str(stop.exception))

    def test_real_scores_are_printed_in_the_results_file(self):
        ev = load("run_heldout_evals")
        deal = self.base.run_deal(self.deal_dir, self.base.Budget(0), True, self.pdf_dir)
        deal["off_page"] = []
        entry = ev.real_entry([deal], {"date": "2026-11-11", "prompt_id": "abc"})
        self.assertEqual((entry["gold"], entry["matched"], entry["also_right"], entry["missed"]), (2, 1, 1, ["g2"]))
        text = "\n".join(ev.render_real({"runs": {"Before": entry, "After": entry}}))
        self.assertIn("| Measure | Before | After |", text)
        self.assertIn("| Recall (labeled statements found) | 50.0% (1/2) | 50.0% (1/2) |", text)
        self.assertIn("| Kept claims that are right | 100.0% (2/2) | 100.0% (2/2) |", text)
        self.assertEqual(ev.render_real({"runs": {}}), [])

    def test_miss_buckets(self):
        diag = load("diagnose_misses")
        pages = [f"{self.KEEP} {self.MISSED} The City may inspect the leasing records on 10 days' notice."]

        def bucket(gold_quote, *cands):
            reading = ai.PdfReading(document_type="other", title="", date="", draft=False, signatures=[], candidates=[
                ai.PdfCandidate(topic=t, quote=q, page=1, wording="", value="") for t, q in cands])
            return diag.why_missed({"quote": gold_quote}, reading, pages)[0]

        self.assertEqual(bucket(self.MISSED), "a")
        self.assertEqual(bucket(self.MISSED, ("units", self.KEEP)), "a")
        self.assertEqual(bucket(self.MISSED, ("term", "The restrictions shall remain in effect for 30 years.")), "b")
        inspect = "The City may inspect the leasing records on 10 days' notice."
        self.assertEqual(bucket(inspect, ("reporting", inspect)), "c")
        self.assertEqual(bucket(self.MISSED, ("term", self.MISSED)), "d")  # Proposed and it passes: lost as a duplicate.


if __name__ == "__main__":
    unittest.main()
