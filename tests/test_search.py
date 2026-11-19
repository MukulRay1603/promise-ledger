"""County search: by meaning with a key, by keywords without one; results are always checked quotes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import ai, search

ITEMS = [
    {"deal_id": "a", "deal": "Holly Place", "file": "CR-044-2026", "claim_id": "c1", "topic": "remedies",
     "document": "PILOT agreement", "date": "2026-05-26", "page": 4,
     "quote": "The County shall have a right of first refusal if the Owner sells the Property.", "v": [1, 0, 0]},
    {"deal_id": "b", "deal": "Penn Place I", "file": "CR-036-2025", "claim_id": "c9", "topic": "reporting",
     "document": "PILOT agreement", "date": "2025-03-07", "page": 6,
     "quote": "The Owner shall submit an annual income certification for each household.", "v": [0, 1, 0]},
]


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "search-index.json"
        path.write_text(json.dumps({"model": "gemini-embedding-001", "items": ITEMS}), encoding="utf-8")
        patch = mock.patch.object(search, "INDEX", path)
        patch.start()
        self.addCleanup(patch.stop)
        search.load_index.cache_clear()
        self.addCleanup(search.load_index.cache_clear)

    def test_without_a_key_it_searches_by_keywords(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            out = search.search("right of first refusal")
        self.assertEqual(out["mode"], "keywords")
        self.assertEqual([r["claim_id"] for r in out["results"]], ["c1"])
        self.assertNotIn("v", out["results"][0])  # Vectors stay on the server.

    def test_with_a_key_it_ranks_by_meaning_and_drops_weak_matches(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ai, "_live_calls", ai.deque()), \
                mock.patch.object(search, "embed", return_value=[[0.1, 1.0, 0.0]]):
            out = search.search("yearly tenant paperwork")
        self.assertEqual(out["mode"], "meaning")
        self.assertEqual([r["claim_id"] for r in out["results"]], ["c9"])  # c1 scores ~0.1, under the floor.

    def test_a_failed_embedding_falls_back_to_keywords(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ai, "_live_calls", ai.deque()), \
                mock.patch.object(search, "embed", side_effect=RuntimeError("down")):
            out = search.search("annual certification")
        self.assertEqual(out["mode"], "keywords")
        self.assertEqual(out["results"][0]["claim_id"], "c9")

    def test_empty_query_and_missing_index(self):
        self.assertEqual(search.search("   ")["results"], [])
        with mock.patch.object(search, "INDEX", Path(self.tmp.name) / "missing.json"):
            search.load_index.cache_clear()
            self.assertEqual(search.search("anything")["mode"], "none")

    def test_route(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            res = TestClient(app).get("/api/county/search", params={"q": "income certification"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["results"][0]["deal"], "Penn Place I")


if __name__ == "__main__":
    unittest.main()
