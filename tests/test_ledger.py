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


class Summary(unittest.TestCase):
    """The at-a-glance numbers are counted from the records, so changing a record changes them."""

    def setUp(self):
        self.packet = copy.deepcopy(ledger.load_packet())
        self.claims = copy.deepcopy(ledger.load_claims()["claims"])
        self.notes = ledger.load_claims()["stage_notes"]

    def summary(self):
        terms = ledger.build_terms(self.claims)
        stages = ledger.build_stages(self.claims, self.notes)
        return ledger.build_summary(self.claims, terms, stages, self.packet)

    def questions(self):
        terms = ledger.build_terms(self.claims)
        stages = ledger.build_stages(self.claims, self.notes)
        return ledger.build_questions(self.claims, terms, stages, self.summary())

    def claim(self, claim_id):
        return next(c for c in self.claims if c["id"] == claim_id)

    def test_demo_numbers(self):
        s = self.summary()
        self.assertEqual((s["homes_described"], s["homes_total"]), (12, 120))
        self.assertEqual(s["homes_claim_id"], "c13")
        self.assertEqual(s["furthest_status"], "signed")
        self.assertEqual((s["terms_differ"], s["terms_not_located"], s["terms_total"]), (3, 2, 7))
        self.assertEqual(s["signers"], ["Harbor Walk Partners"])
        self.assertTrue(s["signed_by_developer_only"])
        self.assertFalse(s["city_signed"])

    def test_sentences_match_the_records(self):
        self.assertEqual(self.summary()["sentences"], [
            "12 of 120 homes described as affordable.",
            "Signed by the developer (Harbor Walk Partners) only; no City-signed agreement located.",
            "3 terms differ across records · 2 terms not located.",
        ])

    def test_counts_follow_the_terms(self):
        rent = {**self.claim("c13"), "id": "c99", "topic": "rent_limits", "value": "Rent limit"}
        self.claims.append(rent)
        s = self.summary()
        self.assertEqual(s["terms_not_located"], 1)
        self.assertIn("1 term not located.", s["sentences"][-1])

    def test_home_count_comes_from_the_furthest_record(self):
        self.claim("c13")["homes"] = {"count": 10}
        self.claim("c13")["value"] = "10 affordable homes"
        self.assertEqual(self.summary()["homes_described"], 10)
        self.claims = [c for c in self.claims if c["status"] != "signed"]
        s = self.summary()
        self.assertEqual((s["homes_described"], s["homes_claim_id"]), (12, "c10"))
        self.assertEqual(s["furthest_status"], "supported")

    def test_city_signature_is_read_from_the_packet(self):
        later = next(d for d in self.packet["documents"] if d["id"] == "later-letter")
        later["signed_by"] = ["City of Lantern Bay", "Harbor Walk Partners"]
        s = self.summary()
        self.assertTrue(s["city_signed"])
        self.assertFalse(s["signed_by_developer_only"])
        self.assertEqual(s["sentences"][1], "Signed by City of Lantern Bay, Harbor Walk Partners.")
        self.assertNotIn("city_signature", [q["key"] for q in self.questions()])

    def test_no_signed_record(self):
        for document in self.packet["documents"]:
            document["signed"], document["signed_by"] = False, []
        self.assertEqual(self.summary()["sentences"][1], "No signed record located.")

    def test_open_questions_cover_missing_and_differing_terms(self):
        tags = {(q["key"], q["tag"]) for q in self.questions()}
        for key in ("rent_limits", "remedies", "reporting", "city_signature", "delivery"):
            self.assertIn((key, "not_located"), tags)
        for key in ("units", "income_basis", "term"):
            self.assertIn((key, "differs"), tags)
        self.assertNotIn(("responsible_party", "differs"), tags)

    def test_home_count_must_be_in_the_quote(self):
        self.claim("c01")["homes"] = {"count": 13, "of": 120}
        problems = ledger.check_claim(self.claim("c01"), self.packet)
        self.assertTrue(any("home count 13" in p for p in problems))

    def test_signed_record_needs_a_signer(self):
        later = next(d for d in self.packet["documents"] if d["id"] == "later-letter")
        later["signed_by"] = []
        self.assertTrue(any("no signer" in p for p in ledger.check_packet(self.packet)))
        self.assertEqual(ledger.check_packet(ledger.load_packet()), [])


if __name__ == "__main__":
    unittest.main()
