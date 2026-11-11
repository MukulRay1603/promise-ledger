"""Rules widened to find more of a record's commitments: quote location and term vocabulary.

The sentences are ordinary drafting wording written for these tests. None is copied from an evaluation set.
Each rule is tested both ways: what it now keeps, and what it must still reject.
"""
import unittest

from app import ai, pipeline


def reading(*candidates, kind="agreement"):
    return ai.PdfReading(document_type=kind, title="T", date="", draft=False, signatures=[], candidates=[
        ai.PdfCandidate(topic=topic, quote=quote, page=page, wording="", value="") for topic, quote, page in candidates])


class QuoteLocation(unittest.TestCase):
    def test_first_letter_case_after_a_dropped_lead_in(self):
        page = "WHEREAS, the Owner will reserve 20 of the 100 homes as affordable homes; and\nNOW, THEREFORE, the City agrees."
        self.assertTrue(pipeline.quote_on_page("The Owner will reserve 20 of the 100 homes as affordable homes", page))
        self.assertEqual(pipeline.printed_wording("The Owner will reserve 20 of the 100 homes as affordable homes", page),
                         "the Owner will reserve 20 of the 100 homes as affordable homes")
        # Only the first letter may differ. Any other change is still a different quote.
        self.assertFalse(pipeline.quote_on_page("The owner will reserve 20 of the 100 homes as affordable homes", page))
        self.assertFalse(pipeline.quote_on_page("The Owner will reserve 21 of the 100 homes as affordable homes", page))

    def test_the_stored_quote_is_the_records_wording(self):
        page = "WHEREAS, the Owner will reserve 20 of the 100 homes as affordable homes; and"
        out = pipeline.verify_reading(reading(("units", "The Owner will reserve 20 of the 100 homes as affordable homes", 1)),
                                      [page], {"id": "d", "type": "Resolution"})
        self.assertEqual(out["claims"][0]["quote"], "the Owner will reserve 20 of the 100 homes as affordable homes")
        self.assertIn(out["claims"][0]["quote"], pipeline.normalize(page))

    def test_spaces_added_by_the_text_layer(self):
        page = "The Owner will pay $ 500 per home under Section 7 -506 of the Tax -\nProperty Article each year."
        self.assertTrue(pipeline.quote_on_page("The Owner will pay $500 per home under Section 7-506 of the Tax-Property Article", page))
        self.assertFalse(pipeline.quote_on_page("The Owner will pay $600 per home under Section 7-506 of the Tax-Property Article", page))

    def test_sentence_that_crosses_a_page_break(self):
        pages = ["Cover page.\nPage 1 of 3\nRiver Deal 2291.7",
                 "The Owner shall keep 20 homes affordable to households earning up to\n \n2\nPage 2 of 3\nRiver Deal 2291.7",
                 "River Deal 2291.7\n60 percent of area median income for 30 years.\nNothing else.\nPage 3 of 3"]
        quote = "The Owner shall keep 20 homes affordable to households earning up to 60 percent of area median income for 30 years."
        self.assertFalse(pipeline.quote_on_page(quote, pages[1]))
        self.assertEqual(pipeline.locate(quote, pages, 2), 2)  # Cited to the page where it starts,
        self.assertEqual(pipeline.locate(quote, pages, 3), 2)  # also when the model cites the page where it ends.
        self.assertTrue(pipeline.quote_at(quote, pages, 2))
        self.assertFalse(pipeline.quote_at(quote, pages, 3))
        self.assertFalse(pipeline.quote_at(quote, pages, 1))
        out = pipeline.verify_reading(reading(("income_basis", quote, 3)), pages, {"id": "d", "type": "Agreement"})
        claim = out["claims"][0]
        self.assertEqual((claim["page"], claim["ends_on_page"], claim["page_corrected"]), (2, 3, True))

    def test_a_break_does_not_join_unrelated_text(self):
        pages = ["The Owner shall keep 20 homes affordable.\nOther business followed.", "Minutes were approved for 30 years."]
        # The words are not next to each other across the break, so this is not a quote from the record.
        self.assertIsNone(pipeline.locate("The Owner shall keep 20 homes affordable for 30 years.", pages, 1))
        # A quote that is whole on one page is never reported as crossing a break.
        self.assertIsNone(pipeline.wording_across_pages("The Owner shall keep 20 homes affordable.", pages, 1))

    def test_piece_of_a_kept_sentence_is_not_a_second_claim(self):
        whole = "The Owner shall keep 20 of the 100 homes affordable to households at or below 60 percent of area median income."
        piece = "20 of the 100 homes affordable to households at or below 60 percent of area median income"
        for order in ([whole, piece], [piece, whole]):
            out = pipeline.verify_reading(reading(*[("income_basis", q, 1) for q in order]), [whole], {"id": "d", "type": "Agreement"})
            self.assertEqual([c["quote"] for c in out["claims"]], [whole])
            self.assertEqual([c["id"] for c in out["claims"]], ["d-01"])
            self.assertEqual(out["counts"]["duplicates"], 1)
        # Under another term the piece is its own claim.
        out = pipeline.verify_reading(reading(("income_basis", whole, 1), ("units", piece, 1)), [whole], {"id": "d", "type": "Agreement"})
        self.assertEqual(len(out["claims"]), 2)


class TermVocabulary(unittest.TestCase):
    def fits(self, topic, quote):
        return pipeline.term_fits(topic, quote)

    def test_term(self):
        for quote in ["The covenants stay in force through December 31, 2060.",
                      "The restrictions expire on the fortieth anniversary of first occupancy.",
                      "These covenants run with the land in perpetuity.",
                      "The Owner may request an extension for two (2) periods of ten (10) years each.",
                      "The affordability restrictions continue in full force and effect until released by the City."]:
            self.assertTrue(self.fits("term", quote), quote)
        self.assertFalse(self.fits("term", "Sections 2 through 4 apply to the Owner."))
        self.assertFalse(self.fits("term", "The Owner shall build the homes."))

    def test_term_in_a_sentence_that_names_the_tax_break(self):
        keep = "As a condition of the abatement, the Owner shall restrict the homes to eligible households for 40 years."
        self.assertTrue(self.fits("term", keep))
        self.assertEqual(pipeline.compare_key("term", keep), "40 years")
        # A tax period with no restriction in the sentence is still not the affordability term.
        for quote in ["The City Council approves a payment in lieu of taxes for 15 years.",
                      "The tax abatement lasts 10 years.",
                      "In exchange for 12 affordable homes, the Council approves a tax abatement for 10 years."]:
            self.assertFalse(self.fits("term", quote), quote)
            self.assertIsNone(pipeline.compare_key("term", quote))

    def test_definition_that_carries_the_value(self):
        term = '"Affordability Period" means the period of thirty (30) years that begins on the first Tax Year after completion.'
        self.assertFalse(pipeline.is_boilerplate(term, set()))
        self.assertTrue(self.fits("term", term))
        self.assertEqual(pipeline.compare_key("term", term), "30 years")
        self.assertFalse(pipeline.is_boilerplate('(c) "Affordable Home" means a home leased to a household at or below 60 percent '
                                                 'of area median income.', set()))
        # A definition with no value explains a word. A definition of something else is not the term.
        self.assertTrue(pipeline.is_boilerplate('"Area Median Income" means the median income for the county, as published each year.', set()))
        self.assertTrue(pipeline.is_boilerplate('"Affordable Homes" means, collectively, the homes described in Section 2.', set()))
        self.assertFalse(self.fits("term", '"Tax Year" means the period beginning July 1 and ending the next June 30.'))

    def test_units(self):
        self.assertTrue(self.fits("units", "The zoning district requires 15% of the units to be rented at set rates."))
        self.assertTrue(self.fits("units", "The developer plans to offer 30 apartments at below-market rents."))
        self.assertFalse(self.fits("units", "The project will have 300 apartments in two buildings."))
        self.assertFalse(self.fits("units", "Affordable Homes required (Section 4.1)"))

    def test_income_basis(self):
        self.assertTrue(self.fits("income_basis", "The lower tier serves households earning up to 40% of the county figure."))
        self.assertFalse(self.fits("income_basis", "The lower tier is on the second floor."))

    def test_public_support(self):
        for quote in ["The developer has asked the City to freeze the taxable value of the site for eight years.",
                      "The City shall hold the assessment at its 2024 level for eight years.",
                      "The applicant requests a rebate of sales tax on building materials.",
                      "The County shall abate all County real property taxes for the project.",
                      "The Owner shall make annual payments of $300 for each home in place of property taxes.",
                      "The developer is offering a payment in lieu of taxes of $300 per home per year.",
                      "With the abatement there is a tax revenue loss of $4 million over 20 years.",
                      "The City agrees to waive the permit fees and to exempt the project from the school tax."]:
            self.assertTrue(self.fits("public_support", quote), quote)
        for quote in ["Payments are due each year on the date property taxes would otherwise be due.",
                      "State law provides incentives, such as waivers and payments in lieu of taxes, for projects near transit.",
                      "The financial statements show that a tax abatement is necessary to make the project feasible.",
                      "Council Member Ortiz moved to freeze the taxable value of the site."]:
            self.assertFalse(self.fits("public_support", quote), quote)

    def test_reporting(self):
        for quote in ["Every year by April 15, the Owner shall send the City a rent roll for the restricted homes.",
                      "The builder gives the Town a yearly list of the restricted homes.",
                      "The Owner shall submit such other reports as the County may reasonably require.",
                      "The Owner must furnish an audited financial statement on request."]:
            self.assertTrue(self.fits("reporting", quote), quote)
        for quote in ["The City may inspect the leasing records on 10 days' notice.",
                      "Staff will send a second notice asking for the certificate by May 15, 2026.",
                      "The certificate shall state counts only and shall not include household names.",
                      "The Owner shall give the City 30 days' written notice before any sale."]:
            self.assertFalse(self.fits("reporting", quote), quote)

    def test_remedies(self):
        for quote in ["If a violation continues for 30 days after notice, the Town may end the tax freeze.",
                      "If the conditions are not met by June 30, 2030, this Agreement shall be null and void.",
                      "A late charge of one percent per month applies to any unpaid amount.",
                      "The City may revoke the exemption and all abated taxes become due and payable.",
                      "The Village may suspend the rebate until the report is received."]:
            self.assertTrue(self.fits("remedies", quote), quote)
        for quote in ["The City may also seek any other remedy available at law or in equity.",
                      "The rebate is paid only while each condition in Exhibit A is met.",
                      "The Owner shall avoid delays in leasing the homes."]:
            self.assertFalse(self.fits("remedies", quote), quote)

    def test_responsible_party(self):
        for quote in ["This Agreement shall be binding upon all successors and assigns of the Owner.",
                      "Any assignee shall be bound by the covenants.",
                      "The covenants apply to the Owner and all subsequent owners of the property."]:
            self.assertTrue(self.fits("responsible_party", quote), quote)
        self.assertFalse(self.fits("responsible_party", "The Owner shall give the City 30 days' notice before any sale."))
        self.assertFalse(self.fits("responsible_party", "Notices go to the Owner at 12 Main Street."))

    def test_a_record_describing_itself(self):
        self.assertTrue(pipeline.is_boilerplate("This is a request for a recommendation on the tax abatement.", set()))

    def test_rejected_sentences_are_still_set_aside(self):
        quote = "The City may inspect the leasing records on 10 days' notice."
        out = pipeline.verify_reading(reading(("reporting", quote, 1)), [quote], {"id": "d", "type": "Agreement"})
        self.assertEqual(out["claims"], [])
        self.assertEqual([x["quote"] for x in out["set_aside"]], [quote])

    def test_wider_rules_never_set_a_stage(self):
        # Every new word list is used by term_fits only. An unsigned agreement stays proposed whatever it says.
        page = ("AGREEMENT\nThis Agreement shall be binding upon all successors and assigns of the Owner.\n"
                "If the conditions are not met, this Agreement shall be null and void.\nBy: ____________")
        out = pipeline.verify_reading(reading(
            ("responsible_party", "This Agreement shall be binding upon all successors and assigns of the Owner.", 1),
            ("remedies", "If the conditions are not met, this Agreement shall be null and void.", 1)), [page], {"id": "d"})
        self.assertEqual(out["stage"], "proposed")
        self.assertEqual({c["status"] for c in out["claims"]}, {"proposed"})
        self.assertEqual(len(out["claims"]), 2)


if __name__ == "__main__":
    unittest.main()
