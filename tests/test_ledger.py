import copy
import re
import unittest
from pathlib import Path

from app import ledger

ROOT = Path(__file__).resolve().parent.parent


class ClaimChecks(unittest.TestCase):
    def setUp(self):
        self.packet = ledger.load_packet()
        self.claims = copy.deepcopy(ledger.load_claims()["claims"])
        self.claim = self.claims[0]

    def problems(self, claim):
        return ledger.check_claim(claim, self.packet)

    def test_every_claim_passes(self):
        self.assertEqual(ledger.check_all(self.claims, self.packet), [])

    def test_changed_quote_is_flagged(self):
        self.claim["quote"] = self.claim["quote"].replace("12", "13")
        self.assertTrue(any("quote not found" in p for p in self.problems(self.claim)))

    def test_quote_on_wrong_page_is_flagged(self):
        self.claim["page"] = 2
        self.assertTrue(any("quote not found" in p for p in self.problems(self.claim)))

    def test_missing_page_is_flagged(self):
        self.claim["page"] = 99
        self.assertTrue(any("page 99" in p for p in self.problems(self.claim)))

    def test_wrong_date_is_flagged(self):
        self.claim["date"] = "2025-02-04"
        self.assertTrue(any("date" in p for p in self.problems(self.claim)))

    def test_signed_needs_a_signed_document(self):
        self.claim["status"] = "signed"
        self.assertTrue(any("not signed" in p for p in self.problems(self.claim)))

    def test_delivered_is_never_accepted_without_records(self):
        self.claim["status"] = "delivered"
        self.assertTrue(any("delivered" in p for p in self.problems(self.claim)))

    def test_bad_arithmetic_is_flagged(self):
        claim = next(c for c in self.claims if "math" in c)
        claim["math"]["equals"] = 13
        self.assertTrue(any("percent" in p for p in self.problems(claim)))

    def test_bad_vote_count_is_flagged(self):
        claim = next(c for c in self.claims if "vote" in c)
        claim["vote"]["present"] = 8
        self.assertTrue(any("vote" in p for p in self.problems(claim)))

    def test_duplicate_id_is_flagged(self):
        self.claims.append(copy.deepcopy(self.claim))
        self.assertTrue(any("duplicate" in p for p in ledger.check_all(self.claims, self.packet)))


class ReviewPage(unittest.TestCase):
    def setUp(self):
        self.review = ledger.build_review()

    def test_absent_terms_read_not_located(self):
        terms = {t["key"]: t for t in self.review["terms"]}
        self.assertEqual(list(terms), list(ledger.TERMS))
        for key in ("rent_limits", "remedies"):
            self.assertEqual(terms[key]["result"], "Not located")
            self.assertEqual(terms[key]["values"], [])

    def test_differing_wording_is_shown(self):
        terms = {t["key"]: t for t in self.review["terms"]}
        self.assertTrue(terms["income_basis"]["wording_differs"])
        self.assertTrue(terms["term"]["wording_differs"])
        self.assertFalse(terms["responsible_party"]["wording_differs"])

    def test_stages_stay_separate(self):
        stages = {s["status"]: s for s in self.review["stages"]}
        self.assertEqual(list(stages), list(ledger.STATUSES))
        self.assertEqual(stages["delivered"]["result"], "Not located")
        ids = [i for s in stages.values() for i in s["claim_ids"]]
        self.assertEqual(len(ids), len(set(ids)))


class DemoRules(unittest.TestCase):
    def test_packet_has_the_five_records(self):
        types = [d["type"] for d in ledger.load_packet()["documents"]]
        self.assertEqual(types, ["Staff summary", "Draft letter", "Developer slides", "Minutes", "Later letter"])

    def test_every_page_is_labeled_made_up(self):
        for document in ledger.load_packet()["documents"]:
            for page in document["pages"]:
                self.assertIn("MADE-UP", page["paragraphs"][0])

    def test_wording_stays_neutral_and_on_topic(self):
        blocked = re.compile(
            r"\b(broke|broken|breach|false|misleading|lied|violat\w+|tenant\w*|renter\w*|landlord\w*|college park)\b",
            re.IGNORECASE,
        )
        files = [*(ROOT / "data" / "demo").glob("*.json"), *(ROOT / "app" / "static").glob("*.html")]
        for path in files:
            text = path.read_text(encoding="utf-8").replace(": false", "")  # JSON booleans
            self.assertIsNone(blocked.search(text), path.name)


if __name__ == "__main__":
    unittest.main()
