"""Records request letter: drafted by code, optionally edited by the model and checked."""
import os
import unittest
from unittest import mock

from app import ai, request_letter as rl

DEAL = {"name": "Holly Place", "county": "Prince George's County, MD", "source": {"file": "CR-044-2026"}}
REVIEW = {
    "city": "Prince George's County",
    "next_records": [
        {"key": "delivery", "record": "Certificate of occupancy or compliance report",
         "why": "Shows whether the homes were built and leased.", "terms": []},
        {"key": "agreement_full", "record": "The full signed agreement",
         "why": "Some terms were not located in it.", "terms": ["Reporting", "Remedies"]},
    ],
    "terms": [{"label": "Reporting", "located": False}, {"label": "Term", "located": True}],
    "documents": [{"status": "done", "title": "CR-044-2026 Transmittal", "date": "2026-05-26"},
                  {"status": "failed", "title": "Broken file"}],
}


class Draft(unittest.TestCase):
    def test_the_code_draft_asks_for_each_missing_record_and_cites_the_law(self):
        d = rl.draft(DEAL, REVIEW)
        self.assertEqual(d["mode"], "template")
        self.assertIn("CR-044-2026", d["subject"])
        self.assertIn("Maryland Public Information Act", d["body"])
        self.assertIn("1. Any certificate of occupancy, compliance report or annual certification", d["body"])
        self.assertIn("In particular, the parts that state: reporting, remedies.", d["body"])
        self.assertNotIn("Some terms were not located in it", d["body"])  # Our notes to the user stay out of the letter.
        self.assertIn("I have not found wording for these terms in the records I have: Reporting.", d["body"])
        self.assertIn("- CR-044-2026 Transmittal (2026-05-26)", d["body"])  # Records on file are not asked for again.
        self.assertNotIn("Broken file", d["body"])
        self.assertIn("[Your name]", d["body"])

    def test_outside_maryland_the_letter_names_no_specific_law(self):
        d = rl.draft({"name": "Harbor Walk"}, {**REVIEW, "city": "Lantern Bay"})
        self.assertIn("your state's public records law", d["body"])


class Polish(unittest.TestCase):
    def setUp(self):
        self.base = rl.draft(DEAL, REVIEW)

    def edit(self, body, subject=None):
        return rl.Letter(subject=subject or self.base["subject"], body=body)

    def test_a_faithful_edit_passes(self):
        self.assertIsNone(rl.check(self.edit(self.base["body"].replace("I request", "I am requesting")), self.base))

    def test_an_invented_number_or_date_is_rejected(self):
        self.assertIn("numbers", rl.check(self.edit(self.base["body"] + "\nPlease reply within 30 days."), self.base))

    def test_a_dropped_record_is_rejected(self):
        body = self.base["body"].replace("The complete signed agreement", "The agreement")
        self.assertIn("dropped", rl.check(self.edit(body), self.base))

    def test_an_added_link_is_rejected(self):
        self.assertIn("link", rl.check(self.edit(self.base["body"] + "\nSee https://example.org"), self.base))

    def test_without_a_key_the_code_draft_is_returned(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            out = rl.letter(DEAL, REVIEW, polish=True)
        self.assertEqual(out["mode"], "template")
        self.assertIn("off", out["notice"])

    def test_a_rejected_model_edit_falls_back_to_the_draft(self):
        bad = rl.Letter(subject="x", body="Please send everything within 10 days.")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(rl, "_call", return_value=bad), \
                mock.patch.object(ai, "_live_calls", ai.deque()):
            out = rl.letter(DEAL, REVIEW, polish=True)
        self.assertEqual(out["mode"], "template")
        self.assertIn("was not used", out["notice"])

    def test_an_accepted_model_edit_is_returned(self):
        good = rl.Letter(subject=self.base["subject"], body=self.base["body"].replace("Thank you,", "With thanks,"))
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(rl, "_call", return_value=good), \
                mock.patch.object(ai, "_live_calls", ai.deque()):
            out = rl.letter(DEAL, REVIEW, polish=True)
        self.assertEqual(out["mode"], "polished")
        self.assertIn("With thanks,", out["body"])


class Route(unittest.TestCase):
    def test_route_returns_a_draft_for_a_sample_deal(self):
        from fastapi.testclient import TestClient
        from app import deals
        from app.main import app

        deals.seed()
        client = TestClient(app)
        deal_id = client.get("/api/deals").json()[0]["id"]
        res = client.post(f"/api/deals/{deal_id}/request-letter", json={"polish": False})
        self.assertEqual(res.status_code, 200)
        self.assertIn("[Your name]", res.json()["body"])


if __name__ == "__main__":
    unittest.main()
