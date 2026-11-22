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



class CountyChecks(unittest.TestCase):
    """Sentences a careless or steered answer could write, each caught by code before anyone sees it."""

    def _kept(self, text, ids):
        agreements = county_ask._board_records(BOARD)
        recs = county_ask._summary_records(BOARD, agreements) | agreements
        reply = ask.AskReply(in_scope=True, sentences=[ask.AnswerSentence(text=text, claim_ids=ids)])
        kept, _ = ask.check(reply, recs, extra=county_ask._county_ok(BOARD), echo_ok=False)
        return bool(kept)

    def test_a_county_total_is_not_pinned_on_one_agreement(self):
        self.assertFalse(self._kept("Alpha Place states 150 affordable homes.", ["A1", "S11"]))
        self.assertTrue(self._kept("Alpha Place states 100 affordable homes.", ["A1"]))

    def test_another_agreements_figure_is_not_borrowed(self):
        self.assertFalse(self._kept("Alpha Place states 50 affordable homes.", ["A1", "A2"]))

    def test_every_or_none_needs_a_count_of_all_or_none(self):
        self.assertFalse(self._kept("None of the agreements contain wording for remedies.", ["S3"]))
        self.assertTrue(self._kept("Wording for reporting was found in every agreement read.", ["S1"]))

    def test_stage_and_judgement_words_are_removed(self):
        self.assertFalse(self._kept("Alpha Place is ratified and enforceable.", ["A1"]))
        self.assertFalse(self._kept("The owner of Beta Homes failed to comply.", ["A2"]))
        self.assertFalse(self._kept("Alpha Place's homes doubled.", ["A1"]))
        self.assertTrue(self._kept("Alpha Place was adopted by the Council.", ["A1"]))

    def test_a_summary_line_that_names_the_agreement_backs_its_numbers(self):
        self.assertTrue(self._kept("Beta Homes has a stated term that runs out by 2040, about 2038.", ["S11"]))

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

    def test_without_key_a_count_question_gets_the_computed_count(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
                mock.patch.object(county_ask, "_quote_records", return_value=({}, "keywords")):
            homes = county_ask.answer("How many affordable homes are stated in total?", board=BOARD)
            soon = county_ask.answer("Which terms run out soonest?", board=BOARD)
            remedy = county_ask.answer("Which agreements have no remedy wording?", board=BOARD)
        self.assertIn("state a count: 150.", homes["sentences"][0]["text"])
        self.assertIn("Beta Homes (about 2038)", soon["sentences"][0]["text"])
        self.assertIn("No wording found for remedies in 1 of 2", remedy["sentences"][0]["text"])

    def test_route_validates_question(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/county/ask", json={"question": "x"}).status_code, 422)
        self.assertEqual(client.post("/api/county/ask", json={"question": "y" * 400}).status_code, 422)


if __name__ == "__main__":
    unittest.main()


class RealQuestions(unittest.TestCase):
    """Questions from the live use test on Nov 22, answered by code."""
    board = {"deals": [dict(_row(1, "Alpha Place", 100, ALL), location={"city": "Hyattsville"}),
                       dict(_row(2, "Beta Homes", 50, dict(ALL, remedies=False), "2038-01-01", True), location={"city": "Bowie"})]}

    def ask(self, q):
        ask.CACHE.clear()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            return county_ask.answer(q, board=self.board)

    def text(self, q):
        return " ".join(s["text"] for s in self.ask(q)["sentences"])

    def test_a_window_of_years_counts_from_today(self):
        from datetime import date
        y = date.today().year
        self.assertIn(f"run out by {y + 5}: none of 2. The soonest stated end is Beta Homes (about 2038)",
                      self.text("Which agreements expire in the next five years?"))
        self.assertIn("by 2040: 1 of 2: Beta Homes", self.text("Which terms end by 2040?"))
        self.assertIn("by 2037: none", self.text("Any terms that run out before 2038?"))

    def test_most_and_fewest_homes(self):
        self.assertTrue(self.text("Which agreement has the most affordable homes?").startswith("Most affordable homes stated: Alpha Place (100); Beta Homes (50)"))
        self.assertTrue(self.text("Which deal has the fewest homes?").startswith("Fewest affordable homes stated: Beta Homes (50)"))

    def test_a_city_lists_its_agreements(self):
        t = self.text("is there affordable housing near hyattsville")
        self.assertIn("Agreements read in Hyattsville: 1 of 2: Alpha Place (100 affordable homes stated)", t)
        self.assertNotIn("Beta", t)

    def test_a_name_that_is_not_an_agreement_is_said_so(self):
        res = self.ask("How many homes are in Atlantis Towers?")
        self.assertEqual(res["sentences"], [])
        self.assertIn("named “Atlantis Towers”", res["notice"])
        self.assertTrue(self.text("How many homes are in Prince George's County in total?").startswith("Affordable homes stated across"))
        self.assertIn("Alpha Place", self.text("How many homes are in Alpha Place?"))

    def test_plain_definitions(self):
        res = self.ask("what does PILOT mean")
        self.assertIn("payment in lieu of taxes", res["sentences"][0]["text"])
        self.assertIn("plain definition", res["notice"])
        self.assertIn("area median income", self.text("What is AMI?"))


class SharedNames(unittest.TestCase):
    board = {"deals": [_row(1, "New Carrollton - Affordable - Phase 1", 112, ALL), _row(2, "New Carrollton - Affordable - Phase 2", 102, ALL),
                       _row(3, "Cottage City Towers Apartments", 100, ALL)]}

    def ask(self, q):
        ask.CACHE.clear()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            return county_ask.answer(q, board=self.board)

    def test_a_shared_name_answers_for_each_phase(self):
        t = self.ask("How many homes does New Carrollton have?")["sentences"][0]["text"]
        self.assertIn("New Carrollton agreements: 2 of 3: Affordable - Phase 1 (112 affordable homes stated)", t)
        self.assertIn("across them: 214", t)

    def test_one_word_of_a_real_name_does_not_make_a_name_known(self):
        self.assertIn("named “Atlantis Towers”", self.ask("How many homes are in Atlantis Towers?")["notice"])
