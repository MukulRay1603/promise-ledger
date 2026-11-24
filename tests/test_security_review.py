"""Fixes from the Nov 10 security review: body caps, no echoed input, id checks, headers, the PDF child's env."""
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import deals, pipeline, storage
from app.main import app


class Requests(unittest.TestCase):
    def setUp(self):
        self.prev = storage._store
        storage.set_store(storage.LocalStorage(tempfile.mkdtemp()))
        deals.seed()
        self.client = TestClient(app)

    def tearDown(self):
        storage.set_store(self.prev)

    def test_large_json_body_is_refused_before_parsing(self):
        res = self.client.post("/api/deals/nope/decisions", content=b'{"x":"' + b"a" * 200_000 + b'"}',
                               headers={"Content-Type": "application/json"})
        self.assertEqual(res.status_code, 413)
        self.assertLess(len(res.content), 200)

    def test_validation_errors_do_not_echo_input(self):
        secret = "q" * 400
        res = self.client.post("/api/deals/harbor-walk/ask", json={"question": secret})
        self.assertEqual(res.status_code, 422)
        self.assertNotIn(secret, res.text)
        self.assertIn("question", res.json()["detail"])

    def test_bad_ids_are_404_not_500(self):
        for bad in ("a" * 500, "a%0Ab", "a.b"):
            self.assertEqual(self.client.get(f"/api/deals/{bad}").status_code, 404, bad)
        self.assertEqual(self.client.get(f"/api/deals/harbor-walk/documents/{'x' * 500}").status_code, 404)

    def test_api_docs_are_not_public(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertNotEqual(self.client.get(path).status_code, 200, path)

    def test_headers(self):
        res = self.client.get("/api/health")
        self.assertIn("max-age=31536000", res.headers["strict-transport-security"])
        self.assertIn("microphone=(self)", res.headers["permissions-policy"])


class Sandbox(unittest.TestCase):
    def test_child_gets_no_secrets(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k", "SOME_TOKEN": "t", "PATH_EXTRA": "p"}):
            env = pipeline.sandbox_options(10)["env"]
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertNotIn("SOME_TOKEN", env)
        self.assertIn("PATH_EXTRA", env)


if __name__ == "__main__":
    unittest.main()
