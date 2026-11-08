"""Logic fixes from the pre-submission audit (L1-L15) and the server-side wording (W)."""
import io
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import ai, deals, guard, ledger, pipeline, storage
from app.main import app
from tests.test_deals_api import letter_pdf, stub_reading

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


# ---------------------------------------------------------------------------
# L1, L3: signatures

class Signatures(unittest.TestCase):
    PAGE = "\n".join(["SIGNATURES", "CITY OF LANTERN BAY", "[signature on file]", "City Manager",
                      "BEACON POINT HOUSING LLC", "[signature on file]", "Managing Member",
                      "Attest:", "[signature on file]", "City Clerk",
                      "Approved as to form:", "[signature on file]", "City Attorney"])

    def sigs(self, parties, page=None):
        return [s["party"] for s in pipeline.checked_signatures([{"party": p, "page": 1} for p in parties], [page or self.PAGE])]

    def test_title_only_parties_are_dropped(self):
        self.assertEqual(self.sigs(["City of Lantern Bay", "Beacon Point Housing LLC", "City Clerk", "City Attorney"]),
                         ["City of Lantern Bay", "Beacon Point Housing LLC"])

    def test_window_stops_at_the_next_party(self):
        page = "\n".join(["CITY OF LANTERN BAY", "BEACON POINT HOUSING LLC", "[signature on file]"])
        self.assertEqual(self.sigs(["City of Lantern Bay", "Beacon Point Housing LLC"], page), ["Beacon Point Housing LLC"])

    def test_city_signed_needs_the_city_itself(self):
        packet = {"city": "Lantern Bay", "developer": "Harbor Walk Partners",
                  "documents": [{"signed": True, "signed_by": ["Harbor Walk Partners", "City Manager"]}]}
        summary = ledger.build_summary([], [], [], packet)
        self.assertFalse(summary["city_signed"])
        packet["documents"][0]["signed_by"].append("City of Lantern Bay")
        self.assertTrue(ledger.build_summary([], [], [], packet)["city_signed"])

    def test_only_completed_signatures_count(self):
        for line, signed in [("/s/ Jane Roe", True), ("[signature on file]", True), ("[Signed]", True),
                             ("Digitally signed by Jane Roe", True), ("Signature:", False), ("Signature: ________", False),
                             ("By: Jane Roe", False), ("This Agreement may be executed in counterparts.", False),
                             ("[unsigned draft]", False), ("/s/", False)]:
            with self.subTest(line=line):
                page = f"Harbor Walk Partners\n{line}\nManaging Member"
                self.assertEqual(bool(self.sigs(["Harbor Walk Partners"], page)), signed)


# ---------------------------------------------------------------------------
# L4, L5: delivered and supported

class Stages(unittest.TestCase):
    def test_type_comes_from_the_label_words(self):
        self.assertEqual(pipeline.type_key("Certified copy of the regulatory agreement"), "agreement")
        self.assertEqual(pipeline.type_key("Annual compliance report"), "staff_report")
        self.assertEqual(pipeline.type_key("Occupancy terms"), "other")
        self.assertEqual(pipeline.type_key("Compliance certificate"), "certificate")

    def test_delivery_needs_explicit_wording(self):
        stage = lambda text, draft=False: pipeline.decide_stage("certificate", [text], [], draft)[0]
        self.assertEqual(stage("9 of the 9 Affordable Homes were leased to income-qualified households."), "delivered")
        self.assertEqual(stage("The Owner certifies that the information is true."), "delivered")
        self.assertEqual(stage("This certificate concerns compliance with Section 4."), "proposed")
        self.assertEqual(stage("Homes were leased.", draft=True), "proposed")

    def test_no_staff_type_and_no_named_type_caps_at_proposed(self):
        pages = ["The homes were leased to households at 60 percent of AMI."]
        self.assertEqual(pipeline.record_kind(None, "certificate", pages), ("other", False))
        self.assertEqual(pipeline.record_kind(None, "certificate", ["COMPLIANCE CERTIFICATE\n" + pages[0]]),
                         ("certificate", False))
        self.assertEqual(pipeline.record_kind("Staff memo", "certificate", pages), ("staff_report", True))

    def test_support_needs_an_action_that_passed(self):
        acted = lambda text: bool(pipeline.support_actions(text))
        self.assertTrue(acted("The Council voted 5 to 2 to support the tax request."))
        self.assertTrue(acted("PASSED AND ADOPTED by the City Council on May 13, 2025."))
        self.assertTrue(acted("The motion carried."))
        for text in ("The motion failed 2-5.", "The Council voted 2 to 5 to approve the request.",
                     "The item was continued to the next meeting.", "Approval of the minutes of March 1.",
                     "The agenda was approved as posted.", "Approved by the Council on April 8, 2025.",
                     "The motion to approve was tabled."):
            with self.subTest(text=text):
                self.assertFalse(acted(text))

    def test_minutes_claim_needs_the_action_nearby(self):
        filler = "Other business was discussed. " * 100
        pages = ["Item 4. The Council voted 5 to 2 to support the tax request.\n" + filler +
                 "Item 9. Members stated their understanding that 20 homes would be affordable."]
        self.assertEqual(pipeline.claim_stage("supported", "minutes", "The Council voted 5 to 2 to support the tax request.", pages), "supported")
        self.assertEqual(pipeline.claim_stage("supported", "minutes", "Members stated their understanding that 20 homes would be affordable.", pages), "proposed")

    def test_negated_recommendation_is_not_support(self):
        self.assertEqual(pipeline.claim_stage("proposed", "staff_report", "Staff recommends approval of the request."), "supported")
        self.assertEqual(pipeline.claim_stage("proposed", "staff_report", "Staff does not recommend approval."), "proposed")
        self.assertEqual(pipeline.claim_stage("proposed", "staff_report", "Staff recommends denial of the request."), "proposed")


# ---------------------------------------------------------------------------
# L6-L8: numbers

class Numbers(unittest.TestCase):
    def test_units_need_a_homes_word(self):
        self.assertEqual(pipeline.numbers("units", "Section 4 of the 2024 agreement applies to 12 affordable homes."),
                         {"homes": {"count": 12}})
        self.assertEqual(pipeline.numbers("units", "We are considering 10% of the 120 homes."),
                         {"math": {"percent": 10, "of": 120, "equals": 12}})
        self.assertEqual(pipeline.numbers("units", "16 of the 80 new homes are reserved."), {"homes": {"count": 16, "of": 80}})

    def test_number_words_are_compared(self):
        self.assertEqual(pipeline.compare_key("units", "Twelve affordable homes will be provided."),
                         pipeline.compare_key("units", "12 affordable homes will be provided."))
        self.assertEqual(pipeline.compare_key("term", "The restrictions last thirty years."), "30 years")
        self.assertEqual(pipeline.numeric("twenty-five years"), "25 years")

    def test_the_number_next_to_the_term_words(self):
        self.assertEqual(pipeline.term_years("Within 2 years of completion, the homes shall remain affordable for 55 years."), 55)
        self.assertEqual(pipeline.compare_key("income_basis", "Homes at 80% of AMI, averaging 60% across the project."), "80 percent")
        self.assertEqual(pipeline.compare_key("rent_limits", "Rent shall not exceed 30 percent of 50 percent of AMI."), "30 of 50 percent")

    def test_quotes_keep_their_words(self):
        reading = ai.PdfReading(document_type="letter", title="", date="", draft=False, signatures=[], candidates=[
            ai.PdfCandidate(topic="units", quote="Twelve affordable homes will be provided.", page=1, wording="will", value="12")])
        claim = pipeline.verify_reading(reading, ["Twelve affordable homes will be provided."], {"id": "d", "type": "Letter"})["claims"][0]
        self.assertEqual(claim["quote"], "Twelve affordable homes will be provided.")
        self.assertEqual(claim["compare"], "12 homes")


# ---------------------------------------------------------------------------
# L9, L13: questions

class Questions(unittest.TestCase):
    def test_scanned_question_only_when_read_and_pluralized(self):
        deal = {"id": "x", "name": "X", "city": "Lantern Bay"}
        one = deals.build_deal_review(deal, [{"id": "d1", "status": "done", "title": "Memo", "scanned_pages": [2], "claims": []}])
        self.assertIn("Memo: page 2 has no text layer and was not read.", [q["text"] for q in one["questions"]][-1])
        two = deals.build_deal_review(deal, [{"id": "d1", "status": "done", "title": "Memo", "scanned_pages": [1, 3], "claims": []}])
        self.assertIn("pages 1 and 3 have no text layer and were not read", two["questions"][-1]["text"])
        failed = deals.build_deal_review(deal, [{"id": "d1", "status": "failed", "filename": "scan.pdf", "error": "No text.",
                                                 "scanned_pages": [1, 2], "claims": []}])
        self.assertEqual([q["key"] for q in failed["questions"] if q["key"].endswith("d1")], ["failed-d1"])


# ---------------------------------------------------------------------------
# L10-L12: refresh, duplicates, stuck documents

class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = storage.LocalStorage(Path(self.tmp.name) / "runtime")
        storage.set_store(self.store)
        self.addCleanup(storage.set_store, None)
        for patcher in (mock.patch.object(pipeline, "READINGS_DIR", Path(self.tmp.name) / "readings"),
                        mock.patch.object(deals, "run_inline", True),
                        mock.patch.object(ai, "read_document", side_effect=stub_reading)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def deal(self):
        return self.client.post("/api/deals", json={"name": "D", "city": "Lantern Bay"}).json()["id"]

    def test_same_file_twice_is_one_document(self):
        deal_id = self.deal()
        data = letter_pdf()  # One file: reportlab stamps a creation time, so each render has different bytes.
        for _ in range(2):
            self.client.post(f"/api/deals/{deal_id}/documents", files={"file": ("a.pdf", data, "application/pdf")})
        review = self.client.get(f"/api/deals/{deal_id}/review").json()
        self.assertEqual(len(review["documents"]), 1)
        self.assertEqual(len({c["quote"] for c in review["claims"]}), len(review["claims"]))

    def test_retry_a_failed_document(self):
        deal_id = self.deal()
        with mock.patch.object(ai, "read_document", return_value=ai.ReadResult(mode="failed", notice="Busy.")):
            doc = self.client.post(f"/api/deals/{deal_id}/documents", files={"file": ("a.pdf", letter_pdf(), "application/pdf")}).json()
        self.assertEqual(self.client.get(f"/api/deals/{deal_id}/documents/{doc['id']}").json()["status"], "failed")
        r = self.client.post(f"/api/deals/{deal_id}/documents/{doc['id']}/retry")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(self.client.get(f"/api/deals/{deal_id}/documents/{doc['id']}").json()["status"], "done")
        self.assertEqual(self.client.post(f"/api/deals/{deal_id}/documents/{doc['id']}/retry").status_code, 409)
        self.assertEqual(self.client.post(f"/api/deals/{deal_id}/documents/nope/retry").status_code, 404)

    def test_resume_only_stale_documents(self):
        deal_id = self.deal()
        fresh = {"id": "d1", "status": "reading", "updated_at": deals.now(), "claims": []}
        old = {"id": "d2", "status": "reading", "claims": [],
               "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")}
        self.store.put_document(deal_id, fresh)
        self.store.put_document(deal_id, old)
        with mock.patch.object(deals, "submit") as submitted:
            self.assertEqual(deals.resume_pending(self.store), 1)
        submitted.assert_called_once_with(deal_id, "d2", self.store)

    def test_a_failing_store_in_the_error_path_does_not_raise(self):
        deal_id = self.deal()
        self.store.put_document(deal_id, {"id": "d1", "status": "queued", "claims": []})
        with mock.patch.object(deals, "page_texts", side_effect=RuntimeError("boom")), \
                mock.patch.object(self.store, "put_document", side_effect=RuntimeError("store down")):
            self.assertIsNone(deals.process_document(deal_id, "d1", self.store))


@unittest.skipUnless((SAMPLES / "harbor-walk" / "manifest.json").exists(), "sample deals not present")
class SampleRefresh(unittest.TestCase):
    def test_refresh_keeps_ids_and_decisions(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deals, "run_inline", True), \
                mock.patch.object(ai, "read_document", side_effect=AssertionError("no model")):
            store = storage.LocalStorage(Path(tmp))
            deals.refresh_samples(store)
            claims = [c["id"] for c in deals.deal_review("harbor-walk", store)["claims"]]
            store.put_decision("harbor-walk", {"id": "e1", "target_type": "claim", "target_id": claims[0],
                                               "decision": "confirmed", "label": "Confirmed", "note": "",
                                               "reviewer_name": "Sam", "reviewer_id": "x", "session": "s" * 20,
                                               "at": deals.now()})
            with mock.patch.object(store, "delete_deal", side_effect=AssertionError("never deleted")), \
                    mock.patch.object(deals, "sample_version", return_value="new-version"):
                self.assertEqual(len(deals.refresh_samples(store)), 3)
            review = deals.deal_review("harbor-walk", store, session="s" * 20)
            self.assertEqual([c["id"] for c in review["claims"]], claims)
            self.assertEqual(review["decisions"]["progress"]["claims_reviewed"], 1)


# ---------------------------------------------------------------------------
# L2, L14, L15: reminders

class Reminders(unittest.TestCase):
    def doc(self, quote, kind="agreement", date_="2024-01-10", **extra):
        return {"id": extra.pop("id", "d1"), "status": "done", "stage": "signed" if kind == "agreement" else "delivered",
                "type_key": kind, "date": date_,
                "claims": [{"id": "c1", "topic": "reporting", "quote": quote, "document": extra.get("doc", "d1"),
                            "document_type": "Agreement", "date": date_, "value": "", "page": 1,
                            "status": "signed" if kind == "agreement" else "delivered"}], **extra}

    def test_days_count_from_as_of(self):
        deal = {"id": "x", "name": "X", "city": "C", "as_of": "2026-04-15"}
        rows = deals.deal_reminders(deal, [self.doc("The Owner shall file a certificate by March 31 of each year.")])
        due = {r["due"]: r["days"] for r in rows}
        self.assertEqual(due["2026-03-31"], -15)  # Past: negative.
        self.assertEqual(due["2027-03-31"], 350)   # Ahead: positive.
        self.assertTrue(all(r["as_of"] == "2026-04-15" for r in rows))
        self.assertIn("Mar 31, 2026", next(r["text"] for r in rows if r["due"] == "2026-03-31"))

    def test_impossible_due_day_is_clamped(self):
        deal = {"id": "x", "name": "X", "city": "C", "as_of": "2026-06-01"}
        rows = deals.deal_reminders(deal, [self.doc("The Owner shall file a certificate by April 31 of each year.")])
        self.assertIn("2026-04-30", {r["due"] for r in rows})

    def test_certificate_counts_for_its_reporting_year(self):
        deal = {"id": "x", "name": "X", "city": "C", "as_of": "2026-04-15"}
        agreement = self.doc("The Owner shall file a certificate by March 31 of each year.", date_="2023-01-10")
        # Dated in 2026 but for reporting year 2024: it meets the 2025 due date, so 2026's is still missing.
        cert = {"id": "d2", "status": "done", "stage": "delivered", "type_key": "certificate", "date": "2026-01-05",
                "title": "Compliance certificate",
                "claims": [{"id": "c9", "topic": "reporting", "quote": "This certificate is for reporting year 2024.",
                            "document": "d2", "document_type": "Certificate", "date": "2026-01-05", "value": ""}]}
        rows = deals.deal_reminders(deal, [agreement, cert])
        missing = {r["due"] for r in rows if r["kind"] == "missing_record"}
        self.assertIn("2026-03-31", missing)
        self.assertNotIn("2025-03-31", missing)

    def test_list_deals_carries_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = storage.LocalStorage(Path(tmp))
            deals.create_deal("X", "C", deal_id="x", store=store, as_of="2026-04-15")
            store.put_document("x", self.doc("The Owner shall file a certificate by March 31 of each year."))
            nxt = deals.list_deals(store)[0]["next_reminder"]
            self.assertEqual(nxt["days"], (date.fromisoformat(nxt["due"]) - date(2026, 4, 15)).days)
            self.assertLess(nxt["days"], 0)  # Overdue reminders come first, with a negative count.


# ---------------------------------------------------------------------------
# Wording (W1, W3, W5, W6, W9, W13, W18, W20)

class Wording(unittest.TestCase):
    def test_term_labels(self):
        self.assertEqual((ledger.TOPICS["units"], ledger.TOPICS["income_basis"]), ("Homes", "Income limit"))

    def test_export_columns_and_values(self):
        self.assertIn("Quote found on page", deals.CLAIM_COLUMNS)
        self.assertNotIn("Verified", deals.CLAIM_COLUMNS)
        self.assertIn("Furthest stage (any term)", deals.TERM_COLUMNS)
        review = {"documents": [], "terms": [], "decisions": {"latest": {}},
                  "claims": [{"id": "c1", "topic": "units", "quote": "q", "document": "d", "document_type": "Letter",
                              "date": "2025-01-01", "page": 1, "status": "signed", "quote_checked": True},
                             {"id": "c2", "topic": "units", "quote": "q", "document": "d", "document_type": "Letter",
                              "date": "2025-01-01", "page": 1, "status": "signed", "quote_checked": False}]}
        col = deals.CLAIM_COLUMNS.index("Quote found on page")
        self.assertEqual([r[col] for r in deals.claim_rows(review)], ["Found", "Flagged for human review"])

    def test_notice_notes_and_question_wording(self):
        deal = {"id": "x", "name": "X", "city": "Lantern Bay"}
        review = deals.build_deal_review(deal, [])
        self.assertEqual(review["notice"], "Code checked each quote against its cited page. People make every decision.")
        claims = [{"id": "c1", "topic": "reporting", "status": "delivered", "quote": "q", "date": "2025-01-01"}]
        notes = deals._stage_notes(claims, [])
        self.assertEqual(notes["delivered"], "Certificate or occupancy record located (as stated in the record).")
        terms = [{"key": "units", "label": "Homes", "located": True, "signed_claim_id": None, "wording_differs": True,
                  "claim_ids": ["a", "b"]}]
        by_id = [{"id": "a", "value": "12 homes"}, {"id": "b", "value": "10 percent"}]
        texts = [q["text"] for q in ledger.build_questions(by_id, terms, [], {"signers": [], "city_signed": False})]
        self.assertIn("Homes: not located in a signed record. Ask staff whether an agreement covers homes.", texts)
        self.assertTrue(any(t.endswith("Ask staff which wording, if any, is in a signed agreement.") for t in texts))
        missing = [{"key": "rent_limits", "label": "Rent limits", "located": False, "signed_claim_id": None,
                    "wording_differs": False, "claim_ids": []}]
        texts = [q["text"] for q in ledger.build_questions([], missing, [], {"signers": [], "city_signed": False})]
        self.assertIn("Rent limits: not located. Ask staff whether an agreement covers rent limits.", texts)
        self.assertFalse(any("agreement section" in t for t in texts))

    def test_display_dates(self):
        self.assertEqual(deals.display_date("2026-11-08"), "Nov 8, 2026")
        self.assertEqual(deals.display_date(date(2025, 3, 1)), "Mar 1, 2025")
        about = deals.export_about({"project": "P", "city": "C", "notice": "N",
                                    "decisions": {"stamp": {"text": "Review complete · all confirmed",
                                                            "reviewer": "Sam", "date": "2026-11-08"}}},
                                   "2026-11-08T01:02:03+00:00")
        flat = [row[0] for row in about]
        self.assertIn("Exported Nov 8, 2026", flat)
        self.assertIn("Review complete · all confirmed (last decision Nov 8, 2026 by Sam)", flat)
        self.assertIn("A review records people's decisions. It is not a legal finding.", flat)


if __name__ == "__main__":
    unittest.main()
