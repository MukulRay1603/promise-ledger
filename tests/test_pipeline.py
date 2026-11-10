import unittest
from datetime import date

from app import ai, deals, ledger, pipeline

PAGES = [
    "MEMO\nThe developer has agreed to set aside 12 of the 120 homes\nas affordable homes.\n"
    "Staff recommends that the Council support the request.",
    "Staff understands that the income limits would last for 30 years.\nThese homes are “affordable” — for now.",
]


def reading(candidates=(), signatures=(), document_type="staff_report", draft=False, date_=""):
    return ai.PdfReading(document_type=document_type, title="T", date=date_, draft=draft,
                         signatures=[ai.Signature(**s) for s in signatures],
                         candidates=[ai.PdfCandidate(**c) for c in candidates])


def cand(quote, page=1, topic="units", wording="has agreed", value="v"):
    return {"topic": topic, "quote": quote, "page": page, "wording": wording, "value": value}


class QuoteChecks(unittest.TestCase):
    def test_line_breaks_and_quote_marks_are_normalized(self):
        self.assertTrue(pipeline.quote_on_page("set aside 12 of the 120 homes as affordable homes.", PAGES[0]))
        self.assertTrue(pipeline.quote_on_page('These homes are "affordable" - for now.', PAGES[1]))

    def test_changed_words_fail(self):
        self.assertFalse(pipeline.quote_on_page("set aside 13 of the 120 homes", PAGES[0]))

    def test_hyphenated_line_break(self):
        self.assertTrue(pipeline.quote_on_page("the affordable homes", "the afford-\nable homes"))

    def test_compound_word_broken_at_its_hyphen(self):
        page = "The County will restrict a number of units to income-\neligible households for 30 years."
        self.assertTrue(pipeline.quote_on_page("units to income-eligible households for 30 years.", page))
        self.assertFalse(pipeline.quote_on_page("units to income eligible households for 40 years.", page))

    def test_margin_line_numbers_do_not_break_a_quote(self):
        # Council bills number every line, so a sentence over two lines has a number inside it.
        lines = ["WHEREAS, the Development will provide 95 affordable rental units, 50 in Building 1",
                 "and 45 in Building 2, at three levels of affordability; and", "",
                 "WHEREAS, the Company has asked the County to accept payments in lieu of", "County real property taxes; and",
                 "", "NOW, THEREFORE, BE IT RESOLVED that the County shall abate the taxes."]
        quote = "the Development will provide 95 affordable rental units, 50 in Building 1 and 45 in Building 2"
        leading = "\n".join(f"{n} {line}".rstrip() for n, line in enumerate(lines, 1))
        trailing = "2\n" + "\n".join(f"{line} {n} " for n, line in enumerate(lines, 1))
        for page in (leading, trailing):
            self.assertTrue(pipeline.quote_on_page(quote, page))
            self.assertFalse(pipeline.quote_on_page(quote.replace("95", "96"), page))
        self.assertEqual(pipeline.locate(quote, ["Cover page.", leading], 1), 2)

    def test_numbers_that_are_not_line_numbers_stay(self):
        page = "The owner will reserve\n12 homes for 30 years.\nRents are limited.\nReports are due yearly.\n9 homes are leased."
        self.assertEqual(pipeline.strip_line_numbers(page), page)
        table = "\n".join(f"{n} homes in phase {n}" for n in (4, 8, 15, 16, 23, 42))
        self.assertEqual(pipeline.strip_line_numbers(table), table)
        self.assertFalse(pipeline.quote_on_page("The owner will reserve homes for 30 years.", page))

    def test_a_number_printed_twice_is_read_once(self):
        self.assertEqual(pipeline.term_years("The covenants last for a period of not fewer than forty (40) years."), 40)
        self.assertEqual(pipeline.compare_key("term", "The limits remain in effect for twenty (20) years."), "20 years")
        self.assertTrue(pipeline.term_fits("term", "The limits remain in effect for twenty (20) years."))
        self.assertEqual(pipeline.numbers("units", "Sixty-six (66) units will be rented as affordable units."),
                         {"homes": {"count": 66}})
        self.assertEqual(pipeline.numeric("Section 4 (2) applies for sixty (60) days"), "Section 4 (2) applies for 60 days")

    def test_home_count_with_two_describing_words(self):
        quote = "The development will provide 95 affordable rental units at multiple levels, 50 units in Building 1 and 45 in Building 2."
        self.assertEqual(pipeline.numbers("units", quote), {"homes": {"count": 95}})
        self.assertEqual(pipeline.compare_key("units", quote), "95 homes")
        tiers = ("The development is offering 95 affordable rental units, 32 units for households earning up to 20% "
                 "of the County's median income.")
        self.assertEqual(pipeline.compare_key("units", tiers), "95 homes")  # "up to 20%" is not a cap on homes.

    def test_locate_corrects_the_page(self):
        quote = "Staff understands that the income limits would last for 30 years."
        self.assertEqual(pipeline.locate(quote, PAGES, 2), 2)
        self.assertEqual(pipeline.locate(quote, PAGES, 1), 2)
        self.assertIsNone(pipeline.locate("All 500 homes were delivered.", PAGES, 1))

    def test_verify_keeps_corrects_and_drops(self):
        r = reading([
            cand("The developer has agreed to set aside 12 of the 120 homes as affordable homes.", page=2),
            cand("Staff understands that the income limits would last for 30 years.", page=2, topic="term",
                 wording="understands"),
            cand("All 500 homes were delivered.", page=1),
            cand("The developer has agreed to set aside 12 of the 120 homes as affordable homes.", page=1),
        ])
        out = pipeline.verify_reading(r, PAGES, {"id": "d1", "type": "Staff report", "date": "2025-02-03"})
        self.assertEqual(out["counts"], {"candidates": 4, "kept": 2, "page_corrected": 1, "dropped": 1, "duplicates": 1, "absent": 0, "boilerplate": 0, "off_term": 0})
        units, term = out["claims"]
        self.assertEqual((units["page"], units["stated_page"], units["page_corrected"]), (1, 2, True))
        self.assertEqual(units["homes"], {"count": 12, "of": 120})
        self.assertEqual(units["value"], "12 homes")
        self.assertEqual(term["value"], "30 years")
        self.assertTrue(all(c["status"] == "proposed" and c["verified"] for c in out["claims"]))

    def test_a_sentence_saying_a_term_is_missing_is_not_a_claim(self):
        pages = ["Rent levels for these homes were not described in the request. Rents would be set later."]
        r = reading([cand("Rent levels for these homes were not described in the request.", topic="rent_limits")])
        out = pipeline.verify_reading(r, pages, {"id": "d", "type": "Staff report"})
        self.assertEqual((out["claims"], out["counts"]["absent"]), ([], 1))

    def test_compare_keys_come_from_the_quote(self):
        key = pipeline.compare_key
        self.assertEqual(key("units", "The owner will reserve 16 of the 80 homes as affordable homes."), "16 homes")
        self.assertIsNone(key("units", "The owner proposes to build 80 homes on the lot."))
        self.assertEqual(key("units", "We are considering 10 percent of the 120 homes."), "10 percent of 120 homes")
        self.assertEqual(key("units", "We will explore setting aside up to 12 homes at reduced rents."), "up to 12 homes")
        self.assertEqual(key("units", "As of December 31, 2024, 9 of the 9 required Affordable Homes were leased."), None)  # A delivery count is not compared.
        self.assertEqual(key("term", "The period ends on December 31, 2026."), "ends december 31 2026")
        self.assertIsNone(key("term", "The City approves a payment in lieu of taxes for 15 years."))
        self.assertEqual(key("reporting", "The owner will file a certificate by March 1 of each year."), "due march 1")
        self.assertIsNone(key("responsible_party", "The owner is responsible."))

    def test_differs_uses_code_keys_not_model_phrasing(self):
        docs = []
        for i, (quote, value) in enumerate([("The owner will reserve 16 of the 80 homes as affordable homes.", "16 of 80"),
                                            ("16 of the 80 homes are reserved as affordable homes.", "sixteen homes"),
                                            ("The owner proposes to build 80 homes.", "80 homes")]):
            docs.append({"id": f"d{i}", "status": "done", "stage": "proposed", "date": f"2025-0{i + 1}-01",
                         "claims": [{"id": f"d{i}-1", "document": f"d{i}", "document_type": "Report", "topic": "units",
                                     "quote": quote, "value": value, "status": "proposed", "date": f"2025-0{i + 1}-01",
                                     "page": 1, "compare": pipeline.compare_key("units", quote)}]})
        review = deals.build_deal_review({"id": "x", "name": "B", "city": "Lantern Bay"}, docs)
        units = next(t for t in review["terms"] if t["key"] == "units")
        self.assertFalse(units["wording_differs"])

    def test_wording_not_in_quote_is_cleared(self):
        r = reading([cand("Staff understands that the income limits would last for 30 years.", page=2,
                          topic="term", wording="will provide")])
        out = pipeline.verify_reading(r, PAGES, {"id": "d1", "type": "Staff report"})
        self.assertEqual(out["claims"][0]["wording"], "")

    def test_percent_arithmetic_is_computed(self):
        self.assertEqual(pipeline.numbers("units", "We are considering 10 percent of the 120 homes."),
                         {"math": {"percent": 10, "of": 120, "equals": 12}})

    def test_model_date_must_be_printed(self):
        pages = ["Dated March 4, 2025. The owner will provide 12 homes."]
        good = pipeline.verify_reading(reading(date_="2025-03-04"), pages, {"id": "d", "type": "Letter"})
        bad = pipeline.verify_reading(reading(date_="2025-03-05"), pages, {"id": "d", "type": "Letter"})
        self.assertEqual(good["date"], "2025-03-04")
        self.assertEqual((bad["date"], bad["date_note"]), ("", "Date not located in the record."))


SIGNED_LETTER = ["Harbor Walk Partners will provide 12 affordable homes.\nSincerely,\nHARBOR WALK PARTNERS LLC\n"
                 "[signature on file]\nManaging Member"]
DRAFT_LETTER = ["DRAFT FOR DISCUSSION. NOT SIGNED.\nHarbor Walk Partners will explore 12 homes.\nSincerely,\n"
                "[unsigned draft]\nHarbor Walk Partners LLC"]
SIG = {"party": "HARBOR WALK PARTNERS LLC", "quote": "[signature on file]", "page": 1}


class StageRules(unittest.TestCase):
    def stage(self, type_, pages, model_type="other", signatures=(), draft=False, quote=None, topic="units"):
        quote = quote or pages[0].split("\n")[0 if "DRAFT" not in pages[0] else 1]
        r = reading([cand(quote, topic=topic)], signatures=signatures, document_type=model_type, draft=draft)
        return pipeline.verify_reading(r, pages, {"id": "d", "type": type_}, ["Harbor Walk Partners LLC"])

    def test_signed_letter_is_signed_and_names_the_signer(self):
        out = self.stage("Later letter", SIGNED_LETTER, signatures=[SIG])
        self.assertEqual((out["stage"], out["signed_by"]), ("signed", ["Harbor Walk Partners LLC"]))
        self.assertEqual(out["claims"][0]["status"], "signed")

    def test_letter_without_checked_signature_is_proposed(self):
        self.assertEqual(self.stage("Letter", SIGNED_LETTER)["stage"], "proposed")
        made_up = {"party": "City of Lantern Bay", "quote": "[signature on file]", "page": 1}
        self.assertEqual(self.stage("Letter", SIGNED_LETTER, signatures=[made_up])["stage"], "proposed")
        no_mark = ["Harbor Walk Partners will provide 12 affordable homes.\nSincerely,\nHARBOR WALK PARTNERS LLC\n"
                   "Managing Member\nBy: ____________"]
        self.assertEqual(self.stage("Letter", no_mark, signatures=[SIG])["stage"], "proposed")

    def test_signature_line_is_found_by_code_not_the_model_quote(self):
        title_only = {"party": "HARBOR WALK PARTNERS LLC", "quote": "Managing Member", "page": 3}
        out = self.stage("Letter", SIGNED_LETTER, signatures=[title_only])
        self.assertEqual(out["stage"], "signed")
        self.assertEqual(out["signatures"][0]["quote"], "[signature on file]")
        self.assertEqual(out["signatures"][0]["page"], 1)

    def test_draft_is_never_signed_even_if_the_model_says_so(self):
        sig = {"party": "Harbor Walk Partners LLC", "quote": "[unsigned draft]", "page": 1}
        out = self.stage("Draft letter", DRAFT_LETTER, model_type="agreement", signatures=[sig])
        self.assertEqual(out["stage"], "proposed")
        self.assertTrue(out["draft"])

    def test_model_type_cannot_upgrade_a_staff_report(self):
        out = self.stage("Staff report", SIGNED_LETTER, model_type="agreement", signatures=[SIG])
        self.assertEqual(out["stage"], "proposed")

    def test_staff_recommendation_is_support(self):
        out = self.stage("Staff report", PAGES, quote="Staff recommends that the Council support the request.",
                         topic="public_support")
        self.assertEqual((out["stage"], out["claims"][0]["status"]), ("proposed", "supported"))

    def test_minutes_need_a_recorded_action(self):
        voted = ["The Council voted 5 to 2 to support the tax request."]
        talked = ["Members discussed the tax request at length."]
        self.assertEqual(self.stage("Minutes", voted)["stage"], "supported")
        self.assertEqual(self.stage("Minutes", talked)["stage"], "proposed")

    def test_certificate_needs_delivery_wording(self):
        cert = ["As of December 31, 2024, 9 of the 9 required homes were leased. The Owner certifies this."]
        self.assertEqual(self.stage("Annual compliance certificate", cert)["stage"], "delivered")
        self.assertEqual(self.stage("Certificate", ["A note about the homes at the site."])["stage"], "proposed")

    def test_the_model_alone_cannot_mark_delivered(self):
        cert = ["As of December 31, 2024, 9 of the 9 required homes were leased. The Owner certifies this."]
        self.assertEqual(self.stage("Staff memo", cert, model_type="certificate")["stage"], "proposed")

    def test_type_labels(self):
        cases = {"Executed agreement": "agreement", "PILOT and regulatory agreement": "agreement",
                 "Council resolution": "resolution", "Minutes": "minutes", "Developer slides": "slides",
                 "Staff memo": "staff_report", "Later letter": "letter", "Annual compliance certificate": "certificate",
                 "Brochure": "other", None: None}
        for label, key in cases.items():
            self.assertEqual(pipeline.type_key(label), key, label)


def done_doc(id_, stage, date_, claims, type_key="agreement", type_="Agreement"):
    return {"id": id_, "status": "done", "stage": stage, "date": date_, "type_key": type_key, "type": type_,
            "signed": stage == "signed", "signed_by": ["Owner LLC"] if stage == "signed" else [], "claims": claims}


def claim(doc, topic, quote, value, status="signed", date_="2011-06-14"):
    return {"id": f"{doc}-{topic}", "document": doc, "document_type": "Agreement", "topic": topic, "quote": quote,
            "value": value, "status": status, "date": date_, "page": 1}


class Reminders(unittest.TestCase):
    deal = {"id": "x", "name": "Mill", "city": "Lantern Bay"}

    def test_stated_end_date_and_missing_yearly_certificate(self):
        docs = [
            done_doc("a", "signed", "2011-06-14", [
                claim("a", "term", "The period begins on January 1, 2012 and ends on December 31, 2026.", "ends 2026"),
                claim("a", "reporting", "The Owner shall deliver a certificate by March 31 of each year.", "yearly"),
            ]),
            done_doc("c", "delivered", "2025-03-20", [], type_key="certificate", type_="Certificate"),
        ]
        rows = deals.deal_reminders(self.deal, docs, today=date(2026, 11, 7))
        kinds = [(r["kind"], r["date"], r["overdue"]) for r in rows]
        self.assertIn(("term_end", "2026-12-31", False), kinds)
        self.assertIn(("missing_record", "2026-03-31", True), kinds)
        self.assertNotIn(("missing_record", "2025-03-31", True), kinds)  # The 2025 certificate is on file.
        self.assertIn(("other", "2027-03-31", False), kinds)  # Next due date, inside the term.

    def test_term_counted_from_agreement_date(self):
        docs = [done_doc("a", "signed", "2025-07-01", [
            claim("a", "term", "This agreement remains in effect for 15 years.", "15 years", date_="2025-07-01")])]
        rows = deals.deal_reminders(self.deal, docs, today=date(2026, 1, 1))
        self.assertEqual(rows[0]["date"], "2040-07-01")

    def test_term_from_an_undated_event_is_a_question_not_a_reminder(self):
        docs = [done_doc("a", "signed", "2025-09-15", [
            claim("a", "term", "This commitment will last for 15 years from the first move-in date.", "15 years",
                  date_="2025-09-15")], type_key="letter", type_="Letter")]
        self.assertEqual(deals.deal_reminders(self.deal, docs, today=date(2026, 1, 1)), [])
        review = deals.build_deal_review(self.deal, docs)
        self.assertTrue(any(q["key"] == "term_start" for q in review["questions"]))

    def test_unsigned_terms_make_no_reminders(self):
        docs = [done_doc("a", "proposed", "2025-02-03", [
            claim("a", "term", "Staff understands this would last for 30 years.", "30 years", status="proposed"),
            claim("a", "reporting", "The company will explore a yearly report.", "yearly", status="proposed")],
            type_key="staff_report")]
        self.assertEqual(deals.deal_reminders(self.deal, docs, today=date(2026, 1, 1)), [])


class ReviewShape(unittest.TestCase):
    def test_deal_review_has_the_demo_keys(self):
        demo = set(ledger.build_review())
        docs = [done_doc("a", "signed", "2025-07-01", [
            claim("a", "units", "The Owner shall reserve 16 of the 80 homes.", "16 of 80 homes", date_="2025-07-01")])]
        review = deals.build_deal_review({"id": "x", "name": "B", "city": "Lantern Bay"}, docs)
        self.assertLessEqual(demo - {"notice"}, set(review))
        for key in ("kpis", "what_changed", "open_questions", "receipt"):
            self.assertIn(key, review)
        self.assertEqual(len(review["receipt"]), len(ledger.TERMS))


if __name__ == "__main__":
    unittest.main()
