"""Checks on the static interface: what the page ships, and the rules it must keep."""
import json
import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
VIDEO_TITLES = [
    "Why new homes cost so much", "How cities help", "The deal", "What 60% of AMI means",
    "Why promises slip", "Meet Promise Ledger", "How it works", "Harbor Walk walkthrough",
]


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.html = cls.client.get("/").text

    def test_hero_and_actions(self):
        self.assertIn("Public support should come with a receipt.", self.html)
        self.assertIn("Open a sample deal", self.html)
        self.assertIn("Start a new deal", self.html)

    def test_demo_banner_stays(self):
        self.assertIn('class="demo-banner"', self.html)
        self.assertIn("Made-up demo data", self.html)

    def test_video_slots_match_the_manifest(self):
        manifest = json.loads((STATIC / "media" / "videos.json").read_text(encoding="utf-8"))["videos"]
        self.assertEqual([video["title"] for video in manifest], VIDEO_TITLES)
        for index, video in enumerate(manifest, start=1):
            self.assertTrue(video["slug"].startswith(f"{index:02d}-"))
            self.assertIn(f'data-video="{video["slug"]}"', self.html)
            self.assertIn(video["title"].replace("&", "&amp;"), self.html)

    def test_ready_videos_have_their_files(self):
        manifest = json.loads((STATIC / "media" / "videos.json").read_text(encoding="utf-8"))["videos"]
        for video in manifest:
            if video["ready"]:
                for ext in ("mp4", "vtt", "jpg"):
                    self.assertTrue((STATIC / "media" / f"{video['slug']}.{ext}").exists(), f"{video['slug']}.{ext} missing")

    def test_static_files_are_served(self):
        for name in ("app.js", "style.css", "mock.js", "pdfview.js", "media/videos.json"):
            self.assertEqual(self.client.get(f"/static/{name}").status_code, 200, name)


class Rules(unittest.TestCase):
    def setUp(self):
        self.js = {name: (STATIC / name).read_text(encoding="utf-8") for name in ("app.js", "mock.js", "pdfview.js")}
        self.css = (STATIC / "style.css").read_text(encoding="utf-8")

    def test_pdfjs_is_pinned_and_loaded_on_demand(self):
        self.assertRegex(self.js["pdfview.js"], r'PDFJS_VERSION = "\d+\.\d+\.\d+"')
        self.assertIn("GlobalWorkerOptions.workerSrc", self.js["pdfview.js"])
        self.assertIn('import("./pdfview.js")', self.js["app.js"])
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("pdfjs", html)

    def test_record_text_never_goes_in_as_html(self):
        # The only innerHTML write is the fixed deal template, which holds no record data.
        uses = re.findall(r"\.innerHTML\s*=\s*([^;]+);", self.js["app.js"])
        self.assertEqual(uses, ["DEAL_TEMPLATE"])
        self.assertNotIn("innerHTML", self.js["mock.js"] + self.js["pdfview.js"])
        self.assertNotIn("insertAdjacentHTML", self.js["app.js"])

    def test_neutral_wording(self):
        text = " ".join(self.js.values()).lower()
        for word in ("broke", "false claim", "misleading", "violat", "fraud"):
            self.assertNotIn(word, text)

    def test_reduced_motion_and_print(self):
        self.assertIn("prefers-reduced-motion: reduce", self.css)
        self.assertIn("@media print", self.css)
        self.assertIn('[data-theme="dark"]', self.css)

    def test_palette(self):
        for color in ("#0F172A", "#FAFAF7", "#0F766E", "#B45309", "#15803D"):
            self.assertIn(color, self.css)


if __name__ == "__main__":
    unittest.main()
