"""Upload assistant: which records to ask for next, decided by rule; and seeding that does not block startup."""
import os
import threading
import unittest
from unittest import mock

from app import deals, ledger, storage


def claim(topic, status="proposed", i=0):
    return {"id": f"c{topic}{i}", "topic": topic, "status": status, "value": "x", "date": "2025-01-01",
            "quote": "q", "document_type": "Letter", "page": 1}


def records(claims, docs=()):
    return deals.next_records(claims, ledger.build_terms(claims), list(docs))


class NextRecords(unittest.TestCase):
    def test_nothing_located_is_left_to_the_note(self):
        self.assertEqual(records([]), [])

    def test_unsigned_deal_asks_for_the_signed_agreement_and_minutes(self):
        out = records([claim("units")], [{"type_key": "letter"}])
        keys = [r["key"] for r in out]
        self.assertEqual(keys, ["agreement", "staff_report", "minutes"])
        self.assertEqual(out[0]["terms"], ["Term", "Responsible party", "Reporting", "Remedies"])
        self.assertEqual(out[1]["terms"], ["Income limit", "Rent limits"])

    def test_staff_report_on_file_points_to_the_exhibit(self):
        out = records([claim("units", "supported")], [{"type_key": "staff_report"}, {"type_key": "minutes"}])
        self.assertIn("exhibit", [r["key"] for r in out])
        self.assertNotIn("staff_report", [r["key"] for r in out])
        self.assertNotIn("minutes", [r["key"] for r in out])

    def test_signed_deal_asks_for_missing_pages_and_delivery(self):
        signed = [claim(t, "signed") for t in ("units", "income_basis", "rent_limits", "term", "responsible_party", "reporting")]
        out = records(signed, [{"type_key": "agreement"}])
        self.assertEqual([r["key"] for r in out], ["agreement_full", "delivery"])
        self.assertEqual(out[0]["terms"], ["Remedies"])

    def test_complete_delivered_deal_needs_nothing(self):
        located = [claim(t, "signed") for t in ledger.TERMS] + [claim("units", "delivered", 1)]
        self.assertEqual(records(located, [{"type_key": "agreement"}, {"type_key": "certificate"}]), [])

    def test_wording_stays_in_house_terms(self):
        text = " ".join(r["record"] + " " + r["why"] for r in records([claim("units")])).lower()
        for banned in ("public housing", "price", "listing"):
            self.assertNotIn(banned, text)


class StartupSeeding(unittest.TestCase):
    def test_default_seeds_in_a_thread(self):
        from fastapi.testclient import TestClient
        from app import main
        started = threading.Event()
        gate = threading.Event()

        def slow_seed():
            started.set()
            gate.wait(5)

        with mock.patch.dict(os.environ, {"SEED": "1"}), mock.patch.object(main, "_startup_seed", slow_seed):
            with TestClient(main.app) as client:  # Serves while the seed is still running.
                self.assertTrue(started.wait(2))
                self.assertEqual(client.get("/api/health").status_code, 200)
            gate.set()

    def test_store_is_built_once_under_threads(self):
        previous = storage._store
        storage.set_store(None)
        try:
            with mock.patch.object(storage, "LocalStorage", side_effect=lambda: object()) as built:
                threads = [threading.Thread(target=storage.get_store) for _ in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            self.assertEqual(built.call_count, 1)
        finally:
            storage.set_store(previous)


if __name__ == "__main__":
    unittest.main()
