"""Code rules that keep a candidate only if it states the term it is filed under."""
import json
import unittest
from pathlib import Path

from app import ai, pipeline

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


class TermFit(unittest.TestCase):
    def fits(self, topic, quote):
        return pipeline.term_fits(topic, quote)

    def test_units_need_a_home_count_and_affordability(self):
        self.assertTrue(self.fits("units", "The Owner shall reserve 16 of the 80 homes as Affordable Homes."))
        self.assertTrue(self.fits("units", "Harbor Walk Partners will explore setting aside up to 12 homes at reduced rents."))
        self.assertFalse(self.fits("units", 'The Owner is building an 80-home rental project (the "Project").'))
        self.assertFalse(self.fits("units", "Affordable Homes required (Section 4.1)"))

    def test_term_is_not_a_tax_period(self):
        self.assertTrue(self.fits("term", "The requirements shall remain in effect for 30 years from the first lease."))
        self.assertFalse(self.fits("term", "The City Council approves a payment in lieu of taxes for 15 years."))

    def test_reporting_needs_a_cadence(self):
        self.assertTrue(self.fits("reporting", "The owner will file an annual compliance certificate by March 1 of each year."))
        self.assertTrue(self.fits("reporting", "This certificate is submitted under Section 7.1 for reporting year 2024."))
        self.assertFalse(self.fits("reporting", "The City may inspect the leasing records on 10 days' notice."))
        self.assertFalse(self.fits("reporting", "Staff will send a second notice asking for the certificate by May 15, 2026."))
        self.assertFalse(self.fits("reporting", "The certificate for reporting year 2025 is marked not received."))

    def test_remedies_rent_party_and_support(self):
        self.assertTrue(self.fits("remedies", "If a default is not cured within 60 days, the Owner shall repay all abated taxes."))
        self.assertFalse(self.fits("remedies", "The City may also seek any other remedy available at law or in equity."))
        self.assertTrue(self.fits("rent_limits", "Monthly rent shall not exceed the 60 percent rent limit."))
        self.assertFalse(self.fits("rent_limits", "Harbor Walk Partners will explore 12 homes at reduced rents."))
        self.assertTrue(self.fits("responsible_party", "The Owner is responsible for compliance with this Agreement."))
        self.assertFalse(self.fits("responsible_party", "The Owner shall give the City 30 days' notice before any sale."))
        self.assertTrue(self.fits("public_support", "The Council voted 5 to 2 to support the tax request."))
        self.assertTrue(self.fits("public_support", "The Council asked staff to confirm the terms in writing."))
        self.assertFalse(self.fits("public_support", "Council Member (Seat 3) moved to support the tax request."))

    def test_boilerplate(self):
        chrome = pipeline.repeated_lines(["SAMPLE DOCUMENT · fictional\nHarbor Walk will provide 12 homes.",
                                          "SAMPLE DOCUMENT · fictional\nThe term is 15 years."])
        self.assertTrue(pipeline.is_boilerplate("SAMPLE DOCUMENT · fictional", chrome))
        self.assertTrue(pipeline.is_boilerplate("This memo reports the status of the yearly certificates.", set()))
        self.assertTrue(pipeline.is_boilerplate('"Area Median Income" means the median income for the county.', set()))
        self.assertFalse(pipeline.is_boilerplate("Harbor Walk will provide 12 homes.", chrome))

    def test_same_sentence_under_two_terms_is_one_claim(self):
        quote = "Each Affordable Home shall be leased to a household at or below 60 percent of area median income."
        reading = ai.PdfReading(document_type="agreement", title="T", date="", draft=False, signatures=[], candidates=[
            ai.PdfCandidate(topic="income_basis", quote=quote, page=1, wording="shall be leased", value="60%"),
            ai.PdfCandidate(topic="units", quote=quote, page=1, wording="shall be leased", value="homes")])
        out = pipeline.verify_reading(reading, [quote], {"id": "d", "type": "Agreement"})
        self.assertEqual([c["topic"] for c in out["claims"]], ["income_basis"])
        self.assertEqual(out["counts"]["off_term"] + out["counts"]["duplicates"], 1)


@unittest.skipUnless(SAMPLES.exists(), "sample deals not present")
class GoldPassesTheRules(unittest.TestCase):
    def test_no_gold_claim_is_filtered_out(self):
        for gold_path in sorted(SAMPLES.glob("*/expected_claims.json")):
            pages_by_file = {}
            for claim in json.loads(gold_path.read_text(encoding="utf-8"))["claims"]:
                if claim["file"] not in pages_by_file:
                    pages_by_file[claim["file"]] = pipeline.extract_pages((gold_path.parent / claim["file"]).read_bytes())
                pages = pages_by_file[claim["file"]]
                with self.subTest(claim=claim["id"]):
                    self.assertTrue(pipeline.term_fits(claim["term"], claim["quote"]))
                    self.assertFalse(pipeline.is_boilerplate(claim["quote"], pipeline.repeated_lines(pages)))


if __name__ == "__main__":
    unittest.main()
