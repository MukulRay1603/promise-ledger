"""Self-healing (app/healing.py, storage retries) and the cheaper answer path (code first, cache, answer model)."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import ask, county_ask, deals, healing, storage

from tests.test_county_ask import BOARD


class StuckDocuments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = storage.LocalStorage(Path(self.tmp.name))
        self.store.put_deal({"id": "d1", "name": "Deal"})
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.store.put_document("d1", {"id": "x1", "status": "reading", "updated_at": old, "started_at": old})

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_stuck_document_is_queued_again_then_stopped(self):
        with mock.patch.object(deals, "submit") as submit, mock.patch.object(deals, "is_stale", return_value=True):
            for _ in range(healing.HEAL_MAX_RETRIES):
                self.assertEqual(healing.heal_stuck_documents(self.store)["requeued"], 1)
            last = healing.heal_stuck_documents(self.store)
        self.assertEqual(submit.call_count, healing.HEAL_MAX_RETRIES)
        self.assertEqual(last["stopped"], 1)
        doc = self.store.get_document("d1", "x1")
        self.assertEqual(doc["status"], "failed")
        self.assertIn("Press Retry", doc["error"])

    def test_one_failing_check_does_not_stop_the_others(self):
        with mock.patch.object(healing, "heal_search_index", side_effect=RuntimeError("boom")), \
                mock.patch.object(healing, "heal_county_data", return_value={"ok": True}), \
                mock.patch.object(deals, "submit"):
            checks = healing.run_once(self.store)
        self.assertFalse(checks["search_index"]["ok"])
        self.assertTrue(checks["storage"]["ok"])
        self.assertIn("answer_model", checks["model"])


class ServiceUnavailable(Exception):
    pass


class StorageRetries(unittest.TestCase):
    def test_a_transient_error_is_retried(self):
        inner = mock.Mock()
        inner.list_deals.side_effect = [ServiceUnavailable(), [{"id": "d1"}]]
        with mock.patch.object(storage, "RETRY_DELAYS", (0, 0)):
            self.assertEqual(storage.RetryingStorage(inner).list_deals(), [{"id": "d1"}])
        self.assertEqual(inner.list_deals.call_count, 2)

    def test_other_errors_and_locks_are_not_retried(self):
        inner = mock.Mock()
        inner.get_deal.side_effect = KeyError("x")
        inner.acquire_lock.side_effect = ServiceUnavailable()
        wrapped = storage.RetryingStorage(inner)
        with self.assertRaises(KeyError):
            wrapped.get_deal("d1")
        with self.assertRaises(ServiceUnavailable):
            wrapped.acquire_lock("n", "o", 5)
        self.assertEqual(inner.get_deal.call_count, 1)
        self.assertEqual(inner.acquire_lock.call_count, 1)


class CheaperAnswers(unittest.TestCase):
    def setUp(self):
        ask.CACHE.clear()

    def test_a_count_is_answered_by_code_with_no_model_call(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ask, "generate") as gen:
            res = county_ask.answer("Which agreements have no remedy wording?", board=BOARD)
        gen.assert_not_called()
        self.assertEqual(res["mode"], "computed")
        self.assertEqual(res["cost_usd"], 0.0)
        self.assertIn("No wording found for remedies in 1 of 2", res["sentences"][0]["text"])
        self.assertEqual([r["name"] for r in res["related"]], ["Beta Homes"])
        self.assertEqual(res["mentions"][0]["id"], "d2")
        self.assertEqual(len(res["follow_ups"]), 3)

    def test_one_agreements_figure_is_answered_by_code(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ask, "generate") as gen:
            res = county_ask.answer("How long is Alpha Place's stated term?", board=BOARD)
        gen.assert_not_called()
        self.assertIn("40 years", res["sentences"][0]["text"])

    def test_the_same_question_again_is_not_paid_twice(self):
        reply = ask.AskReply(in_scope=True, sentences=[ask.AnswerSentence(text="Alpha Place states 100 affordable homes.",
                                                                          claim_ids=["A1"])])
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(county_ask, "_quote_records", return_value=({}, "keywords")), \
                mock.patch.object(county_ask.ai, "_allow_live_call", return_value=True), \
                mock.patch.object(ask, "generate", return_value=(reply, 0.0015)) as gen:
            first = county_ask.answer("Why does Alpha Place matter?", board=BOARD)
            again = county_ask.answer("why does alpha place matter", board=BOARD)
        self.assertEqual(gen.call_count, 1)
        self.assertEqual(first["cost_usd"], 0.0015)
        self.assertTrue(again["cached"])
        self.assertEqual(again["cost_usd"], 0.0)

    def test_the_prompt_holds_only_what_the_question_needs(self):
        agreements = county_ask._board_records(BOARD)
        summaries = county_ask._summary_records(BOARD, agreements)
        recs = county_ask._prompt_records("What does Beta Homes say about remedies?", summaries, agreements, {})
        self.assertEqual({r["deal_id"] for r in recs.values() if r["id"].startswith("A")}, {"d2"})
        self.assertTrue(all("remedies" in r["quote"] for r in recs.values() if r["id"].startswith("S")))

    def test_answers_use_the_lite_model_first(self):
        self.assertEqual(ask.ask_model(), os.getenv("ASK_MODEL") or county_ask.ai.FALLBACK_MODEL)


if __name__ == "__main__":
    unittest.main()
