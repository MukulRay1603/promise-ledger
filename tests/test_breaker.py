"""The main-model circuit breaker: one busy answer rests the main model; the fallback reads until it wakes."""
import unittest
from unittest import mock

from app import ai


class Busy(Exception):
    code = 503


class Breaker(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch.object(ai, "MAIN_COOLDOWN_SECONDS", 600), mock.patch.object(ai, "_main_resting_until", 0.0),
                      mock.patch.object(ai, "FALLBACK_MODEL", "fallback-model")):
            patch.start()
            self.addCleanup(patch.stop)

    def test_after_one_busy_section_later_sections_go_straight_to_the_fallback(self):
        calls = []

        def call(record, model):
            calls.append(model)
            if model == ai.MODEL:
                raise Busy()
            return ai.PdfReading.model_construct(candidates=[]), 10, 5

        with mock.patch.object(ai, "_call_pdf_model", side_effect=call):
            ai._read_section("one")
            ai._read_section("two")
            ai._read_section("three")
        self.assertEqual(calls, [ai.MODEL, "fallback-model", "fallback-model", "fallback-model"])

    def test_the_main_model_is_tried_again_after_the_rest(self):
        ai.note_busy(ai.MODEL)
        self.assertEqual(ai.first_model(), "fallback-model")
        with mock.patch.object(ai.time, "monotonic", return_value=ai._main_resting_until + 1):
            self.assertEqual(ai.first_model(), ai.MODEL)

    def test_a_busy_fallback_does_not_rest_the_main_model(self):
        ai.note_busy("fallback-model")
        self.assertEqual(ai.first_model(), ai.MODEL)


if __name__ == "__main__":
    unittest.main()
