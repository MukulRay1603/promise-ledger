"""Tester feedback: saved without identifying details unless asked; read back only with the server's token."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import feedback, storage


class Feedback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = storage.LocalStorage(Path(self.tmp.name))

    def test_a_name_is_kept_only_when_the_tester_asks_to_be_quoted_by_name(self):
        feedback.save(feedback.FeedbackIn(role="staff", quote="anonymous", name="Dana", title="DHCD"), self.store)
        feedback.save(feedback.FeedbackIn(role="resident", quote="named", name="Sam", title="Tenant"), self.store)
        rows = feedback.read_all(self.store)
        self.assertEqual([(r["role"], r["name"]) for r in rows], [("staff", ""), ("resident", "Sam")])
        self.assertTrue(all("ip" not in r and "session" not in r for r in rows))

    def test_times_and_ratings_are_bounded(self):
        with self.assertRaises(Exception):
            feedback.FeedbackIn(role="staff", trust=9)
        with self.assertRaises(Exception):
            feedback.FeedbackIn(role="staff", by_hand={"seconds": -5})

    def test_reading_back_needs_the_token(self):
        with mock.patch.dict(os.environ, {"FEEDBACK_TOKEN": ""}):
            self.assertFalse(feedback.allowed("anything"))
        with mock.patch.dict(os.environ, {"FEEDBACK_TOKEN": "s3cret-token"}):
            self.assertFalse(feedback.allowed(None))
            self.assertFalse(feedback.allowed("wrong"))
            self.assertTrue(feedback.allowed("s3cret-token"))

    def test_routes(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        with mock.patch.object(feedback, "get_store", return_value=self.store):
            self.assertEqual(client.post("/api/feedback", json={"role": "student", "with_tool": {"seconds": 40, "found": "yes"}}).status_code, 201)
            self.assertEqual(client.post("/api/feedback", json={"role": "wizard"}).status_code, 422)
            self.assertEqual(client.get("/api/feedback").status_code, 404)
            with mock.patch.dict(os.environ, {"FEEDBACK_TOKEN": "t0ken-value"}):
                res = client.get("/api/feedback", headers={"X-Feedback-Token": "t0ken-value"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()[0]["with_tool"]["seconds"], 40)


if __name__ == "__main__":
    unittest.main()
