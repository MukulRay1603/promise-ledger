import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import ai
from app.main import app

SAMPLE = ai.load_sample()["text"]


class NoKey(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_page_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertTrue(self.client.get("/healthz").json()["ok"])

    def test_review_data(self):
        data = self.client.get("/api/review").json()
        self.assertEqual(data["checks"]["passed"], data["checks"]["total"])
        self.assertEqual(data["checks"]["problems"], [])

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
