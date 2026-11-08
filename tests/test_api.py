import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import ai
from app import main
from app.main import app

SAMPLE = ai.load_sample()["text"]


class Busy(Exception):
    """Stands in for a google-genai APIError with an HTTP code."""

    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class ReadTimeout(Exception):
    """Stands in for an httpx timeout."""


class NoKey(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_models(self):
        with mock.patch.dict(os.environ, {"GEMINI_MODEL": "", "GEMINI_FALLBACK_MODEL": ""}):
            import importlib
            fresh = importlib.reload(ai)
            self.assertEqual(fresh.MODEL, "gemini-3.5-flash")
            self.assertEqual(fresh.FALLBACK_MODEL, "gemini-flash-lite-latest")
        importlib.reload(ai)

    def test_page_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        health = self.client.get("/api/health").json()
        self.assertTrue(health["ok"])
        self.assertEqual(health, self.client.get("/healthz").json())

    def test_page_ships_the_review_data(self):
        html = self.client.get("/").text
        start = html.index('id="review-data" type="application/json">') + len('id="review-data" type="application/json">')
        raw = html[start:html.index("</script>", start)]
        self.assertNotIn("<", raw)
        embedded = json.loads(raw)
        self.assertEqual(embedded["summary"], self.client.get("/api/review").json()["summary"])

    def test_record_text_cannot_close_the_script_tag(self):
        payload = {"notice": "</script><script>alert(1)</script>"}
        with mock.patch.object(main, "review", return_value=payload):
            html = self.client.get("/").text
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("\\u003c/script>", html)

    def test_review_data(self):
        data = self.client.get("/api/review").json()
        self.assertEqual(data["checks"]["passed"], data["checks"]["total"])
        self.assertEqual(data["checks"]["problems"], [])
        summary = data["summary"]
        self.assertEqual((summary["homes_described"], summary["homes_total"]), (12, 120))
        self.assertEqual(summary["sentences"][0], "12 of 120 homes described as affordable.")
        self.assertTrue(data["questions"])

    def test_sample_uses_saved_output(self):
        data = self.client.post("/api/extract", json={"text": SAMPLE}).json()
        self.assertEqual(data["mode"], "saved")
        self.assertEqual(len(data["candidates"]), 3)
        self.assertEqual(data["dropped"], 0)
        self.assertNotIn("not read", data["notice"])

    def test_other_text_says_it_was_not_read(self):
        data = self.client.post("/api/extract", json={"text": "Some other short record text."}).json()
        self.assertEqual(data["mode"], "saved")
        self.assertIn("not read", data["notice"])

    def test_text_limits(self):
        self.assertEqual(self.client.post("/api/extract", json={"text": "short"}).status_code, 422)
        too_long = "x" * (ai.MAX_INPUT_CHARS + 1)
        self.assertEqual(self.client.post("/api/extract", json={"text": too_long}).status_code, 422)


class WithKey(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "placeholder"})
        patcher.start()
        self.addCleanup(patcher.stop)
        ai._live_calls.clear()

    def candidate(self, quote):
        return ai.Candidate(quote=quote, topic="units", wording="will provide")

    def test_quote_not_in_text_is_dropped(self):
        good = "Harbor Walk Partners will provide 12 affordable homes at Harbor Walk."
        model_output = ai.Extraction(candidates=[self.candidate(good), self.candidate("All 500 homes were delivered.")])
        with mock.patch.object(ai, "_call_model", return_value=model_output):
            result = ai.extract(SAMPLE)
        self.assertEqual(result.mode, "live")
        self.assertEqual([c.quote for c in result.candidates], [good])
        self.assertEqual(result.dropped, 1)

    def test_output_has_no_status_and_is_flagged(self):
        quote = "Rents would stay below a limit to be set later."
        output = ai.Extraction(candidates=[self.candidate(quote)])
        with mock.patch.object(ai, "_call_model", return_value=output):
            item = ai.extract(SAMPLE).candidates[0].model_dump()
        self.assertNotIn("status", item)
        self.assertEqual(item["review"], ai.REVIEW_LABEL)

    def test_model_failure_falls_back(self):
        with mock.patch.object(ai, "_call_model", side_effect=RuntimeError("down")):
            result = ai.extract(SAMPLE)
        self.assertEqual(result.mode, "saved")
        self.assertIn("did not finish", result.notice)

    def test_busy_model_retries_once_with_fallback(self):
        quote = "Harbor Walk Partners will provide 12 affordable homes at Harbor Walk."
        output = ai.Extraction(candidates=[self.candidate(quote)])
        busy = Busy(503)
        with mock.patch.object(ai, "_call_model", side_effect=[busy, output]) as call:
            result = ai.extract(SAMPLE)
        self.assertEqual([c.args[1] for c in call.call_args_list], [ai.MODEL, ai.FALLBACK_MODEL])
        self.assertEqual(result.mode, "live")
        self.assertIn(ai.FALLBACK_MODEL, result.notice)

    def test_timeout_and_504_also_retry(self):
        output = ai.Extraction(candidates=[])
        for err in (Busy(504), TimeoutError(), ReadTimeout()):
            with mock.patch.object(ai, "_call_model", side_effect=[err, output]) as call:
                self.assertEqual(ai.extract(SAMPLE).mode, "live")
            self.assertEqual(call.call_count, 2)

    def test_fallback_failure_uses_saved_output(self):
        with mock.patch.object(ai, "_call_model", side_effect=[Busy(503), Busy(503)]) as call:
            result = ai.extract(SAMPLE)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result.mode, "saved")
        self.assertIn("did not finish", result.notice)

    def test_other_errors_do_not_retry(self):
        with mock.patch.object(ai, "_call_model", side_effect=Busy(400)) as call:
            result = ai.extract(SAMPLE)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result.mode, "saved")

    def test_live_calls_are_limited(self):
        output = ai.Extraction(candidates=[])
        with mock.patch.object(ai, "_call_model", return_value=output) as call:
            for _ in range(ai.MAX_LIVE_CALLS_PER_MINUTE + 1):
                result = ai.extract(SAMPLE)
        self.assertEqual(call.call_count, ai.MAX_LIVE_CALLS_PER_MINUTE)
        self.assertEqual(result.mode, "saved")

    def test_personal_details_are_redacted_before_the_model(self):
        text = "Call 410-555-0100 or write to someone@example.com about the homes."
        output = ai.Extraction(candidates=[])
        with mock.patch.object(ai, "_call_model", return_value=output) as call:
            ai.extract(text)
        sent = call.call_args.args[0]
        self.assertNotIn("555", sent)
        self.assertNotIn("example.com", sent)


if __name__ == "__main__":
    unittest.main()
