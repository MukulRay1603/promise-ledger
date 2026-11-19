"""Real county deals (data/county), secured PDFs, and the reminders calendar."""
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from app import deals, pipeline, storage

ROOT = Path(__file__).resolve().parent.parent
COUNTY = ROOT / "data" / "county"


def _pdf(text: str = "The Owner shall rent 12 units to households at or below 60 percent of area median income.",
         password: str | None = None, owner: str = "owner-secret") -> bytes:
    from pypdf import PdfWriter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    writer = PdfWriter(clone_from=io.BytesIO(buf.getvalue()))
    if password is not None:
        writer.encrypt(user_password=password, owner_password=owner, algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class SecuredPdfs(unittest.TestCase):
    def test_a_secured_pdf_that_opens_without_a_password_is_read(self):
        pages = pipeline._read_pages(_pdf(password=""))
        self.assertIn("60 percent", pages[0])

    def test_a_pdf_that_needs_a_password_is_refused(self):
        with self.assertRaises(pipeline.PdfError) as ctx:
            pipeline._read_pages(_pdf(password="open-sesame"))
        self.assertIn("password", str(ctx.exception))


class CountyManifests(unittest.TestCase):
    """The committed manifests are real records with provenance; the importer's rules hold for every one."""

    def setUp(self):
        self.manifests = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(COUNTY.glob("*/manifest.json"))]
        if not self.manifests:
            self.skipTest("no county manifests")

    def test_every_record_has_an_official_source_and_a_hash(self):
        for m in self.manifests:
            self.assertTrue(m["real"])
            self.assertTrue(m["source"]["url"].startswith("https://princegeorgescountymd.legistar.com/"))
            self.assertRegex(m["source"]["file"], r"^C[RB]-\d{2,3}-\d{4}$")
            for d in m["documents"]:
                self.assertRegex(d["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(d["url"].startswith("https://princegeorgescountymd.legistar1.com/"))
                self.assertTrue(d["file"].endswith(".pdf"))

    def test_converted_word_records_are_committed_and_match_their_hash(self):
        for m in self.manifests:
            folder = COUNTY / m["slug"]
            for d in m["documents"]:
                if d.get("converted_from"):
                    data = (folder / d["file"]).read_bytes()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), d["sha256"], d["file"])
                    self.assertIn(d["converted_from"]["format"], ("doc", "docx"))

    def test_the_notice_says_records_are_listed_not_judged(self):
        for m in self.manifests:
            self.assertIn("does not judge", m["notice"])


class CountySeeding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = storage.LocalStorage(self.root / "store")
        self.pdf = _pdf()
        self.sha = hashlib.sha256(self.pdf).hexdigest()
        folder = self.root / "county" / "test-deal-cr-001-2026"
        folder.mkdir(parents=True)
        self.manifest = folder / "manifest.json"
        self.manifest.write_text(json.dumps({
            "real": True, "deal": "Test Deal", "slug": "test-deal-cr-001-2026", "city": "Prince George's County",
            "county": "Prince George's County, MD", "as_of": "2020-01-01",
            "source": {"file": "CR-001-2026", "url": "https://princegeorgescountymd.legistar.com/x"},
            "documents": [{"file": "01-pilot-agreement.pdf", "id": "r01", "type": "PILOT agreement", "date": "2026-01-05",
                           "title": "CR-001-2026 Attachment B", "url": "https://example.org/a.pdf", "sha256": self.sha}],
        }), encoding="utf-8")
        cache = mock.patch.object(deals, "COUNTY_CACHE_DIR", self.root / "cache")
        cache.start()
        self.addCleanup(cache.stop)

    def _fake_download(self, payload: bytes):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return mock.patch("urllib.request.urlopen", return_value=Resp(payload))

    def test_a_record_is_downloaded_checked_and_stored_without_a_live_read(self):
        with self._fake_download(self.pdf), mock.patch.object(deals, "submit") as submit:
            deal_id = deals.seed_sample(self.manifest, self.store)
        deal = self.store.get_deal(deal_id)
        self.assertTrue(deal["real"])
        self.assertNotIn("as_of", deal)  # Real reminders count from today.
        self.assertEqual(deal["source"]["file"], "CR-001-2026")
        docs = self.store.list_documents(deal_id)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source_url"], "https://example.org/a.pdf")
        submit.assert_not_called()  # Seeding never spends on a live read of a real record.
        # A record with no saved reading is marked, not queued, so a restart never reads it live either.
        self.assertEqual(docs[0]["status"], "failed")
        self.assertIn("Not read yet", docs[0]["error"])
        with mock.patch.object(deals, "submit") as submit:
            self.assertEqual(deals.resume_pending(self.store), 0)
        submit.assert_not_called()

    def test_a_file_that_no_longer_matches_its_hash_is_not_used(self):
        with self._fake_download(_pdf("A different file.")):
            deal_id = deals.seed_sample(self.manifest, self.store)
        self.assertEqual(self.store.list_documents(deal_id), [])

    def test_county_deals_are_left_out_when_turned_off(self):
        with mock.patch.dict("os.environ", {"COUNTY_DEALS": "0"}), \
                mock.patch.object(deals, "refresh_samples", return_value=[]) as refresh:
            deals.seed(self.store)
        self.assertEqual(refresh.call_count, 1)  # Samples only.


class CalendarExport(unittest.TestCase):
    def test_term_end_gets_heads_up_events_and_valid_ics(self):
        rows = [{"deal_id": "holly-place", "deal_name": "Holly Place", "city": "", "kind": "term_end",
                 "date": "2066-07-07", "text": "Affordability term ends July 7, 2066, 40 years from the PILOT agreement.",
                 "claim_id": "c1"}]
        ics = deals.reminders_ics(rows, "https://example.org")
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n"))
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1 + len(deals.TERM_WARNING_YEARS))
        for years in deals.TERM_WARNING_YEARS:
            self.assertIn(f"DTSTART;VALUE=DATE:{2066 - years}0707", ics)
        self.assertIn("URL:https://example.org/#/deals/holly-place", ics)
        self.assertIn("\\,", ics)  # Commas in text are escaped.
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")))

    def test_a_february_29_end_still_gets_its_warnings(self):
        rows = [{"deal_id": "d", "deal_name": "D", "city": "", "kind": "term_end", "date": "2032-02-29",
                 "text": "Affordability term ends.", "claim_id": None}]
        self.assertIn("DTSTART;VALUE=DATE:20270228", deals.reminders_ics(rows))

    def test_the_calendar_route(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        res = client.get("/api/reminders.ics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/calendar", res.headers["content-type"])
        self.assertEqual(client.get("/api/reminders.ics?deal=../x").status_code, 404)


if __name__ == "__main__":
    unittest.main()


class AffordableCount(unittest.TestCase):
    """Real county sentences hold several counts; only the one stated as affordable is taken."""

    def count(self, quote):
        return deals.affordable_homes([{"topic": "units", "quote": quote, "id": "c"}])[0]

    def test_counts_next_to_affordable_words(self):
        self.assertEqual(self.count("Unit Mix - 145 Affordable Units"), 145)
        self.assertEqual(self.count("this project includes 175 affordable housing units at 60% or less than AMI."), 175)
        self.assertEqual(self.count("rehabilitate a thirty six (36) unit affordable rental community for seniors"), 36)
        self.assertEqual(self.count("Of the two hundred forty five (245) units, twenty six (26) units will be set-aside "
                                    "for families earning no more than fifty percent (50%) AMI"), 26)

    def test_market_rate_and_accessibility_counts_are_not_taken(self):
        self.assertEqual(self.count("Of the one hundred fifty eight (158) residential units, one hundred twenty eight "
                                    "(128) units will be income-restricted, and thirty (30) units will be market-rate."), 128)
        self.assertIsNone(self.count("Of the three hundred four (304) units, sixteen (16) units will be designated for "
                                     "residents with mobility impairments"))


class SavedScansWithoutKey(unittest.TestCase):
    """A scan transcribed once (with a key) is used later without one; nothing is sent to read it."""

    def test_a_saved_transcription_fills_scanned_pages_without_a_key(self):
        from app import vision

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline, "READINGS_DIR", Path(tmp)), \
                mock.patch.object(pipeline, "READINGS_WRITE_DIR", None), \
                mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "SCANS_TO_MODEL": "1"}):
            vision._save("ab" * 32, [1], vision.ScanResult(mode="live", pages={1: "The Owner shall rent 12 units."}))
            doc = {"sha256": "ab" * 32, "scanned_pages": [1]}
            filled, result = vision.fill_scanned(doc, [""], load_pdf=lambda: b"%PDF-1.4 stub")
            self.assertEqual(result.mode, "cache")
            self.assertIn("12 units", filled[0])
            loaded = []
            _, none = vision.fill_scanned({"sha256": "cd" * 32, "scanned_pages": [1]}, [""], load_pdf=lambda: loaded.append(1))
            self.assertEqual(none.mode, "off")
            self.assertEqual(loaded, [])  # No key and nothing saved: the PDF is not even loaded.
