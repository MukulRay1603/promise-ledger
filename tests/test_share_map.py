"""Link previews, share links and the county map data."""
import json
import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import deals
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


class SharePreviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_has_absolute_preview_image(self):
        html = self.client.get("/").text
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        self.assertIsNotNone(m)
        self.assertTrue(m.group(1).startswith("http"), m.group(1))
        self.assertTrue((ROOT / "app" / "static" / "og" / "site.png").is_file())

    def test_unknown_or_bad_deal_is_404(self):
        self.assertEqual(self.client.get("/s/no-such-deal").status_code, 404)
        self.assertEqual(self.client.get("/s/bad%20id!").status_code, 404)

    def test_share_page_escapes_and_redirects(self):
        row = {"id": "x-cr-1-2026", "name": 'A <b>"Quoted"</b> place', "homes": 12, "term_end": "2066-07-07",
               "term_end_estimated": True, "file": "CR-1-2026"}
        orig = deals.county_board
        deals.county_board = lambda *a, **k: {"deals": [row]}
        try:
            res = self.client.get("/s/x-cr-1-2026")
        finally:
            deals.county_board = orig
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("<b>", res.text)
        self.assertIn("12 affordable homes stated", res.text)
        self.assertIn("2066+", res.text)
        self.assertIn('og:image" content="http', res.text)
        self.assertIn("/#/deals/x-cr-1-2026", res.text)


class CountyMapData(unittest.TestCase):
    def test_locations_name_their_record(self):
        path = ROOT / "data" / "county" / "locations.json"
        locs = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(locs), 10)
        for slug, loc in locs.items():
            self.assertTrue((ROOT / "data" / "county" / slug / "manifest.json").is_file(), slug)
            self.assertTrue(38.5 < loc["lat"] < 39.2 and -77.2 < loc["lon"] < -76.6, slug)  # Inside the county's box.
            self.assertTrue(loc["source"]["record"] and loc["source"]["page"], slug)
            self.assertRegex(loc["address"], r"^\d", slug)

    def test_boundary_ships_both_outlines(self):
        b = json.loads((ROOT / "data" / "county" / "boundary.json").read_text())
        self.assertEqual(set(b["shapes"]), {"Prince George's County", "Washington, DC"})

    def test_board_carries_map_and_totals(self):
        board = deals.county_board()
        self.assertIn("map", board)
        for key in ("pages", "located", "cost_usd"):
            self.assertIn(key, board["totals"])


if __name__ == "__main__":
    unittest.main()
