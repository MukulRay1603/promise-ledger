"""Ask the county: answers only from checked county records."""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import ask, county_ask
from app.main import app


def _row(i, name, homes, found, term_end="2066-07-07", blanks=False):
    return {"id": f"d{i}", "name": name, "file": f"CR-00{i}-2025", "council_status": "Adopted", "passed": "2025-04-29",
            "records_read": 5, "homes": homes, "income_limit": "60% of area median income", "term_years": 40,
            "term_end": term_end, "term_end_estimated": True, "found": found,
            "template_text": [{"quote": "(insert specific dates)"}] if blanks else []}


ALL = {"reporting": True, "remedies": True, "rent_limits": False, "income_basis": True, "term": True}
BOARD = {"deals": [_row(1, "Alpha Place", 100, ALL), _row(2, "Beta Homes", 50, dict(ALL, remedies=False), "2038-01-01", True)]}


class Summaries(unittest.TestCase):
    def test_summary_lines_count_and_list(self):
        agreements = county_ask._board_records(BOARD)
        s = county_ask._summary_records(BOARD, agreements)
        text = " ".join(r["quote"] for r in s.values())
        self.assertIn("No wording found for remedies in 1 of 2 agreements read: Beta Homes.", text)
        self.assertIn("Stated terms that run out by 2040: 1 of 2: Beta Homes (about 2038).", text)
        self.assertIn("across 2 agreements that state a count: 150.", text)
        self.assertIn("affordable homes stated: 100", agreements["A1"]["quote"])

    def test_invented_number_is_removed(self):
        recs = county_ask._summary_records(BOARD, county_ask._board_records(BOARD))
        reply = ask.AskReply(in_scope=True, sentences=[
            ask.AnswerSentence(text="No remedy wording was found in 1 of 2 agreements.", claim_ids=["S4"]),
            ask.AnswerSentence(text="No remedy wording was found in 7 of 2 agreements.", claim_ids=["S4"]),
            ask.AnswerSentence(text="Beta Homes was signed in 2038.", claim_ids=["S4"])])
        kept, removed = ask.check(reply, recs)
        self.assertEqual([k["text"] for k in kept], ["No remedy wording was found in 1 of 2 agreements."])
        self.assertEqual(removed, 2)


class Route(unittest.TestCase):
    def test_without_key_only_quotes(self):
        quotes = {"Q1": {"id": "Q1", "quote": "The term is 40 years.", "status": None, "deal_id": "d1", "deal": "Alpha Place",
                         "claim_id": "r1-01", "page": 2, "document_title": "Resolution", "topic": "term"}}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
                mock.patch.object(county_ask, "_quote_records", return_value=(quotes, "keywords")):
            res = county_ask.answer("How long do the homes stay affordable?", board=BOARD)
        self.assertEqual(res["mode"], "quotes")
        self.assertEqual(res["sentences"][0]["text"], "“The term is 40 years.”")
        self.assertEqual(res["sources"]["Q1"]["claim_id"], "r1-01")

    def test_route_validates_question(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/county/ask", json={"question": "x"}).status_code, 422)
        self.assertEqual(client.post("/api/county/ask", json={"question": "y" * 400}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
