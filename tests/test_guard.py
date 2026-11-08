"""Public demo guard: rate limits on uploads and new deals, and expiry of visitor deals."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import ai, deals, guard, pipeline, storage
from app.main import app
from tests.test_deals_api import letter_pdf, stub_reading
from tests.test_sample_refresh import SAMPLES, Firestore, Gcs, no_model

OLD = "2020-01-01T00:00:00+00:00"
READINGS = pipeline.READINGS_DIR  # Cached sample readings, so seeding needs no model.


class GuardSetup(unittest.TestCase):
    demo_mode = "1"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = self.make_store()
        storage.set_store(self.store)
        self.addCleanup(storage.set_store, None)
        for patcher in (mock.patch.dict(os.environ, {"DEMO_MODE": self.demo_mode}),
                        mock.patch.object(pipeline, "READINGS_DIR", Path(self.tmp.name) / "readings"),
                        mock.patch.object(deals, "run_inline", True),
                        mock.patch.object(ai, "read_document", side_effect=stub_reading),
                        mock.patch.object(guard, "maybe_sweep", return_value=False)):  # Sweeps are run by hand here.
            patcher.start()
            self.addCleanup(patcher.stop)
        guard.reset_limits()
        self.addCleanup(guard.reset_limits)
        self.client = TestClient(app)

    def make_store(self):
        return storage.LocalStorage(Path(self.tmp.name) / "runtime")

    # Cloud Run appends the address it saw, so the client's real IP is the last X-Forwarded-For hop.
    def new_deal(self, ip="203.0.113.7", spoof="10.0.0.1"):
        return self.client.post("/api/deals", json={"name": "Test deal", "city": "Lantern Bay"},
                                headers={"X-Forwarded-For": f"{spoof}, {ip}"})

    def upload(self, deal_id, ip="203.0.113.7", spoof=None):
        hops = f"{spoof}, {ip}" if spoof else ip
        return self.client.post(f"/api/deals/{deal_id}/documents", headers={"X-Forwarded-For": hops},
                                files={"file": ("letter.pdf", letter_pdf(), "application/pdf")})


class RateLimits(GuardSetup):
    def test_new_deals_hit_429_with_retry_after(self):
        for _ in range(3):
            self.assertEqual(self.new_deal().status_code, 201)
        r = self.new_deal()
        self.assertEqual(r.status_code, 429)
        self.assertGreater(int(r.headers["Retry-After"]), 0)
        self.assertIn("public demo allows 3 new deals an hour", r.json()["detail"])
        self.assertEqual(self.new_deal(ip="198.51.100.2").status_code, 201)  # Another network is not affected.

    def test_uploads_hit_429_and_reset_after_the_window(self):
        deal_id = self.new_deal().json()["id"]
        clock = [1000.0]
        with mock.patch("app.guard.time.monotonic", side_effect=lambda: clock[0]):
            for _ in range(5):
                self.assertEqual(self.upload(deal_id).status_code, 202)
            r = self.upload(deal_id)
            self.assertEqual(r.status_code, 429)
            self.assertEqual(r.headers["Retry-After"], "3600")
            self.assertIn("5 uploads an hour", r.json()["detail"])
            clock[0] += 1800
            self.assertEqual(self.upload(deal_id).status_code, 429)
            clock[0] += 1801  # The first hits have left the window.
            self.assertEqual(self.upload(deal_id).status_code, 202)

    def test_limits_come_from_env(self):
        with mock.patch.dict(os.environ, {"RATE_LIMIT_DEALS_PER_HOUR": "1"}):
            self.assertEqual(self.new_deal().status_code, 201)
            self.assertEqual(self.new_deal().status_code, 429)

    def test_reads_are_not_limited_and_carry_the_demo_header(self):
        for _ in range(20):
            r = self.client.get("/api/deals")
            self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("x-demo-mode"), "1")

    def test_last_forwarded_hop_is_the_client(self):
        def req(headers):
            return mock.Mock(headers=headers, client=mock.Mock(host="10.0.0.2"))
        self.assertEqual(guard.client_ip(req({"x-forwarded-for": "1.2.3.4, 203.0.113.7"})), "203.0.113.7")
        self.assertEqual(guard.client_ip(req({"x-forwarded-for": "203.0.113.7"})), "203.0.113.7")
        self.assertEqual(guard.client_ip(req({})), "10.0.0.2")

    def test_spoofed_first_hop_does_not_bypass_the_limit(self):
        deal_id = self.new_deal().json()["id"]
        for n in range(5):
            self.assertEqual(self.upload(deal_id, spoof=f"192.0.2.{n}").status_code, 202)
        self.assertEqual(self.upload(deal_id, spoof="192.0.2.99").status_code, 429)
        for n in range(2):
            self.assertEqual(self.new_deal(spoof=f"192.0.2.{n}").status_code, 201)
        self.assertEqual(self.new_deal(spoof="192.0.2.50").status_code, 429)

    def test_visitor_deals_and_uploads_are_marked_demo(self):
        deal_id = self.new_deal().json()["id"]
        self.upload(deal_id)
        self.assertTrue(self.store.get_deal(deal_id)["demo"])
        self.assertTrue(all(d["demo"] for d in self.store.list_documents(deal_id)))


class Expiry(GuardSetup):
    def age(self, deal_id, hours):
        deal = self.store.get_deal(deal_id)
        deal["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        self.store.put_deal(deal)

    def test_only_old_demo_deals_are_deleted(self):
        old = self.new_deal().json()["id"]
        self.upload(old)
        doc = self.store.list_documents(old)[0]
        fresh = self.new_deal().json()["id"]
        staff = deals.create_deal("Staff deal", "Lantern Bay", store=self.store, demo=False)
        self.age(old, 25)
        self.age(fresh, 23)
        self.age(staff["id"], 100)
        self.assertEqual(guard.sweep(self.store)["deals"], [old])
        self.assertIsNone(self.store.get_deal(old))
        self.assertEqual(self.store.list_documents(old), [])
        self.assertIsNone(self.store.get_blob(doc["file_key"]))
        self.assertIsNotNone(self.store.get_deal(fresh))
        self.assertIsNotNone(self.store.get_deal(staff["id"]))
        self.assertEqual(guard.sweep(self.store)["deals"], [])  # Idempotent.

    def unflagged(self, hours):
        """A visitor deal from before demo flags existed: no "demo" key."""
        deal = deals.create_deal("Old visitor deal", "Lantern Bay", store=self.store)
        deal.pop("demo")
        deal["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        self.store.put_deal(deal)
        return deal["id"]

    def test_old_deals_without_a_flag_are_swept_once(self):
        old, fresh = self.unflagged(25), self.unflagged(2)
        staff = deals.create_deal("Staff deal", "Lantern Bay", store=self.store, demo=False)
        self.age(staff["id"], 100)
        self.assertEqual(guard.sweep(self.store)["deals"], [old])
        self.assertIsNotNone(self.store.get_deal(fresh))
        self.assertIsNotNone(self.store.get_deal(staff["id"]))
        self.assertEqual(guard.sweep(self.store)["deals"], [])

    def test_ttl_comes_from_env(self):
        deal_id = self.new_deal().json()["id"]
        self.age(deal_id, 3)
        with mock.patch.dict(os.environ, {"DEMO_TTL_HOURS": "2"}):
            self.assertEqual(guard.sweep(self.store)["deals"], [deal_id])

    def test_another_instance_sweeping_skips(self):
        deal_id = self.new_deal().json()["id"]
        self.age(deal_id, 25)
        self.assertTrue(self.store.acquire_lock(guard.SWEEP_LOCK, "other", 600))
        self.assertEqual(guard.sweep(self.store, owner="me")["deals"], [])
        self.store.release_lock(guard.SWEEP_LOCK, "other")
        self.assertEqual(guard.sweep(self.store, owner="me")["deals"], [deal_id])


@unittest.skipUnless((SAMPLES / "harbor-walk" / "manifest.json").exists(), "sample deals not present")
class SamplesAreKept(GuardSetup):
    def setUp(self):
        super().setUp()
        with mock.patch.object(ai, "read_document", side_effect=no_model), \
                mock.patch.object(pipeline, "READINGS_DIR", READINGS):
            deals.refresh_samples(self.store, SAMPLES)
        for deal in self.store.list_deals():
            deal.update(created_at=OLD, demo=True)  # Even a sample marked demo by mistake is kept.
            self.store.put_deal(deal)

    def doc_ids(self):
        return {d["id"]: sorted(x["id"] for x in self.store.list_documents(d["id"])) for d in self.store.list_deals()}

    def test_samples_are_never_deleted(self):
        before = self.doc_ids()
        self.assertEqual(sorted(before), ["beacon-point", "harbor-walk", "mill-street"])
        self.assertEqual(guard.sweep(self.store), {"deals": [], "documents": []})
        self.assertEqual(self.doc_ids(), before)

    def test_samples_without_a_demo_flag_are_not_migrated_away(self):
        before = self.doc_ids()
        for deal in self.store.list_deals():  # As stored before demo flags existed.
            deal.pop("demo", None)
            self.store.put_deal(deal)
        self.assertEqual(guard.sweep(self.store), {"deals": [], "documents": []})
        self.assertEqual(self.doc_ids(), before)

    def test_old_visitor_uploads_on_a_sample_are_removed(self):
        seeded = self.doc_ids()["harbor-walk"]
        self.assertEqual(self.upload("harbor-walk").status_code, 202)
        visitor = next(d for d in self.store.list_documents("harbor-walk") if d.get("demo"))
        visitor["created_at"] = OLD
        self.store.put_document("harbor-walk", visitor)
        self.assertEqual(guard.sweep(self.store)["documents"], [f"harbor-walk/{visitor['id']}"])
        self.assertEqual(self.doc_ids()["harbor-walk"], seeded)
        self.assertIsNone(self.store.get_blob(visitor["file_key"]))
        self.assertIsNotNone(self.store.get_blob(self.store.list_documents("harbor-walk")[0]["file_key"]))


class GcpExpiry(Expiry):
    def make_store(self):
        return storage.GcpStorage(Firestore(), Gcs(), bucket="pl-files")


class GcpSamplesAreKept(SamplesAreKept):
    def make_store(self):
        return storage.GcpStorage(Firestore(), Gcs(), bucket="pl-files")


class DemoModeOff(GuardSetup):
    demo_mode = "0"

    def test_no_rate_limits(self):
        for _ in range(6):
            self.assertEqual(self.new_deal().status_code, 201)
        deal_id = self.new_deal().json()["id"]
        for _ in range(7):
            self.assertEqual(self.upload(deal_id).status_code, 202)

    def test_no_demo_marks_no_sweep_no_header(self):
        r = self.new_deal()
        self.assertNotIn("x-demo-mode", r.headers)
        deal_id = r.json()["id"]
        self.upload(deal_id)
        self.assertIs(self.store.get_deal(deal_id)["demo"], False)
        self.assertFalse(any(d.get("demo") for d in self.store.list_documents(deal_id)))
        deal = self.store.get_deal(deal_id)
        deal.update(demo=True, created_at=OLD)
        self.store.put_deal(deal)
        unflagged = {**deal, "id": "old-visitor-deal", "created_at": OLD}
        unflagged.pop("demo")
        self.store.put_deal(unflagged)  # The migration only runs in demo mode.
        with mock.patch.object(self.store, "acquire_lock", side_effect=AssertionError("no sweep")):
            self.assertEqual(guard.sweep(self.store), {"deals": [], "documents": []})
        self.assertIsNotNone(self.store.get_deal(deal_id))
        self.assertIsNotNone(self.store.get_deal("old-visitor-deal"))


class HourlySweep(unittest.TestCase):
    def test_at_most_once_an_hour_per_instance(self):
        clock = [5000.0]
        with mock.patch.object(guard, "_last_sweep", 0.0), mock.patch.object(guard, "sweep") as sweep, \
                mock.patch("app.guard.time.monotonic", side_effect=lambda: clock[0]):
            self.assertTrue(guard.maybe_sweep(background=False))  # First request after start.
            clock[0] += 600
            self.assertFalse(guard.maybe_sweep(background=False))
            clock[0] += 3000
            self.assertTrue(guard.maybe_sweep(background=False))
        self.assertEqual(sweep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
