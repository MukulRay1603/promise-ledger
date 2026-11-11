"""Checks on the static interface: what the page ships, and the rules it must keep."""
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main
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
        self.assertIn("check the affordable-housing commitments a developer made in exchange for a tax break or other public support, with the source page one click away.", self.html)

    def test_landing_sections(self):
        for title in ("The problem", "How it works", "Proof", "Learn the basics", "Who it’s for", "See a deal checked"):
            self.assertIn(title, self.html)
        # Proof figures are from evals/run_pdf_evals.py on the sample deals, and say so.
        for count in ('data-count="96"', 'data-count="98"', 'data-count="0"', 'data-count="3"'):
            self.assertIn(count, self.html)
        self.assertIn("On sample data", self.html)
        self.assertIn("https://github.com/MukulRay1603/promise-ledger", self.html)

    def test_export_preview_dialog(self):
        self.assertIn('id="export-dialog"', self.html)
        for label in ("Download .xlsx", "Download .csv", "Copy as CSV", ">Close<"):
            self.assertIn(label, self.html)

    def test_theme_button_names_its_target(self):
        self.assertIn('<span class="theme-label">Dark mode</span>', self.html)
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('dark ? "Light mode" : "Dark mode"', js)

    def test_guided_tour(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("Take the 60-second tour", self.html)
        self.assertIn('href="#/deals/harbor-walk/tour"', self.html)
        self.assertEqual(js.count("    title: \""), 6)  # Six steps.
        for step in ("Upload", "Claims", "View source", "What changed", "People decide", "Receipt and share"):
            self.assertIn(f'title: "{step}"', js)
        self.assertIn('event.key === "Escape"', js)
        self.assertIn("reducedMotion.matches", js)

    def test_decision_dialog(self):
        for text in ("Confirm", "Needs follow-up", "Disputed", 'maxlength="500"', 'id="dd-name"'):
            self.assertIn(text, self.html)

    def test_command_menu_is_labelled(self):
        self.assertIn('id="cmdk"', self.html)
        self.assertIn('role="combobox"', self.html)
        self.assertIn('aria-label="Search"', self.html)

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

    def test_video_viewer_is_in_page(self):
        self.assertIn('id="video-dialog"', self.html)
        self.assertIn('id="vv-strip"', self.html)
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        # Captions are burned into the videos; the text track is offered but must not show by default.
        track = script[script.index('el("track"'):].split(")", 1)[0]
        self.assertNotIn("default", track)

    def test_about_and_roadmap_pages(self):
        for view in ("about", "roadmap"):
            self.assertIn(f'data-view="{view}"', self.html)
            self.assertIn(f'href="#/{view}" data-nav="{view}"', self.html)
        # Team credit, Mukul first, with the links the team gave.
        about = self.html[self.html.index('id="view-about"'):self.html.index('id="view-roadmap"')]
        self.assertLess(about.index("Mukul Rayana"), about.index("Karthik Ramanathan"))
        for link in ("https://mukulray1603.github.io", "https://www.linkedin.com/in/mukul-rayana/",
                     "https://github.com/Karthik0803", "https://www.linkedin.com/in/karthik-ramanathan-4902471b3/"):
            self.assertIn(link, about)
        # New-tab links say so to screen readers and keep rel=noopener.
        for tag in re.findall(r'<a [^>]*target="_blank"[^>]*>.*?</a>', about, flags=re.S):
            self.assertIn('rel="noopener"', tag)
            self.assertIn("opens in a new tab", tag)
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('const STATIC_PAGES = { roadmap: "Roadmap", about: "About" };', script)
        # The roadmap is six tabbed panels; each tab names the panel it controls.
        roadmap = self.html[self.html.index('id="view-roadmap"'):]
        roadmap = roadmap[:roadmap.index("</section>")]
        tabs = re.findall(r'role="tab" id="(rmt-\w+)" aria-controls="(rmp-\w+)"', roadmap)
        self.assertEqual(len(tabs), 6)
        for tab, panel in tabs:
            self.assertIn(f'id="{panel}" aria-labelledby="{tab}"', roadmap)
        self.assertIn("function setupPageTabs", script)

    def test_media_reports_lengths(self):
        with mock.patch.dict(os.environ, {"MEDIA_BASE_URL": ""}):
            data = self.client.get("/api/media").json()
        self.assertTrue(all(isinstance(video["secs"], int) and 30 <= video["secs"] <= 90 for video in data["videos"]))

    def test_media_falls_back_to_static(self):
        with mock.patch.dict(os.environ, {"MEDIA_BASE_URL": ""}):
            data = self.client.get("/api/media").json()
        self.assertEqual(data["base"], "/static/media/")
        self.assertEqual([video["title"] for video in data["videos"]], VIDEO_TITLES)
        for video in data["videos"]:
            present = all((STATIC / "media" / f"{video['slug']}.{ext}").is_file() for ext in ("mp4", "vtt", "jpg"))
            self.assertEqual(video["ready"], present)

    def test_media_base_url_is_used(self):
        def fake_ready(base, slugs):
            return {slug: slug.startswith("01") for slug in slugs}
        env = {"MEDIA_BASE_URL": "https://storage.example/bucket/media"}
        with mock.patch.dict(os.environ, env), mock.patch.object(main, "_remote_ready", side_effect=fake_ready):
            data = self.client.get("/api/media").json()
        self.assertEqual(data["base"], "https://storage.example/bucket/media/")
        self.assertEqual([v["ready"] for v in data["videos"]], [True] + [False] * 7)

    def test_static_files_are_served(self):
        for name in ("app.js", "style.css", "mock.js", "pdfview.js"):
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

    def test_no_bare_null_children(self):
        # replaceChildren prints null as text, so optional children must go through a filtered list.
        js = self.js["app.js"]
        bad = []
        for m in re.finditer(r"\.replaceChildren\(", js):
            i, depth = m.end(), 1
            while depth:
                depth += {"(": 1, ")": -1}.get(js[i], 0)
                i += 1
            body = js[m.end():i - 1]
            if body.lstrip().startswith("..."):
                continue
            # Only top-level arguments matter: drop nested calls before looking for ": null".
            top, level = [], 0
            for ch in body:
                level += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
                top.append(ch if level == 0 or ch in "([{" else "")
            if re.search(r":\s*null", "".join(top)):
                bad.append(js.count(chr(10), 0, m.start()) + 1)
        self.assertEqual(bad, [])

    def test_neutral_wording(self):
        text = " ".join(self.js.values()).lower()
        for word in ("broke", "false claim", "misleading", "violat", "fraud"):
            self.assertNotIn(word, text)

    def test_overview_video(self):
        # The overview loads from YouTube's privacy-enhanced domain only after a press.
        js = self.js["app.js"]
        self.assertIn("https://www.youtube-nocookie.com/embed/aD03n_4KfFc", js)
        self.assertIn('play.addEventListener("click"', js)
        self.assertTrue((STATIC / "media" / "overview.jpg").exists())

    def test_no_commitments_note(self):
        # A deal whose files were all read but hold no commitment says so, instead of looking stuck.
        js = self.js["app.js"]
        self.assertIn('id: "no-claims-note"', js)
        self.assertIn("does not state", js)
        self.assertIn("none of them states", js)
        # The file list may only hide it; only the review render shows it, so a stale review never shows it.
        self.assertIn("noClaimsNote({ canShow: false });", js)
        self.assertIn("noClaimsNote({ canShow: true });", js)

    def test_next_records_panel(self):
        # The upload assistant draws the server's rule-based list under the files; no model is asked.
        js = self.js["app.js"]
        self.assertIn('id: "next-records"', js)
        self.assertIn("Records to ask for next", js)
        self.assertIn("renderNextRecords();", js)
        self.assertIn(".next-records", self.css)

    def test_promise_building(self):
        # The building pictures the checked home counts only; it respects reduced motion and is left out of print.
        js = self.js["app.js"]
        self.assertIn('id="promise-scene"', js)
        self.assertIn("function sceneData(review)", js)
        self.assertIn('role: "img"', js)
        self.assertIn("Drawn from checked quotes only", js)
        self.assertIn(".scene-animate .scene-lit { animation: none", self.css)
        self.assertIn(".promise-scene { display: none !important; }", self.css)

    def test_paper_trail(self):
        # The trail is a real table, uses the server's own "wording differs" decision, and links each value to its source.
        js = self.js["app.js"]
        self.assertIn('id="paper-trail"', js)
        self.assertIn("term.wording_differs && normValue(value) !== normValue(previous)", js)
        self.assertIn('el("table", { class: "trail" }', js)
        self.assertIn("openSource(claim, event.currentTarget)", js)
        self.assertIn(".trail-wrap { display: none !important; }", self.css)

    def test_reduced_motion_and_print(self):
        self.assertIn("prefers-reduced-motion: reduce", self.css)
        self.assertGreaterEqual(self.css.count("prefers-reduced-motion: reduce"), 3)  # Base, landing and printer layers.

    def test_receipt_prints_and_stamps(self):
        self.assertIn("@keyframes feed", self.css)
        self.assertIn("@keyframes stamp", self.css)
        self.assertIn("function printOut", self.js["app.js"])
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="printer-slot"', html)
        self.assertIn('class="receipt-stamp" aria-hidden="true">Flagged for human review', html)
        self.assertIn("reducedMotion.matches", self.js["app.js"])
        self.assertIn("@media print", self.css)
        self.assertIn('[data-theme="dark"]', self.css)

    def test_palette(self):
        for color in ("#0F172A", "#F8F6F1", "#0F766E", "#B45309", "#15803D", "#0A0F1C"):
            self.assertIn(color, self.css)


if __name__ == "__main__":
    unittest.main()
