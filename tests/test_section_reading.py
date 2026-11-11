"""Reading a long record a few pages at a time, and retrying a cut-off answer. The model is stubbed."""
import os
import unittest
from unittest import mock

from pydantic import ValidationError

from app import ai, pipeline


def part(pages, kind="agreement", title="", date="", draft=False, signer=None):
    return ai.PdfReading(document_type=kind, title=title, date=date, draft=draft,
                         signatures=[ai.Signature(party=signer, quote="/s/ " + signer, page=pages[0])] if signer else [],
                         candidates=[ai.PdfCandidate(topic="units", quote=f"quote on page {n}", page=n, wording="", value="")
                                     for n in pages])


class Sections(unittest.TestCase):
    def test_short_records_are_one_section(self):
        self.assertEqual(ai.sections(0, 4), [])
        self.assertEqual(ai.sections(1, 4), [(1, 1)])
        self.assertEqual(ai.sections(4, 4), [(1, 4)])

    def test_long_records_are_split_evenly_and_cover_every_page_once(self):
        self.assertEqual(ai.sections(5, 4), [(1, 3), (4, 5)])
        self.assertEqual(ai.sections(21, 4), [(1, 4), (5, 8), (9, 12), (13, 15), (16, 18), (19, 21)])
        for count in range(1, 61):
            got = ai.sections(count, 4)
            self.assertEqual([n for first, last in got for n in range(first, last + 1)], list(range(1, count + 1)))
            self.assertTrue(all(last - first + 1 <= 4 for first, last in got))

    def test_page_tags_keep_the_files_page_numbers(self):
        record = ai.pages_to_record(["five", "six"], first=5)
        self.assertEqual(record, '<page n="5">\nfive\n</page>\n<page n="6">\nsix\n</page>')

    def test_merge_takes_the_first_sections_type_and_joins_the_rest(self):
        merged = ai.merge_readings([part([1, 2], kind="resolution", title="", date="2026-05-04"),
                                    part([5], kind="agreement", title="Exhibit 1", draft=True, signer="Acme Homes LLC")])
        self.assertEqual((merged.document_type, merged.title, merged.date, merged.draft),
                         ("resolution", "Exhibit 1", "2026-05-04", True))
        self.assertEqual([c.page for c in merged.candidates], [1, 2, 5])
        self.assertEqual([s.party for s in merged.signatures], ["Acme Homes LLC"])


class ReadDocument(unittest.TestCase):
    def setUp(self):
        ai._live_calls.clear()
        self.env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        ai._live_calls.clear()

    def test_each_section_is_read_and_the_results_are_joined(self):
        seen = []

        def call(record, model):
            seen.append(record)
            numbers = [int(n) for n in __import__("re").findall(r'<page n="(\d+)">', record)]
            return part(numbers, kind="agreement" if numbers[0] == 1 else "other"), 100, 10

        with mock.patch.object(ai, "_call_pdf_model", side_effect=call), mock.patch.object(ai, "PDF_SECTION_PAGES", 2):
            result = ai.read_document([f"text of page {n}" for n in range(1, 6)])
        self.assertEqual(result.mode, "live")
        self.assertEqual(len(seen), 3)  # 5 pages, 2 at a time: 2 + 2 + 1
        self.assertIn('<page n="5">', seen[2])
        self.assertNotIn('<page n="1">', seen[1])
        self.assertEqual([c.page for c in result.reading.candidates], [1, 2, 3, 4, 5])
        self.assertEqual(result.reading.document_type, "agreement")
        self.assertEqual((result.tokens_in, result.tokens_out), (300, 30))

    def test_a_short_record_is_still_one_call(self):
        with mock.patch.object(ai, "_call_pdf_model", return_value=(part([1]), 10, 5)) as call:
            result = ai.read_document(["one", "two", "three"])
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result.mode, "live")

    def test_a_failed_section_fails_the_document(self):
        answers = [(part([1]), 10, 5), RuntimeError("boom")]
        with mock.patch.object(ai, "_call_pdf_model", side_effect=answers), mock.patch.object(ai, "PDF_SECTION_PAGES", 1):
            result = ai.read_document(["one", "two"])
        self.assertEqual(result.mode, "failed")  # A partial reading would look complete.
        self.assertIsNone(result.reading)

    def test_a_busy_section_is_tried_once_more(self):
        class Busy(Exception):
            code = 503

        answers = [Busy(), Busy(), (part([1]), 10, 5)]  # main model, fallback, then the main model again
        with mock.patch.object(ai, "_call_pdf_model", side_effect=answers) as call, \
                mock.patch.object(ai, "FALLBACK_MODEL", "fallback-model"), mock.patch.object(ai, "SECTION_RETRY_SECONDS", 0):
            result = ai.read_document(["one"])
        self.assertEqual((result.mode, call.call_count), ("live", 3))
        with mock.patch.object(ai, "_call_pdf_model", side_effect=[Busy()] * 4) as call, \
                mock.patch.object(ai, "FALLBACK_MODEL", "fallback-model"), mock.patch.object(ai, "SECTION_RETRY_SECONDS", 0):
            result = ai.read_document(["one"])
        self.assertEqual((result.mode, call.call_count), ("failed", 4))

    def test_a_cut_off_answer_is_retried_on_the_fallback_model(self):
        def cut_off():
            try:
                ai.PdfReading.model_validate_json('{"document_type": "agreement", "title": "T", "candi')
            except ValidationError as err:
                return err

        calls = []

        def call(record, model):
            calls.append(model)
            if model == ai.MODEL:
                raise cut_off()
            return part([1]), 10, 5

        with mock.patch.object(ai, "_call_pdf_model", side_effect=call), mock.patch.object(ai, "FALLBACK_MODEL", "fallback-model"):
            result = ai.read_document(["one"])
        self.assertEqual(calls, [ai.MODEL, "fallback-model"])
        self.assertEqual((result.mode, result.model), ("live", "fallback-model"))

    def test_the_whole_record_stays_under_the_character_cap(self):
        seen = []

        def call(record, model):
            seen.append(record)
            return part([1]), 10, 5

        with mock.patch.object(ai, "_call_pdf_model", side_effect=call), mock.patch.object(ai, "PDF_SECTION_PAGES", 1), \
                mock.patch.object(ai, "MAX_RECORD_CHARS", 2500):
            ai.read_document(["x" * 1000] * 6)
        self.assertLessEqual(sum(len(r) for r in seen), 2500)
        self.assertLess(len(seen), 6)

    def test_sections_change_nothing_about_who_decides(self):
        # A later section may call itself an agreement and name a signer. Code still finds no signature on the page.
        pages = ["STAFF REPORT\nThe owner would reserve 20 of the 100 homes as affordable homes.", "Attachment: draft terms."]
        merged = ai.merge_readings([
            ai.PdfReading(document_type="staff_report", title="", date="", draft=False, signatures=[], candidates=[
                ai.PdfCandidate(topic="units", quote="The owner would reserve 20 of the 100 homes as affordable homes.",
                                page=1, wording="", value="")]),
            part([2], kind="agreement", signer="Acme Homes LLC")])
        out = pipeline.verify_reading(merged, pages, {"id": "d"})
        self.assertEqual((out["stage"], out["signed_by"]), ("proposed", []))
        self.assertEqual([c["status"] for c in out["claims"]], ["proposed"])


if __name__ == "__main__":
    unittest.main()
