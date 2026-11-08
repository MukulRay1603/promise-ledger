"""The sample deals, read from the cached readings in data/readings/, match their gold answers.

No model is called: the API key is cleared, so a missing cached reading fails the document instead.
Regenerate the cache with `python evals/run_pdf_evals.py` after changing the prompt.
"""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from app import deals, pipeline, storage

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@unittest.skipUnless((SAMPLES / "harbor-walk" / "manifest.json").exists(), "sample deals not present")
class SampleDealsFromCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = storage.LocalStorage(Path(cls.tmp.name))
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), mock.patch.object(deals, "run_inline", True):
            cls.seeded = deals.seed(cls.store, samples_dir=SAMPLES)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def gold(self, slug):
        return json.loads((SAMPLES / slug / "expected_claims.json").read_text(encoding="utf-8"))

    def test_every_document_read_from_cache(self):
        self.assertEqual(sorted(self.seeded), ["beacon-point", "harbor-walk", "mill-street"])
        for slug in self.seeded:
            for doc in self.store.list_documents(slug):
                self.assertEqual(doc["status"], "done", f"{slug}/{doc['filename']}: {doc.get('error')} "
                                                        f"(prompt {pipeline.PROMPT_ID}; rerun the evals to refresh)")
                self.assertTrue(doc["from_cache"])

    def test_terms_differ_and_not_located_match_gold(self):
        for slug in self.seeded:
            review = deals.deal_review(slug, self.store)
            gold = self.gold(slug)
            self.assertEqual(sorted(t["key"] for t in review["terms"] if t["wording_differs"]),
                             sorted(d["term"] for d in gold["differs"]), slug)
            self.assertEqual(sorted(t["key"] for t in review["terms"] if not t["located"]),
                             sorted(gold["not_located"]), slug)

    def test_no_later_stage_than_gold(self):
        order = ["proposed", "supported", "signed", "delivered"]
        for slug in self.seeded:
            gold_by_file = {}
            for c in self.gold(slug)["claims"]:
                gold_by_file.setdefault(c["file"], set()).add(c["stage"])
            for doc in self.store.list_documents(slug):
                allowed = max((order.index(s) for s in gold_by_file.get(doc["filename"], {"proposed"})), default=0)
                for claim in doc["claims"]:
                    self.assertLessEqual(order.index(claim["status"]), allowed, f"{slug}: {claim['quote']}")

    def test_sample_reminders_are_fixed_by_as_of(self):
        rows = [(r["deal_id"], r["kind"], r["due"], r["overdue"]) for r in deals.all_reminders(self.store)]
        later = [(r["deal_id"], r["kind"], r["due"]) for r in deals.all_reminders(self.store, today=None)]
        self.assertEqual([r[:3] for r in rows], later)
        self.assertIn(("mill-street", "missing_record", "2026-03-31", True), rows)
        self.assertIn(("mill-street", "term_end", "2026-12-31", False), rows)
        beacon = [r for r in deals.all_reminders(self.store) if r["deal_id"] == "beacon-point"]
        self.assertEqual([(r["kind"], r["due"], r["overdue"]) for r in beacon], [("other", "2026-03-01", False)])
        self.assertIn("First yearly certificate", beacon[0]["text"])
        self.assertIn("not in the file yet", beacon[0]["text"])
        self.assertFalse(any(r[0] == "harbor-walk" for r in rows))

    def test_as_of_is_stored_on_the_deal(self):
        self.assertEqual(self.store.get_deal("beacon-point")["as_of"], "2025-07-01")
        self.assertLess(date.fromisoformat(self.store.get_deal("mill-street")["as_of"]), date(2026, 12, 31))


if __name__ == "__main__":
    unittest.main()
