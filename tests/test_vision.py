"""Scanned pages: transcribed by a stubbed model, then read by the normal claim pipeline."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import ai, deals, pipeline, storage, vision

TYPED = "The owner will provide 12 affordable homes in the building."
SCANNED = "The affordability restrictions remain in effect for 30 years."
MADE_UP = "All 500 homes were delivered to the City last year."


def pdf(pages):
    """A PDF from a list of page texts. An empty string makes a page with a drawing and no text layer."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=letter)
    for text in pages:
        if text:
            c.drawString(72, 700, text)
        else:
            c.rect(72, 600, 200, 100)
        c.showPage()
    c.save()
    return out.getvalue()


def reader(pages):
    """A model reading that quotes the typed page, the scanned page, and one sentence that is nowhere."""
    candidates = [ai.PdfCandidate(topic="units", quote=TYPED, page=1, wording="will provide", value="12 homes"),
                  ai.PdfCandidate(topic="term", quote=SCANNED, page=2, wording="remain", value="30 years"),
                  ai.PdfCandidate(topic="units", quote=MADE_UP, page=2, wording="were", value="500 homes")]
    reading = ai.PdfReading(document_type="letter", title="", date="", draft=False, signatures=[], candidates=candidates)
    return ai.ReadResult(mode="live", model="stub", reading=reading)


def page_count(data):
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(data)).pages)


class Transcriber:
    """Stands in for the model: returns `texts` for the pages of the PDF it is handed, and records the calls."""

    def __init__(self, texts):
        self.texts, self.sizes = texts, []

    def __call__(self, data):
        self.sizes.append(page_count(data))
        return vision.Transcription(pages=[vision.PageText(page=i, text=t) for i, t in enumerate(self.texts, 1)])


class ScannedPages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = storage.LocalStorage(Path(self.tmp.name) / "runtime")
        storage.set_store(self.store)
        self.addCleanup(storage.set_store, None)
        for target, name, value in ((pipeline, "READINGS_DIR", Path(self.tmp.name) / "readings"),
                                    (pipeline, "READINGS_WRITE_DIR", None), (deals, "run_inline", True)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("GEMINI_API_KEY", None)
        self.deal = deals.create_deal("Harbor Walk", "Lantern Bay", store=self.store)

    def add(self, pages):
        return deals.add_document(self.deal["id"], "scan.pdf", pdf(pages), type_="Letter", store=self.store, process=False)

    def process(self, doc, transcriber=None, read=reader):
        return deals.process_document(self.deal["id"], doc["id"], self.store, reader=read, transcriber=transcriber)

    def questions(self):
        review = deals.deal_review(self.deal["id"], store=self.store)
        return {q["key"]: q["text"] for q in review["questions"]}

    def test_scanned_page_is_transcribed_and_its_claims_are_marked(self):
        doc = self.add([TYPED, ""])
        self.assertEqual(doc["scanned_pages"], [2])
        stub = Transcriber([SCANNED])
        done = self.process(doc, stub)
        self.assertEqual(stub.sizes, [1])  # Only the scanned page was sent.
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["transcribed_pages"], [2])
        self.assertEqual(deals.page_texts(self.deal["id"], doc["id"], self.store)[1], SCANNED)
        by_page = {c["page"]: c for c in done["claims"]}
        self.assertEqual(sorted(by_page), [1, 2])
        self.assertTrue(by_page[2]["from_scan"])
        self.assertTrue(by_page[2]["verified"])
        self.assertNotIn("from_scan", by_page[1])
        # The quote that is not in the transcribed text is dropped, as on any page.
        self.assertEqual(done["counts"]["dropped"], 1)
        self.assertEqual(deals.public_doc(done)["transcribed_pages"], [2])
        questions = self.questions()
        self.assertEqual(questions[f"transcribed-{doc['id']}"],
                         "scan.pdf: page 2 was a scanned image; its text was transcribed by AI. "
                         "Check quotes from it against the PDF.")
        self.assertNotIn(f"scanned-{doc['id']}", questions)
        claims = deals.deal_review(self.deal["id"], store=self.store)["claims"]
        self.assertEqual([c.get("from_scan", False) for c in sorted(claims, key=lambda c: c["page"])], [False, True])

    def test_no_key_is_unchanged(self):
        doc = self.add([TYPED, ""])
        with mock.patch.object(vision, "_call_vision_model", side_effect=AssertionError("no model call")), \
                mock.patch.object(vision, "subset_pdf", side_effect=AssertionError("no PDF work")):
            done = self.process(doc)
        self.assertEqual(done["status"], "done")
        self.assertNotIn("transcribed_pages", done)
        self.assertEqual([c["page"] for c in done["claims"]], [1])
        self.assertNotIn("from_scan", done["claims"][0])
        self.assertEqual(deals.page_texts(self.deal["id"], doc["id"], self.store)[1].strip(), "")
        self.assertEqual(self.questions()[f"scanned-{doc['id']}"],
                         "scan.pdf: page 2 has no text layer and was not read. Ask for a text copy or run OCR.")

    def test_all_scanned_with_no_key_still_fails_as_before(self):
        doc = self.add(["", ""])
        done = self.process(doc)
        self.assertEqual(done["status"], "failed")
        self.assertIn("No text layer was found", done["error"])

    def test_all_scanned_document_is_read_once_transcribed(self):
        doc = self.add(["", ""])
        done = self.process(doc, Transcriber([TYPED, SCANNED]))
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["transcribed_pages"], [1, 2])
        self.assertEqual([c["from_scan"] for c in done["claims"]], [True, True])
        self.assertIn("pages 1 and 2 were scanned images; their text was transcribed by AI. Check quotes from them "
                      "against the PDF.", self.questions()[f"transcribed-{doc['id']}"])

    def test_page_cap(self):
        doc = self.add([TYPED, "", "", "", ""])
        stub = Transcriber([SCANNED, "A second scanned page with enough words.", "never asked for", "never asked for"])
        with mock.patch.object(vision, "VISION_MAX_PAGES", 2):
            done = self.process(doc, stub)
        self.assertEqual(stub.sizes, [2])  # Two pages sent, not four.
        self.assertEqual(done["transcribed_pages"], [2, 3])
        questions = self.questions()
        self.assertIn("pages 2 and 3 were scanned images", questions[f"transcribed-{doc['id']}"])
        self.assertIn("pages 4 and 5 have no text layer and were not read", questions[f"scanned-{doc['id']}"])

    def test_failed_or_empty_transcription_keeps_the_old_question(self):
        def broken(data):
            raise RuntimeError("model down")
        doc = self.add([TYPED, "", ""])
        done = self.process(doc, broken)
        self.assertEqual(done["status"], "done")
        self.assertNotIn("transcribed_pages", done)
        self.assertIn("pages 2 and 3 have no text layer", self.questions()[f"scanned-{doc['id']}"])
        # A retry transcribes page 2 only: page 3 comes back with no words and stays unread.
        again = self.process(done, Transcriber([SCANNED, "  "]))
        self.assertEqual(again["transcribed_pages"], [2])
        questions = self.questions()
        self.assertIn("page 3 has no text layer and was not read", questions[f"scanned-{doc['id']}"])
        self.assertIn("page 2 was a scanned image", questions[f"transcribed-{doc['id']}"])

    def test_transcription_is_cached_by_file_hash_and_not_repeated(self):
        data = pdf([TYPED, ""])
        sha = pipeline.file_hash(data)
        stub = Transcriber([SCANNED])
        first = vision.transcribe(data, [2], sha, call=stub)
        second = vision.transcribe(data, [2], sha, call=stub)
        self.assertEqual((first.mode, second.mode), ("live", "cache"))
        self.assertEqual(second.pages, {2: SCANNED})
        self.assertEqual(len(stub.sizes), 1)
        # A document whose scanned page is already filled sends nothing on the next run.
        doc = self.add([TYPED, "", ""])
        self.process(doc, Transcriber([SCANNED, SCANNED + " Again."]))
        later = Transcriber([SCANNED])
        done = self.process(self.store.get_document(self.deal["id"], doc["id"]), later)
        self.assertEqual(later.sizes, [])
        self.assertEqual(done["transcribed_pages"], [2, 3])
        self.assertTrue(next(c for c in done["claims"] if c["page"] == 2)["from_scan"])

    def test_answers_for_pages_that_were_not_sent_are_ignored(self):
        data = pdf([TYPED, ""])

        def odd(_):
            return vision.Transcription(pages=[vision.PageText(page=7, text=SCANNED), vision.PageText(page=0, text=SCANNED),
                                               vision.PageText(page=1, text=SCANNED), vision.PageText(page=1, text=MADE_UP)])
        self.assertEqual(vision.transcribe(data, [2], call=odd).pages, {2: SCANNED})

    def test_handwritten_signature_does_not_sign(self):
        doc = self.add([TYPED, ""])
        scan = "LANTERN BAY HOMES LLC\n[handwritten signature]\n" + SCANNED

        def read(pages):
            result = reader(pages)
            result.reading.signatures = [ai.Signature(party="Lantern Bay Homes LLC", quote="[handwritten signature]", page=2)]
            return result
        done = self.process(doc, Transcriber([scan]), read)
        self.assertEqual(done["stage"], "proposed")
        self.assertEqual(done["signed_by"], [])

    def test_live_call_sends_the_pdf_and_uses_the_fallback_when_busy(self):
        class Busy(Exception):
            code = 503
        os.environ["GEMINI_API_KEY"] = "test-key"
        seen = []

        def call(data, model):
            seen.append((page_count(data), model))
            if model == ai.MODEL:
                raise Busy()
            return vision.Transcription(pages=[vision.PageText(page=1, text=SCANNED)]), 100, 50
        with mock.patch.object(vision, "_call_vision_model", side_effect=call), \
                mock.patch.object(ai, "FALLBACK_MODEL", "fallback-model"), mock.patch.object(ai, "_live_calls", ai.deque()):
            result = vision.transcribe(pdf([TYPED, ""]), [2])
        self.assertEqual(seen, [(1, ai.MODEL), (1, "fallback-model")])
        self.assertEqual((result.mode, result.model, result.pages), ("live", "fallback-model", {2: SCANNED}))
        self.assertGreater(result.cost_usd, 0)


if __name__ == "__main__":
    unittest.main()


class ScannedSignatures(unittest.TestCase):
    """Stage evidence counts only from pages with their own text layer."""
    PAGES = ["LETTER AGREEMENT\nThe owner will provide 12 affordable homes.",
             "HARBOR WALK PARTNERS\n/s/ Dana Reyes\nManaging Member"]

    def reading(self):
        from app import ai
        return ai.PdfReading(
            document_type="letter", title="Letter agreement", date="", draft=False,
            signatures=[ai.Signature(party="Harbor Walk Partners", quote="/s/ Dana Reyes", page=2)],
            candidates=[ai.PdfCandidate(topic="units", quote="The owner will provide 12 affordable homes.", page=1,
                                        wording="will provide", value="12 homes")])

    def test_typed_signature_signs(self):
        out = pipeline.verify_reading(self.reading(), self.PAGES, {"id": "d", "type": "Letter"})
        self.assertEqual(out["stage"], "signed")

    def test_signature_only_on_a_scanned_page_does_not_sign(self):
        out = pipeline.verify_reading(self.reading(), self.PAGES, {"id": "d", "type": "Letter", "transcribed_pages": [2]})
        self.assertEqual(out["stage"], "proposed")
        self.assertIn("must confirm it against the PDF", out["stage_reason"])
        self.assertTrue(all(c["status"] == "proposed" for c in out["claims"]))


class ScanRetries(unittest.TestCase):
    """A scan that comes back empty is not paid for again and again on retry (security review)."""
    def test_attempts_are_capped(self):
        calls = []

        def empty(data):
            calls.append(1)
            return vision.Transcription(pages=[])
        doc = {"scanned_pages": [1], "sha256": None}
        with mock.patch.object(vision, "subset_pdf", return_value=b"%PDF"):
            for _ in range(5):
                vision.fill_scanned(doc, [""], lambda: b"%PDF-stub", call=empty, use_cache=False)
        self.assertEqual(len(calls), vision.MAX_SCAN_ATTEMPTS)

    def test_pages_past_the_cap_are_never_sent(self):
        sent = []

        def record(data):
            sent.append(1)
            return vision.Transcription(pages=[])
        doc = {"scanned_pages": list(range(1, 13)), "sha256": None}
        with mock.patch.object(vision, "VISION_MAX_PAGES", 10), \
                mock.patch.object(vision, "subset_pdf", side_effect=lambda data, numbers: (sent.append(tuple(numbers)), b"%PDF")[1]):
            pages = [""] * 12
            vision.fill_scanned(doc, pages, lambda: b"%PDF-stub", call=record, use_cache=False)
        self.assertTrue(all(max(x) <= 10 for x in sent if isinstance(x, tuple)))
